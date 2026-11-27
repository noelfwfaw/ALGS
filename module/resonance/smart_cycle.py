"""Smart adaptive multi-city cycle trade optimizer for 雷索纳斯 (Resonance Solstice)."""

from itertools import product
import math

from module.resonance.columba import PRESTIGE_TABLE, load_columba_data, normalize_player_config
from module.resonance.route import (
    _calc_fatigue, _event_modifier, _pack_leg, _role_buy_more, _role_tax_cut, js_round,
)
from module.resonance.smart_state import (
    DEFAULT_BOOK_WEIGHT, DEFAULT_MAX_BOOKS_PER_LEG, DEFAULT_NEG_FATIGUE, DRIVE_FATIGUE_BUFFER, SMART_STATE_PATH,
    ZERO_BOOK_COOLDOWN_SECONDS, compute_book_weight, get_active_cooldowns, leg_atomic_fatigue_budget, load_smart_state,
    neg_fatigue_cost, normalize_neg_fatigue, record_negotiation_fatigue, record_zero_book_buy, safe_negotiation_budget,
    update_smart_books,
)

HOP_FATIGUE_PENALTY = 5.0
DEFAULT_MAX_CYCLE_LEN = 4
NEG_LEVELS = (0, 10, 20)


def _empty_leg(drive_fatigue):
    """Construct an empty transit leg when repositioning without cargo."""
    return {
        'combinations': [],
        'buy_order': [],
        'profit': 0,
        'restock': 0,
        'fatigue': drive_fatigue,
        'profit_per_fatigue': 0,
        'general_profit_index': 0,
        'used_lot': 0,
    }


def _static_pair_products(from_city, to_city, prices, cfg, data):
    """Precompute negotiation-invariant product parameters for one directed city pair."""
    attach = data['city_attach']
    skills = data['resonance_skills']
    roles = cfg['roles']
    prestige = cfg['prestige']
    events = cfg['events']
    unlock = cfg['productUnlockStatus']
    all_more = cfg.get('allExchangesBuyMorePercent', 0)
    prod_more = cfg.get('productsBuyMorePercent', {})

    from_attach = attach.get(from_city, from_city)
    to_attach = attach.get(to_city, to_city)
    from_p = PRESTIGE_TABLE.get(prestige.get(from_attach, 1))
    to_p = PRESTIGE_TABLE.get(prestige.get(to_attach, 1))
    if not from_p or not to_p:
        return []

    tax_cut = _role_tax_cut(roles, from_city, skills)
    from_base_tax = from_p['specialTax'].get(from_attach, from_p['generalTax'])
    sell_tax_rate = to_p['specialTax'].get(to_attach, to_p['generalTax']) + tax_cut

    items = []
    for product in data['products_by_city'].get(from_city, ()):
        name = product['name']
        if product.get('type') == 'Craft' or not unlock.get(name, True):
            continue
        raw_buy = prices.get(name, {}).get('buy', {}).get(from_city, {}).get('price', 0)
        raw_sell = prices.get(name, {}).get('sell', {}).get(to_city, {}).get('price', 0)
        base_lot = product.get('buyLot', {}).get(from_city, 0)
        if not raw_buy or not raw_sell or not base_lot:
            continue

        buy_tax_term = from_base_tax + _event_modifier(product, from_city, events, 'taxVariation', 0.0) + 2.0 * tax_cut
        lot_pct = (_role_buy_more(roles, product, from_city, skills) + 100.0 * from_p['extraBuy']
                   + _event_modifier(product, from_city, events, 'buyMore', 0) + all_more + prod_more.get(name, 0))
        items.append((
            name,
            raw_buy,
            raw_sell,
            js_round(base_lot * (100.0 + lot_pct) / 100.0),
            product['buyPrices'][from_city],
            buy_tax_term,
            sell_tax_rate,
        ))
    return items


def _eval_pair_neg_mode(u, v, drive_f, pair_items, max_lot, max_books, bp, rp, neg_fatigue, cooldown_factor):
    """Build restock-level options for `(u, v)` under a fixed `(bp, rp)` negotiation pair."""
    cands = []
    for name, raw_buy, raw_sell, buy_lot, base_price, buy_tax_term, sell_tax_rate in pair_items:
        buy_price = raw_buy * (1.0 - bp / 100.0)
        sell_price = int(math.floor(raw_sell * (1.0 + rp / 100.0) + 0.5))
        single = sell_price - buy_price
        single -= single * sell_tax_rate
        single -= buy_price * buy_tax_term
        single = js_round(single)
        if single > 0:
            cands.append({'name': name, 'single_profit': single, 'buy_lot': buy_lot, 'base_price': base_price})
    if not cands:
        return []
    cands.sort(key=lambda item: item['single_profit'], reverse=True)
    nf = neg_fatigue_cost(bp, rp, neg_fatigue)
    bcfg = {'bargainFatigue': 0, 'raiseFatigue': 0, 'disabled': (bp == 0 and rp == 0)}
    opts = []
    prev = None
    for r in range(0, max_books + 1):
        leg = _pack_leg(cands, max_lot, drive_f, bcfg, r, prev)
        if prev is not None and leg['profit'] == prev['profit']:
            break
        prev = leg
        profit = leg['profit']
        if profit <= 0:
            continue
        eff_profit = js_round(profit * cooldown_factor) if (r == 0 and cooldown_factor < 1.0) else profit
        opts.append({
            'from_city': u, 'to_city': v, 'leg': leg,
            'profit': profit, 'eff_profit': eff_profit,
            'drive_fatigue': drive_f, 'neg_fatigue': nf,
            'restock': r, 'bargain_pct': bp, 'raise_pct': rp,
        })
    return opts


def _build_edge_options_for_pair(u, v, drive_f, pair_items, max_lot, max_books, neg_fatigue, cooldown_factor):
    """Enumerate `(restock, bargain_pct, raise_pct)` strategies for directed pair `(u, v)`."""
    opts = []
    for bp, rp in product(NEG_LEVELS, NEG_LEVELS):
        opts.extend(_eval_pair_neg_mode(u, v, drive_f, pair_items, max_lot, max_books, bp, rp, neg_fatigue, cooldown_factor))
    opts.append({
        'from_city': u, 'to_city': v, 'leg': _empty_leg(drive_f),
        'profit': 0, 'eff_profit': 0,
        'drive_fatigue': drive_f, 'neg_fatigue': 0.0,
        'restock': 0, 'bargain_pct': 0, 'raise_pct': 0,
    })
    return opts


def build_edge_options(prices, player_config, data, cities=None, max_books=DEFAULT_MAX_BOOKS_PER_LEG,
                       neg_fatigue=None, cooled_cities=None):
    """Precompute non-empty and empty trading options across all active directed city pairs."""
    if data is None:
        data = load_columba_data()
    if not prices:
        return [], {}
    cfg = normalize_player_config(player_config, data=data)
    excluded = set(cfg.get('excludedCities', ()))
    active_cities = list(cities) if cities is not None else [c for c in data['cities'] if c not in excluded]
    roles = cfg.get('roles', {})
    max_lot = int(cfg.get('maxLot', 500) or 500)
    nf_map = normalize_neg_fatigue(neg_fatigue)
    cooled = cooled_cities or {}

    edges = {}
    for u, v in product(active_cities, active_cities):
        if u == v:
            continue
        df = _calc_fatigue(u, v, roles, data)
        if df <= 0:
            continue
        pair_items = _static_pair_products(u, v, prices, cfg, data)
        edges[(u, v)] = _build_edge_options_for_pair(
            u, v, df, pair_items, max_lot, max_books, nf_map, float(cooled.get(u, 1.0)),
        )
    return active_cities, edges


def _prune_single_edge(opts, book_weight, hop_penalty):
    """Attach parametric cost to options of one edge and keep strictly Pareto-dominant options."""
    scored = []
    for o in opts:
        copy_o = dict(o)
        copy_o['cost'] = float(o['drive_fatigue'] + o['neg_fatigue'] + hop_penalty + book_weight * o['restock'])
        scored.append(copy_o)
    scored.sort(key=lambda x: (x['cost'], -x['eff_profit']))
    frontier = []
    best_p = -1
    for o in scored:
        if o['eff_profit'] > best_p:
            frontier.append(o)
            best_p = o['eff_profit']
    return tuple(frontier)


def _prune_edge_frontier(edges, cities, book_weight, hop_penalty):
    """Build Pareto-pruned option matrix across all directed city pairs."""
    n = len(cities)
    pruned = [[() for _ in range(n)] for _ in range(n)]
    for i, j in product(range(n), range(n)):
        if i == j:
            continue
        opts = edges.get((cities[i], cities[j]))
        if opts:
            pruned[i][j] = _prune_single_edge(opts, book_weight, hop_penalty)
    return pruned


def _best_2_3_cycle_from_root(best_w, n, s, max_k):
    """Return `(best_weight, best_indices, top2_to_b)` for 2- and 3-city simple cycles rooted at `s`."""
    w_row_s = best_w[s]
    top_weight, top_indices = -1e18, None
    top2_to_b = [[] for _ in range(n)]

    for a in range(s + 1, n):
        w_sa = w_row_s[a]
        if w_sa is not None and best_w[a][s] is not None:
            w = w_sa + best_w[a][s]
            if w > top_weight:
                top_weight, top_indices = w, (s, a, s)

    if max_k < 3:
        return top_weight, top_indices, top2_to_b

    for b in range(s + 1, n):
        cands = [
            (w_row_s[a] + best_w[a][b], a)
            for a in range(s + 1, n)
            if a != b and w_row_s[a] is not None and best_w[a][b] is not None
        ]
        if not cands:
            continue
        cands.sort(reverse=True)
        top2_to_b[b] = cands[:2]
        if best_w[b][s] is not None:
            w = cands[0][0] + best_w[b][s]
            if w > top_weight:
                top_weight, top_indices = w, (s, cands[0][1], b, s)
    return top_weight, top_indices, top2_to_b


def _best_cycle_from_root(best_w, n, s, max_k):
    """Return `(best_weight, best_indices)` among 2..4-city simple cycles whose min vertex is `s`."""
    top_weight, top_indices, top2_to_b = _best_2_3_cycle_from_root(best_w, n, s, max_k)
    if max_k < 4:
        return top_weight, top_indices
    for b, c in product(range(s + 1, n), range(s + 1, n)):
        if b == c or not top2_to_b[b] or best_w[b][c] is None or best_w[c][s] is None:
            continue
        w_bc_cs = best_w[b][c] + best_w[c][s]
        for w_sab, a in top2_to_b[b]:
            if a != c:
                w = w_sab + w_bc_cs
                if w > top_weight:
                    top_weight, top_indices = w, (s, a, b, c, s)
                break
    return top_weight, top_indices


def _best_simple_cycle_fixed_lambda(pruned, n, lam, max_len):
    """Find max-weight simple cycle of length `2..min(4, max_len)` at fixed ratio `lam`."""
    best_w = [[None] * n for _ in range(n)]
    best_o = [[None] * n for _ in range(n)]
    for i, j in product(range(n), range(n)):
        if i == j or not pruned[i][j]:
            continue
        opt = max(pruned[i][j], key=lambda o: o['eff_profit'] - lam * o['cost'])
        best_o[i][j] = opt
        best_w[i][j] = opt['eff_profit'] - lam * opt['cost']

    top_weight, top_indices = -1e18, None
    max_k = min(4, max(2, int(max_len)))
    for s in range(n):
        w, idx = _best_cycle_from_root(best_w, n, s, max_k)
        if w > top_weight:
            top_weight, top_indices = w, idx

    if top_indices is None:
        return None, -1e18
    legs = [best_o[top_indices[k]][top_indices[k + 1]] for k in range(len(top_indices) - 1)]
    return legs, top_weight
    return legs, top_weight


def solve_optimal_cycle(edges, cities, book_weight=DEFAULT_BOOK_WEIGHT,
                        max_len=DEFAULT_MAX_CYCLE_LEN, hop_penalty=HOP_FATIGUE_PENALTY):
    """Solve exact maximum `(eff_profit / parametric_cost)` simple cycle across active cities."""
    if len(cities) < 2:
        return None
    pruned = _prune_edge_frontier(edges, cities, book_weight, hop_penalty)
    n = len(cities)
    lam = 0.0
    best_legs = None

    for _ in range(25):
        legs, weight = _best_simple_cycle_fixed_lambda(pruned, n, lam, max_len)
        if not legs:
            break
        tot_eff = sum(o['eff_profit'] for o in legs)
        tot_cost = sum(o['cost'] for o in legs)
        if tot_eff <= 0 or tot_cost <= 0:
            break
        new_lam = tot_eff / tot_cost
        best_legs = legs
        if new_lam <= lam + 1e-6 or weight <= 1e-6:
            lam = new_lam
            break
        lam = new_lam

    if not best_legs:
        return None
    tot_profit = sum(o['profit'] for o in best_legs)
    tot_eff = sum(o['eff_profit'] for o in best_legs)
    tot_df = sum(o['drive_fatigue'] for o in best_legs)
    tot_nf = sum(o['neg_fatigue'] for o in best_legs)
    tot_f = tot_df + tot_nf
    tot_b = sum(o['restock'] for o in best_legs)
    tot_c = sum(o['cost'] for o in best_legs)
    if tot_profit <= 0 or tot_c <= 0:
        return None
    ring = [o['from_city'] for o in best_legs] + [best_legs[0]['from_city']]
    return {
        'cities': ring,
        'legs': best_legs,
        'total_profit': tot_profit,
        'total_eff_profit': tot_eff,
        'total_drive_fatigue': tot_df,
        'total_neg_fatigue': tot_nf,
        'total_fatigue': tot_f,
        'total_restock': tot_b,
        'total_cost': tot_c,
        'book_weight': float(book_weight),
        'score': js_round(tot_eff / tot_c),
        'profit_per_fatigue': js_round(tot_profit / tot_f) if tot_f > 0 else 0,
    }


def _wrap_leg_plan(chosen, cycle, is_entry, edges, neg_fatigue=None):
    """Wrap one selected edge option into the caravan leg-plan structure."""
    is_repo = (
        is_entry
        and chosen['restock'] == 0
        and chosen['bargain_pct'] == 0
        and chosen['raise_pct'] == 0
    )
    return {
        'from_city': chosen['from_city'],
        'to_city': chosen['to_city'],
        'leg': chosen['leg'],
        'is_reposition': is_repo,
        'is_return': False,
        'is_smart_cycle': True,
        'bargain_target': chosen['bargain_pct'],
        'raise_target': chosen['raise_pct'],
        'expected_neg_fatigue': int(round(chosen['neg_fatigue'])),
        'atomic_fatigue': leg_atomic_fatigue_budget(chosen['drive_fatigue'], chosen['bargain_pct'], chosen['raise_pct'], neg_fatigue),
        'cycle': cycle,
        '_edges': edges,
        'best_route': None,
    }


def plan_smart_cycle_leg(current_city, prices, player_config, data, smart_state=None,
                         max_len=DEFAULT_MAX_CYCLE_LEN, hop_penalty=HOP_FATIGUE_PENALTY, now_ts=None):
    """Compute global optimal cycle and return the next leg to execute from `current_city`."""
    state = smart_state if isinstance(smart_state, dict) else {}
    owned = state.get('owned_books')
    book_weight, max_books = compute_book_weight(owned)
    nf = normalize_neg_fatigue(state.get('neg_fatigue'))
    cooled = get_active_cooldowns(state, now_ts=now_ts)

    cfg = normalize_player_config(player_config, data=data)
    active_cities, edges = build_edge_options(
        prices, cfg, data, max_books=max_books, neg_fatigue=nf, cooled_cities=cooled,
    )
    cycle = solve_optimal_cycle(edges, active_cities, book_weight=book_weight, max_len=max_len, hop_penalty=hop_penalty)
    if cycle is None:
        return None
    cycle['neg_fatigue'] = nf

    for leg_opt in cycle['legs']:
        if leg_opt['from_city'] == current_city:
            return _wrap_leg_plan(leg_opt, cycle, is_entry=False, edges=edges, neg_fatigue=nf)

    ring_cities = cycle['cities'][:-1]
    if current_city not in active_cities:
        # Temporarily evaluate outgoing edges from an excluded starting city so we can enter the cycle cleanly.
        roles = cfg.get('roles', {})
        for v in ring_cities:
            df = _calc_fatigue(current_city, v, roles, data)
            if df <= 0:
                continue
            pair_items = _static_pair_products(current_city, v, prices, cfg, data)
            edges[(current_city, v)] = _build_edge_options_for_pair(
                current_city, v, df, pair_items, int(cfg.get('maxLot', 500) or 500),
                max_books, nf, float(cooled.get(current_city, 1.0)),
            )

    lam = cycle['total_eff_profit'] / cycle['total_cost']
    best_entry = None
    best_val = -1e18
    for v in ring_cities:
        for o in edges.get((current_city, v), ()):
            cost = float(o['drive_fatigue'] + o['neg_fatigue'] + hop_penalty + book_weight * o['restock'])
            val = o['eff_profit'] - lam * cost
            if val > best_val:
                best_val = val
                best_entry = o
    return _wrap_leg_plan(best_entry, cycle, is_entry=True, edges=edges, neg_fatigue=nf) if best_entry else None


def plan_smart_endgame_leg(current_city, edges, cycle, remaining_fatigue,
                           book_weight=DEFAULT_BOOK_WEIGHT, hop_penalty=HOP_FATIGUE_PENALTY):
    """Pick highest-profit leg fitting atomically within `remaining_fatigue` at >= 85% cycle efficiency."""
    if not cycle or not edges or remaining_fatigue <= 0:
        return None
    min_ratio = 0.85 * (cycle['total_eff_profit'] / cycle['total_cost'])
    nf = cycle.get('neg_fatigue')
    best_opt = None
    for (u, _v), opts in edges.items():
        if u != current_city:
            continue
        for o in opts:
            if o['eff_profit'] <= 0:
                continue
            f_safe = leg_atomic_fatigue_budget(o['drive_fatigue'], o['bargain_pct'], o['raise_pct'], nf)
            if f_safe > remaining_fatigue:
                continue
            f_need = o['drive_fatigue'] + o['neg_fatigue']
            cost = float(f_need + hop_penalty + book_weight * o['restock'])
            if cost <= 0 or (o['eff_profit'] / cost) < min_ratio:
                continue
            if best_opt is None or o['eff_profit'] > best_opt['eff_profit']:
                best_opt = o
    return _wrap_leg_plan(best_opt, cycle, is_entry=True, edges=edges, neg_fatigue=nf) if best_opt else None


def format_cycle_short(cycle):
    """Format concise loop label such as `3城环: 阿妮塔发射中心→岚心城→海角城`."""
    if not cycle or not cycle.get('legs'):
        return ''
    ring = cycle['cities'][:-1]
    return '%d城环: %s' % (len(ring), '→'.join(ring))


def format_cycle_summary(cycle):
    """Format detailed cycle summary showing books and bargain/raise per leg."""
    if not cycle or not cycle.get('legs'):
        return ''
    parts = []
    for o in cycle['legs']:
        bp, rp = o['bargain_pct'], o['raise_pct']
        neg_tag = '不议价' if (bp == 0 and rp == 0) else '%d/%d' % (bp, rp)
        parts.append('%s(%d书·%s)' % (o['from_city'], o['restock'], neg_tag))
    parts.append(cycle['legs'][0]['from_city'])
    return ' → '.join(parts)
