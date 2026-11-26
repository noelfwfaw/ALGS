"""Config-adaptive market quality evaluation and WebUI status reporting for 雷索纳斯 trading."""

import copy
from datetime import datetime
import json
import os
import re

from module.resonance.columba import fetch_prices, load_columba_data, normalize_player_config
from module.resonance.route import SORT_ALIASES, js_round, recommend_routes
from module.resonance.smart_cycle import (
    build_edge_options, compute_book_weight, format_cycle_short, format_cycle_summary,
    load_smart_state, solve_optimal_cycle,
)

MARKET_FILTER_THRESHOLDS = {
    'all': None,
    'normal': 15.0,
    'good': 25.0,
    'great': 40.0,
}
MARKET_FILTER_LABELS = {
    'all': '不限行情',
    'normal': '常态以上 ≥ 15',
    'good': '较好行情 ≥ 25',
    'great': '大行情 ≥ 40',
}
SORT_METRIC_LABELS = {
    'profit': '总利润',
    'profit_per_fatigue': '单位疲劳利润',
    'general_profit_index': '综合参考利润',
    'smart_cycle': '智能环路综合评分',
}

MARKET_BASE_BUY_V = 100
MARKET_BASE_SELL_V = 100
MARKET_GOOD_BUY_V = 80
MARKET_GOOD_SELL_V = 120
# Multi-city cycles average independent city swings across 2-3 legs (~1/sqrt(3) of ±20%),
# so 89/111 aligns smart_cycle's 15/25/40 thresholds with single-leg auto mode.
SMART_CYCLE_GOOD_BUY_V = 89
SMART_CYCLE_GOOD_SELL_V = 111
MARKET_OVERFLOW_FATIGUE = 60

MARKET_STATUS_PATH = os.path.join('config', 'state', 'resonance_market_status.json')
PROFILE_CACHE_PATH = os.path.join('config', 'state', 'resonance_profile.json')

# Keep identical to MAP_COORDS_05X keys in map_nav.py without importing cv2/assets into WebUI.
MAPPED_CITIES = frozenset((
    '修格里城', '澄明数据中心', '七号自由港', '曼德矿场', '阿妮塔发射中心',
    '云岫桥基地', '铁盟哨站', '阿妮塔战备工厂', '黑月游乐城', '淘金乐园',
    '阿妮塔能源研究所', '荒原站', '栖羽站', '岚心城', '远星大桥',
    '贡露城', '维蒂林场', '塔图站', '海角城', '汇流塔',
))
CITY_ALIASES = {'7号自由港': '七号自由港'}


def _canonical_city(name):
    text = str(name or '').strip()
    return CITY_ALIASES.get(text, text)


def _scale_side(base_map, live_side, variation_pct):
    """Build synthetic side prices at `variation_pct`, falling back to normalized live prices."""
    trend = 'up' if variation_pct >= 100 else 'down'
    scaled = {
        city: {
            'price': js_round(base_p * variation_pct / 100.0),
            'variation': variation_pct,
            'trend': trend,
            'time': 0,
        }
        for city, base_p in (base_map or {}).items()
        if base_p and base_p > 0
    }
    for city, info in (live_side or {}).items():
        if city in scaled:
            continue
        live_p = info.get('price', 0)
        if not live_p:
            continue
        live_v = info.get('variation', 0)
        base_p = (live_p / (live_v / 100.0)) if live_v and live_v > 0 else live_p
        scaled[city] = {
            'price': js_round(base_p * variation_pct / 100.0),
            'variation': variation_pct,
            'trend': trend,
            'time': 0,
        }
    return scaled


def build_scaled_prices(data, live_prices, buy_v, sell_v):
    """Build synthetic market snapshot scaling all goods by `(buy_v%, sell_v%)`."""
    scaled = {}
    for product in data['products']:
        name = product['name']
        live_entry = live_prices.get(name, {})
        entry = {}
        buy_side = _scale_side(product.get('buyPrices'), live_entry.get('buy'), buy_v)
        if buy_side:
            entry['buy'] = buy_side
        sell_side = _scale_side(product.get('sellPrices'), live_entry.get('sell'), sell_v)
        if sell_side:
            entry['sell'] = sell_side
        if entry:
            scaled[name] = entry
    return scaled


def _format_route_label(route):
    if not route:
        return ''
    arrow = '<->' if route.get('go_and_return') else '->'
    return '%s %s %s' % (route['from_city'], arrow, route['to_city'])


def _corridor_best_route(price_table, player_config, sort_key, data, manual_cities=None):
    """Return (score, route_label) for auto global search or manual A<->B corridor."""
    if manual_cities:
        city_a = _canonical_city(manual_cities[0])
        city_b = _canonical_city(manual_cities[1])
        if city_a and city_b and city_a != city_b and city_a in MAPPED_CITIES and city_b in MAPPED_CITIES:
            manual_cfg = copy.deepcopy(player_config)
            manual_cfg['excludedCities'] = [
                c for c in manual_cfg.get('excludedCities', ()) if c not in (city_a, city_b)
            ]
            ab = recommend_routes(
                price_table, player_config=manual_cfg, data=data, sort_by=sort_key,
                go_and_return=False, from_city=city_a, to_city=city_b, limit=1,
            )
            cfg_ba = copy.deepcopy(manual_cfg)
            cfg_ba['bargain'] = dict(cfg_ba['returnBargain'])
            ba = recommend_routes(
                price_table, player_config=cfg_ba, data=data, sort_by=sort_key,
                go_and_return=False, from_city=city_b, to_city=city_a, limit=1,
            )
            best = max(ab + ba, key=lambda r: r[sort_key], default=None)
            return (best[sort_key], _format_route_label(best)) if best else (0, '')

    routes = recommend_routes(
        price_table, player_config=player_config, data=data, sort_by=sort_key, limit=1,
    )
    best = routes[0] if routes else None
    return (best[sort_key], _format_route_label(best)) if best else (0, '')


def _smart_cycle_best_score(price_table, player_config, data, book_weight, max_books, neg_fatigue):
    """Solve smart cycle score without cooldown distortion for market index evaluation."""
    cities, edges = build_edge_options(
        price_table, player_config, data, max_books=max_books, neg_fatigue=neg_fatigue, cooled_cities={},
    )
    cycle = solve_optimal_cycle(edges, cities, book_weight=book_weight)
    return (cycle['score'], cycle) if cycle else (0, None)


def evaluate_market_quality(
    prices, player_config, sort_by, data, manual_cities=None, route_mode='auto', smart_state=None,
):
    """Evaluate config-normalized market index in 0..100+ (0=100% parity, 100=80/120 for auto/manual or 89/111 for smart_cycle)."""
    base_prices = build_scaled_prices(data, prices, MARKET_BASE_BUY_V, MARKET_BASE_SELL_V)

    if route_mode == 'smart_cycle':
        state = smart_state if isinstance(smart_state, dict) else {}
        owned = state.get('owned_books')
        neg_fatigue = state.get('neg_fatigue')
        book_weight, max_books = compute_book_weight(owned)
        good_prices = build_scaled_prices(data, prices, SMART_CYCLE_GOOD_BUY_V, SMART_CYCLE_GOOD_SELL_V)
        live_score, live_cycle = _smart_cycle_best_score(prices, player_config, data, book_weight, max_books, neg_fatigue)
        base_score, _ = _smart_cycle_best_score(base_prices, player_config, data, book_weight, max_books, neg_fatigue)
        good_score, _ = _smart_cycle_best_score(good_prices, player_config, data, book_weight, max_books, neg_fatigue)
        if good_score <= base_score:
            return None
        return {
            'index': round((live_score - base_score) / float(good_score - base_score) * 100.0, 1),
            'live': live_score,
            'base': base_score,
            'good': good_score,
            'sort_by': 'smart_cycle',
            'route': format_cycle_short(live_cycle),
            'cycle_detail': format_cycle_summary(live_cycle),
            'book_weight': round(book_weight, 1),
            'owned_books': owned,
        }

    good_prices = build_scaled_prices(data, prices, MARKET_GOOD_BUY_V, MARKET_GOOD_SELL_V)
    sort_key = SORT_ALIASES.get(sort_by, 'general_profit_index')
    live_score, live_route = _corridor_best_route(
        prices, player_config, sort_key, data, manual_cities=manual_cities,
    )
    base_score, _ = _corridor_best_route(base_prices, player_config, sort_key, data, manual_cities=manual_cities)
    good_score, _ = _corridor_best_route(good_prices, player_config, sort_key, data, manual_cities=manual_cities)
    if good_score <= base_score:
        return None
    index = round((live_score - base_score) / float(good_score - base_score) * 100.0, 1)
    return {
        'index': index,
        'live': live_score,
        'base': base_score,
        'good': good_score,
        'sort_by': sort_key,
        'route': live_route,
    }


def _read_json_dict(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def load_market_status(config_name, path=MARKET_STATUS_PATH):
    """Load latest persisted market check record for `config_name`, or return None."""
    key = str(config_name or 'default')
    record = _read_json_dict(path).get(key)
    return record if isinstance(record, dict) else None


def save_market_status(config_name, record, path=MARKET_STATUS_PATH):
    """Atomically persist latest market check record under `config_name`."""
    key = str(config_name or 'default')
    payload = _read_json_dict(path)
    payload[key] = dict(record)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def build_market_status_record(mq, status, market_filter, fatigue=None, next_check='', source='task'):
    """Build normalized WebUI-friendly market status snapshot dictionary."""
    return {
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'status': status,
        'market_filter': market_filter,
        'threshold': MARKET_FILTER_THRESHOLDS.get(market_filter),
        'index': mq['index'],
        'live': mq['live'],
        'base': mq['base'],
        'good': mq['good'],
        'sort_by': mq['sort_by'],
        'route': mq.get('route', ''),
        'cycle_detail': mq.get('cycle_detail', ''),
        'book_weight': mq.get('book_weight'),
        'owned_books': mq.get('owned_books'),
        'fatigue': fatigue,
        'next_check': next_check or '',
        'source': source,
    }


def _build_webui_player_config(profile, trade_cfg, data):
    """Build normalized player_config from saved ResonanceTrade settings without cv2/assets."""
    raw_excluded = re.split(r'[,，、\s]+', str(trade_cfg.get('ExcludedCities', '武林源') or ''))
    excluded = {_canonical_city(name) for name in raw_excluded if _canonical_city(name)}
    for city in data['cities']:
        if city not in MAPPED_CITIES:
            excluded.add(city)

    bargain_pct = int(trade_cfg.get('BargainPercent', 20) or 0)
    raise_pct = int(trade_cfg.get('RaisePercent', 20) or 0)
    return_bargain = bool(trade_cfg.get('ReturnBargain', False))
    bargain_cfg = {
        'bargainPercent': bargain_pct,
        'raisePercent': raise_pct,
        'bargainFatigue': 0,
        'raiseFatigue': 0,
        'disabled': bargain_pct == 0 and raise_pct == 0,
    }
    ret_cfg = (
        dict(bargain_cfg)
        if return_bargain
        else {'bargainPercent': 0, 'raisePercent': 0, 'bargainFatigue': 0, 'raiseFatigue': 0, 'disabled': True}
    )
    raw = {
        'maxLot': int((profile or {}).get('maxLot', 500) or 500),
        'prestige': dict((profile or {}).get('prestige', {})),
        'roles': dict((profile or {}).get('roles', {})),
        'onegraph': {
            'maxRestock': int(trade_cfg.get('RestockBooks', 2) or 0),
            'goAndReturn': bool(trade_cfg.get('RoundTrip', False)),
        },
        'bargain': dict(bargain_cfg),
        'returnBargain': ret_cfg,
        'excludedCities': sorted(excluded),
    }
    return normalize_player_config(raw, data=data)


def refresh_market_status_for_webui(
    config_name, trade_cfg, profile=None, prices=None, data=None,
    status_path=MARKET_STATUS_PATH, profile_path=PROFILE_CACHE_PATH,
):
    """Evaluate live market quality on demand from WebUI and persist status record."""
    if data is None:
        data = load_columba_data()
    if profile is None:
        profile = _read_json_dict(profile_path)
    cfg = trade_cfg or {}
    player_cfg = _build_webui_player_config(profile, cfg, data)
    sort_by = cfg.get('SortBy', 'profit_per_fatigue')
    market_filter = cfg.get('MarketFilter', 'all')
    route_mode = cfg.get('RouteMode', 'auto')
    manual_cities = None
    if route_mode == 'manual':
        manual_cities = (cfg.get('ManualCityA', ''), cfg.get('ManualCityB', ''))
    smart_state = load_smart_state(config_name) if route_mode == 'smart_cycle' else None

    live_prices = prices if prices is not None else fetch_prices(ttl=30, force=True, data=data)
    mq = evaluate_market_quality(
        live_prices, player_cfg, sort_by, data,
        manual_cities=manual_cities, route_mode=route_mode, smart_state=smart_state,
    )
    if mq is None:
        return None
    threshold = MARKET_FILTER_THRESHOLDS.get(market_filter)
    if threshold is None:
        status = 'open'
    elif mq['index'] >= threshold:
        status = 'pass'
    else:
        status = 'wait'
    record = build_market_status_record(mq, status, market_filter, source='manual')
    save_market_status(config_name, record, path=status_path)
    return record


def format_market_summary(record):
    """Format market status record into concise Chinese badge, overview line, and details."""
    status = record.get('status', 'open')
    index = float(record.get('index', 0.0))
    threshold = record.get('threshold')
    market_filter = record.get('market_filter', 'all')
    metric = SORT_METRIC_LABELS.get(record.get('sort_by'), '参考指标')
    route = record.get('route') or '暂无'
    filter_label = MARKET_FILTER_LABELS.get(market_filter, market_filter)
    thresh_num = int(threshold) if threshold is not None else 0

    if status == 'pass':
        badge = '行情达标，正常跑商'
        color = '#28a745'
        overview = '行情达标｜指数 %.1f ≥ %d（%s）' % (index, thresh_num, route)
    elif status == 'wait':
        badge = '行情不足，等待复查'
        color = '#e67e22'
        overview = '等待好行情｜指数 %.1f < %d（%s）' % (index, thresh_num, route)
    elif status == 'overflow':
        badge = '防疲劳溢出放行'
        color = '#17a2b8'
        overview = '防溢出放行｜指数 %.1f < %d（%s）' % (index, thresh_num, route)
    else:
        badge = '不限行情（实时监测）'
        color = '#6c757d'
        overview = '行情指数 %.1f（不限，%s）' % (index, route)

    lines = [
        '行情指数：%.1f（当前门槛：%s）' % (index, filter_label),
        '%s：实时 %s ｜ 平价基准 %s ｜ 常规上限 %s' % (
            metric,
            f"{int(record.get('live', 0)):,}",
            f"{int(record.get('base', 0)):,}",
            f"{int(record.get('good', 0)):,}",
        ),
        '当前最优路线：%s' % route,
    ]
    if record.get('cycle_detail'):
        lines.append('智能环路方案：%s' % record['cycle_detail'])
    if record.get('book_weight') is not None:
        stock_txt = '%d 本' % int(record['owned_books']) if record.get('owned_books') is not None else '待扫描'
        lines.append('进货书库存：%s ｜ 书本权重：%.1f 疲劳/本' % (stock_txt, float(record['book_weight'])))
    meta = '最近检测：%s' % record.get('updated_at', '')
    if record.get('fatigue') is not None:
        meta += ' ｜ 当前疲劳：%d' % int(record['fatigue'])
    if status == 'wait' and record.get('next_check'):
        meta += ' ｜ 下次复查：%s' % record['next_check']
    lines.append(meta)
    return {
        'badge': badge,
        'color': color,
        'overview_line': overview,
        'detail_lines': lines,
    }
