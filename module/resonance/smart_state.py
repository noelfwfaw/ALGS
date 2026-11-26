"""Adaptive telemetry state and book-weight calibration for Resonance smart-cycle trading."""

import json
import os
import time

SMART_STATE_PATH = os.path.join('config', 'state', 'resonance_smart_state.json')
DEFAULT_BOOK_WEIGHT = 33.0
DEFAULT_MAX_BOOKS_PER_LEG = 5
ZERO_BOOK_COOLDOWN_SECONDS = 1200
DEFAULT_NEG_FATIGUE = {
    'buy': {'0': 0.0, '10': 10.0, '20': 22.0},
    'sell': {'0': 0.0, '10': 10.0, '20': 22.0},
}


def _read_json_dict(path):
    """Load JSON dictionary tolerantly; return empty dict on missing or corrupt files."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json_dict(payload, path):
    """Atomically write dictionary JSON to disk."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def normalize_neg_fatigue(raw_neg):
    """Merge stored negotiation fatigue averages with sensible defaults."""
    out = {side: dict(DEFAULT_NEG_FATIGUE[side]) for side in ('buy', 'sell')}
    if isinstance(raw_neg, dict):
        for side in ('buy', 'sell'):
            side_raw = raw_neg.get(side)
            if isinstance(side_raw, dict):
                for key in ('10', '20'):
                    val = side_raw.get(key)
                    if isinstance(val, (int, float)) and 6.0 <= float(val) <= 45.0:
                        out[side][key] = float(val)
    return out


def load_smart_state(config_name, path=SMART_STATE_PATH):
    """Load per-instance adaptive state (book stock, negotiation EMA, zero-book cooldowns)."""
    key = str(config_name or 'default')
    inst = _read_json_dict(path).get(key)
    if not isinstance(inst, dict):
        inst = {}
    owned = inst.get('owned_books')
    owned_books = max(0, int(owned)) if isinstance(owned, (int, float)) and owned >= 0 else None
    buys = inst.get('zero_book_buys')
    clean_buys = (
        {str(k): float(v) for k, v in buys.items() if isinstance(v, (int, float))}
        if isinstance(buys, dict) else {}
    )
    return {
        'owned_books': owned_books,
        'neg_fatigue': normalize_neg_fatigue(inst.get('neg_fatigue')),
        'zero_book_buys': clean_buys,
    }


def _save_smart_state(config_name, inst_state, path=SMART_STATE_PATH):
    """Persist per-instance smart state atomically under `config_name`."""
    key = str(config_name or 'default')
    store = _read_json_dict(path)
    store[key] = inst_state
    _write_json_dict(store, path)


def update_smart_books(config_name, owned_books, path=SMART_STATE_PATH):
    """Persist remaining restock book inventory observed in-game."""
    state = load_smart_state(config_name, path=path)
    state['owned_books'] = max(0, int(owned_books))
    _save_smart_state(config_name, state, path=path)
    return state['owned_books']


def record_zero_book_buy(config_name, city, path=SMART_STATE_PATH, now_ts=None):
    """Record a 0-book purchase in `city` and prune expired cooldown timestamps."""
    ts = float(now_ts if now_ts is not None else time.time())
    state = load_smart_state(config_name, path=path)
    cutoff = ts - ZERO_BOOK_COOLDOWN_SECONDS
    buys = {c: t for c, t in state['zero_book_buys'].items() if t >= cutoff}
    if city:
        buys[str(city)] = ts
    state['zero_book_buys'] = buys
    _save_smart_state(config_name, state, path=path)


def record_negotiation_fatigue(config_name, is_buy, target_pct, fatigue_spent, path=SMART_STATE_PATH):
    """Update EMA of real fatigue spent for bargain/raise target percentage."""
    if not target_pct or target_pct <= 0 or not fatigue_spent or fatigue_spent <= 0:
        return
    side = 'buy' if is_buy else 'sell'
    level_key = '10' if float(target_pct) <= 15.0 else '20'
    sample = max(6.0, min(45.0, float(fatigue_spent)))
    state = load_smart_state(config_name, path=path)
    prev = state['neg_fatigue'][side].get(level_key, DEFAULT_NEG_FATIGUE[side][level_key])
    state['neg_fatigue'][side][level_key] = round(0.75 * prev + 0.25 * sample, 2)
    _save_smart_state(config_name, state, path=path)


def record_smart_buy_telemetry(config_name, city, restock, bargain_pct, restock_owned, neg_fatigue_spent, path=SMART_STATE_PATH):
    """Persist book stock, zero-book cooldown, and buy-negotiation EMA after purchasing a leg."""
    if restock_owned is not None:
        update_smart_books(config_name, restock_owned, path=path)
    if restock == 0:
        record_zero_book_buy(config_name, city, path=path)
    if bargain_pct > 0 and neg_fatigue_spent:
        record_negotiation_fatigue(config_name, True, bargain_pct, neg_fatigue_spent, path=path)


def get_active_cooldowns(smart_state, now_ts=None):
    """Return {city: discount_factor} for recent 0-book shelf purchases within cooldown window."""
    if not isinstance(smart_state, dict):
        return {}
    ts = float(now_ts if now_ts is not None else time.time())
    buys = smart_state.get('zero_book_buys') or {}
    out = {}
    for city, buy_ts in buys.items():
        elapsed = ts - float(buy_ts)
        if 0.0 <= elapsed < ZERO_BOOK_COOLDOWN_SECONDS:
            out[city] = 0.35 + 0.65 * (elapsed / ZERO_BOOK_COOLDOWN_SECONDS)
    return out


def compute_book_weight(owned_books=None):
    """Map restock-book stock to `(book_fatigue_weight, max_books_per_leg)`."""
    if owned_books is None:
        return DEFAULT_BOOK_WEIGHT, DEFAULT_MAX_BOOKS_PER_LEG
    n = int(owned_books)
    if n <= 0:
        return 120.0, 0
    if n < 20:
        return 90.0, 1
    if n < 60:
        weight = 70.0 - 28.0 * (n - 20) / 40.0
        return round(weight, 2), min(3, n)
    if n <= 200:
        weight = 42.0 - 12.0 * (n - 60) / 140.0
        return round(weight, 2), DEFAULT_MAX_BOOKS_PER_LEG
    extra = min(300, n - 200)
    weight = 30.0 - 8.0 * extra / 300.0
    return round(weight, 2), DEFAULT_MAX_BOOKS_PER_LEG


def neg_fatigue_cost(bargain_pct, raise_pct, neg_fatigue=None):
    """Estimate expected extra fatigue for a `(bargain_pct, raise_pct)` pair."""
    nf = normalize_neg_fatigue(neg_fatigue)
    b_key = '0' if bargain_pct <= 0 else ('10' if bargain_pct <= 15 else '20')
    s_key = '0' if raise_pct <= 0 else ('10' if raise_pct <= 15 else '20')
    return nf['buy'][b_key] + nf['sell'][s_key]
