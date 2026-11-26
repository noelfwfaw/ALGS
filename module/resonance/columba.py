"""Columba Chamber of Commerce (resonance-columba.com) data and HTTP client."""

import copy
import json
import os
import time
import urllib.request

import requests

COLUMBA_BASE_URL = 'https://www.resonance-columba.com'
DATA_PATH = os.path.join(os.path.dirname(__file__), 'columba_data.json')

PRESTIGE_CITIES = (
    '修格里城', '曼德矿场', '澄明数据中心', '七号自由港', '阿妮塔发射中心', '海角城',
    '铁山城', '贡露城', '岚心城', '塔图站', '雪金城', '武林源',
)

PRESTIGE_TABLE = {
    level: {
        'generalTax': round(0.1 - 0.005 * (level // 2), 4),
        'specialTax': {
            '七号自由港': round(0.07 - 0.005 * (level // 2), 4),
            '阿妮塔能源研究所': round(0.07 - 0.005 * (level // 2), 4),
        },
        'extraBuy': round(level * 0.1, 4),
    }
    for level in range(1, 21)
}

GAME_EVENTS = (
    {
        'name': '红茶战争',
        'playConfigurable': True,
        'buyMore': {'product': {'红茶': 50}},
        'taxVariation': {'product': {'红茶': -0.05}},
    },
)

DEFAULT_PLAYER_CONFIG = {
    'maxLot': 500,
    'tradeLevel': 20,
    'bargain': {
        'bargainPercent': 0,
        'raisePercent': 0,
        'bargainFatigue': 0,
        'raiseFatigue': 0,
        'disabled': False,
    },
    'returnBargain': {
        'bargainPercent': 0,
        'raisePercent': 0,
        'bargainFatigue': 0,
        'raiseFatigue': 0,
        'disabled': False,
    },
    'prestige': {city: 1 for city in PRESTIGE_CITIES},
    'roles': {},
    'onegraph': {
        'maxRestock': 5,
        'goAndReturn': False,
    },
    'productUnlockStatus': {},
    'events': {},
    'excludedCities': [],
    'allExchangesBuyMorePercent': 0,
    'productsBuyMorePercent': {},
}

_DATA_CACHE = {}
_PRICE_CACHE = {'ts': 0.0, 'prices': None}


def _normalized_proxies():
    """Normalize localhost https:// proxy URLs to http:// for urllib3 1.24 compatibility."""
    proxies = {}
    for scheme, proxy_url in urllib.request.getproxies().items():
        if proxy_url.startswith('https://127.0.0.1') or proxy_url.startswith('https://localhost'):
            proxies[scheme] = 'http://' + proxy_url[len('https://'):]
        else:
            proxies[scheme] = proxy_url
    return proxies


def http_request(method, url, json_body=None, timeout=15):
    """Send an HTTP request directly first, falling back to normalized system proxies."""
    headers = {'User-Agent': 'Mozilla/5.0'}
    direct = requests.Session()
    direct.trust_env = False
    try:
        resp = direct.request(method, url, json=json_body, timeout=timeout, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        proxies = _normalized_proxies()
        if not proxies:
            raise
        proxied = requests.Session()
        proxied.trust_env = False
        resp = proxied.request(method, url, json=json_body, timeout=timeout, headers=headers, proxies=proxies)
        resp.raise_for_status()
        return resp.json()


def _index_products_by_city(products, cities):
    """Group buyable products under each origin city."""
    grouped = {city: [] for city in cities}
    for product in products:
        _append_product_cities(grouped, product)
    return grouped


def _append_product_cities(grouped, product):
    """Register one product into each origin city bucket where it is sold."""
    for city in product.get('buyPrices', {}):
        if city in grouped:
            grouped[city].append(product)


def load_columba_data(path=None):
    """Load and index static Columba trade tables from JSON."""
    target = os.path.abspath(path or DATA_PATH)
    cached = _DATA_CACHE.get(target)
    if cached is not None:
        return cached

    with open(target, 'r', encoding='utf-8') as f:
        raw = json.load(f)

    products = raw['products']
    cities = raw['cities']
    fatigue_map = {}
    for row in raw['city_fatigues']:
        pair = row.get('cities', ())
        if len(pair) == 2:
            fatigue_map[frozenset(pair)] = row.get('fatigue', 0)

    indexed = {
        'cities': cities,
        'city_attach': raw['city_attach'],
        'city_with_prestige': raw['city_with_prestige'],
        'city_fatigues': raw['city_fatigues'],
        'products': products,
        'resonance_skills': raw['resonance_skills'],
        'city_by_id': {str(idx): city for idx, city in enumerate(cities, 1)},
        'product_by_id': {str(idx): product['name'] for idx, product in enumerate(products, 1)},
        'products_by_city': _index_products_by_city(products, cities),
        'fatigue_map': fatigue_map,
    }
    _DATA_CACHE[target] = indexed
    return indexed


def _decode_product_sides(sides, city_by_id):
    """Decode compact 'b'/'s' city maps for a single product."""
    entry = {}
    for short_key, side_key in (('b', 'buy'), ('s', 'sell')):
        if short_key not in sides:
            continue
        entry[side_key] = {
            city_by_id.get(str(cid), str(cid)): {
                'price': info['p'],
                'variation': info['v'],
                'trend': 'up' if info['t'] == 1 else 'down',
                'time': info['ti'],
            }
            for cid, info in sides[short_key].items()
        }
    return entry


def decode_prices(raw_data, data=None):
    """Decode compact /api/get-prices payload into {product: {buy/sell: {city: info}}}."""
    if data is None:
        data = load_columba_data()
    city_by_id = data['city_by_id']
    product_by_id = data['product_by_id']
    return {
        product_by_id.get(str(pid), str(pid)): _decode_product_sides(sides, city_by_id)
        for pid, sides in raw_data.items()
    }


def fetch_prices(ttl=180, force=False, data=None, timeout=15):
    """Fetch live prices from /api/get-prices with an in-memory TTL cache."""
    now = time.time()
    if not force and _PRICE_CACHE['prices'] is not None and (now - _PRICE_CACHE['ts']) < ttl:
        return _PRICE_CACHE['prices']

    payload = http_request('GET', COLUMBA_BASE_URL + '/api/get-prices', timeout=timeout)
    if not isinstance(payload, dict) or not payload.get('data'):
        raise ValueError('Columba /api/get-prices returned empty data')

    prices = decode_prices(payload['data'], data=data)
    _PRICE_CACHE['ts'] = now
    _PRICE_CACHE['prices'] = prices
    return prices


def normalize_player_config(raw=None, data=None):
    """Deep-merge raw config onto defaults and normalize crew resonance levels."""
    if data is None:
        data = load_columba_data()
    cfg = copy.deepcopy(DEFAULT_PLAYER_CONFIG)
    merge_keys = (
        'bargain', 'returnBargain', 'prestige', 'roles', 'onegraph',
        'productUnlockStatus', 'events', 'productsBuyMorePercent',
    )
    if raw:
        for key, value in raw.items():
            if key in merge_keys and isinstance(value, dict):
                cfg[key] = {**cfg.get(key, {}), **value}
            elif value is not None:
                cfg[key] = copy.deepcopy(value)

    skills = data['resonance_skills']
    normalized_roles = {}
    for role, role_cfg in cfg['roles'].items():
        if not isinstance(role_cfg, dict):
            continue
        item = dict(role_cfg)
        level = item.get('resonance', 0)
        if level and role in skills:
            available = sorted(int(k) for k in skills[role])
            if level not in available:
                lower = [k for k in available if k <= level]
                if lower:
                    item['resonance'] = lower[-1]
        normalized_roles[role] = item
    cfg['roles'] = normalized_roles
    return cfg


def fetch_player_config(sync_id, data=None, timeout=15):
    """Fetch and normalize saved player config by sync ID."""
    payload = http_request(
        'POST',
        COLUMBA_BASE_URL + '/api/sync-player-config',
        json_body={'action': 'get', 'id': sync_id},
        timeout=timeout,
    )
    if not isinstance(payload, dict) or not payload.get('data'):
        raise ValueError('Columba sync config not found for id=%r' % (sync_id,))
    return normalize_player_config(payload['data'], data=data)
