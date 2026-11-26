"""Trade route calculation for 雷索纳斯 (Resonance Solstice) via resonance-columba.com."""

import argparse
import math

from module.resonance.columba import (
    COLUMBA_BASE_URL, DATA_PATH, DEFAULT_PLAYER_CONFIG, GAME_EVENTS, PRESTIGE_CITIES, PRESTIGE_TABLE,
    decode_prices, fetch_player_config, fetch_prices, http_request, load_columba_data, normalize_player_config,
)

SORT_ALIASES = {
    'profit': 'profit',
    'byProfit': 'profit',
    'profit_per_fatigue': 'profit_per_fatigue',
    'byProfitPerFatigue': 'profit_per_fatigue',
    'general_profit_index': 'general_profit_index',
    'byGeneralProfitIndex': 'general_profit_index',
}


def js_round(value):
    """Match JavaScript Math.round() for non-negative trade values."""
    return int(math.floor(value + 0.5))


def _skill_effect(roles, skills, role):
    """Return resonance skill effect dict for a crew member, or None."""
    level = roles[role].get('resonance', 0)
    if not level:
        return None
    return skills.get(role, {}).get(str(level))


def _role_buy_more(roles, product, city, skills):
    """Sum buy-lot percentage bonuses from crew resonance skills."""
    total = 0
    is_special = product.get('type') == 'Special'
    name = product['name']
    for role in roles:
        effect = _skill_effect(roles, skills, role)
        if not effect:
            continue
        buy_more = effect.get('buyMore')
        if not buy_more:
            continue
        total += buy_more.get('product', {}).get(name, 0)
        if is_special:
            total += buy_more.get('city', {}).get(city, 0)
        total += buy_more.get('all', 0)
    return total


def _event_modifier(product, city, events, field, initial=0):
    """Sum product/city modifiers from active game events for the given field."""
    total = initial
    is_special = product.get('type') == 'Special'
    name = product['name']
    for event in GAME_EVENTS:
        if not event.get('playConfigurable') or events.get(event['name'], {}).get('activated'):
            mod = event.get(field, {})
            total += mod.get('product', {}).get(name, 0)
            if is_special:
                total += mod.get('city', {}).get(city, 0)
    return total


def _role_tax_cut(roles, city, skills):
    """Sum crew city tax-cut modifiers for a given city."""
    total = 0.0
    for role in roles:
        effect = _skill_effect(roles, skills, role)
        if not effect:
            continue
        total += effect.get('taxCut', {}).get('city', {}).get(city, 0)
    return total


def _calc_fatigue(from_city, to_city, roles, data):
    """Calculate driving fatigue between two cities after crew reductions."""
    base = data['fatigue_map'].get(frozenset((from_city, to_city)), 0)
    if base == 0:
        return 0
    reduction = 0
    skills = data['resonance_skills']
    for role in roles:
        effect = _skill_effect(roles, skills, role)
        if not effect:
            continue
        reduction += effect.get('other', {}).get('driveLessFatigue', 0)
    return max(0, base - reduction)


def _pair_candidates(from_city, to_city, prices, cfg, bargain_cfg, data):
    """Build profit-sorted list of tradeable goods from from_city to to_city."""
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

    disabled = bool(bargain_cfg.get('disabled'))
    bargain_pct = 0 if disabled else (bargain_cfg.get('bargainPercent') or 0)
    raise_pct = 0 if disabled else (bargain_cfg.get('raisePercent') or 0)
    tax_cut = _role_tax_cut(roles, from_city, skills)
    from_base_tax = from_p['specialTax'].get(from_attach, from_p['generalTax'])
    to_base_tax = to_p['specialTax'].get(to_attach, to_p['generalTax'])

    candidates = []
    for product in data['products_by_city'].get(from_city, ()):
        name = product['name']
        if product.get('type') == 'Craft' or not unlock.get(name, True):
            continue
        raw_buy = prices.get(name, {}).get('buy', {}).get(from_city, {}).get('price', 0)
        raw_sell = prices.get(name, {}).get('sell', {}).get(to_city, {}).get('price', 0)
        base_lot = product.get('buyLot', {}).get(from_city, 0)
        if not raw_buy or not raw_sell or not base_lot:
            continue

        buy_price = raw_buy * (1.0 - bargain_pct / 100.0)
        buy_tax_rate = from_base_tax + _event_modifier(product, from_city, events, 'taxVariation', 0.0) + tax_cut
        lot_pct = (_role_buy_more(roles, product, from_city, skills) + 100.0 * from_p['extraBuy']
                   + _event_modifier(product, from_city, events, 'buyMore', 0) + all_more + prod_more.get(name, 0))
        buy_lot = js_round(base_lot * (100.0 + lot_pct) / 100.0)

        sell_price = js_round(raw_sell * (1.0 + raise_pct / 100.0))
        sell_tax_rate = to_base_tax + tax_cut
        # Match resonance-columba's exact onegraph profit formula (including tax_cut term on both steps).
        single_profit = sell_price - buy_price
        single_profit -= single_profit * sell_tax_rate
        single_profit -= buy_price * (buy_tax_rate + tax_cut)
        single_profit = js_round(single_profit)
        if single_profit > 0:
            candidates.append({
                'name': name,
                'single_profit': single_profit,
                'buy_lot': buy_lot,
                'base_price': product['buyPrices'][from_city],
            })

    candidates.sort(key=lambda item: item['single_profit'], reverse=True)
    return candidates


def _pack_leg(candidates, max_lot, base_fatigue, bargain_cfg, restock, prev_leg):
    """Greedily pack cargo up to max_lot for a specific restock count."""
    used_lot = 0
    combinations = []
    for item in candidates:
        if used_lot >= max_lot:
            break
        avail = item['buy_lot'] * (restock + 1)
        take = min(max_lot - used_lot, avail)
        used_lot += take
        combinations.append({
            'name': item['name'],
            'buy_lot': take,
            'available_lot': avail,
            'profit': item['single_profit'] * take,
            'single_profit': item['single_profit'],
            'base_price': item['base_price'],
        })

    profit = sum(c['profit'] for c in combinations)
    disabled = bool(bargain_cfg.get('disabled'))
    fatigue = base_fatigue + (0 if disabled else ((bargain_cfg.get('bargainFatigue') or 0)
                                                  + (bargain_cfg.get('raiseFatigue') or 0)))
    last_non_wasting = restock
    if prev_leg is not None and profit == prev_leg['profit']:
        last_non_wasting = prev_leg['last_not_wasting_restock']

    ppf = js_round(profit / fatigue) if fatigue > 0 else 0
    gpi_denom = fatigue + 33 * restock
    gpi = js_round(profit / gpi_denom) if gpi_denom > 0 else 0
    return {
        'combinations': combinations,
        'buy_order': sorted(combinations, key=lambda item: item['base_price'], reverse=True),
        'profit': profit,
        'restock': restock,
        'fatigue': fatigue,
        'profit_per_fatigue': ppf,
        'general_profit_index': gpi,
        'used_lot': used_lot,
        'last_not_wasting_restock': last_non_wasting,
        'is_wasting_restock': last_non_wasting != restock,
    }


def _build_city_row(from_city, active_cities, prices, player_config, bargain_cfg, data, max_restock):
    """Build restock-indexed trade legs from one origin city to all destinations."""
    max_lot = player_config.get('maxLot', 500)
    roles = player_config.get('roles', {})
    row = {}
    for to_city in active_cities:
        if from_city == to_city:
            continue
        candidates = _pair_candidates(from_city, to_city, prices, player_config, bargain_cfg, data)
        base_fatigue = _calc_fatigue(from_city, to_city, roles, data)
        row[to_city] = _build_restock_map(candidates, max_lot, base_fatigue, bargain_cfg, max_restock)
    return row


def _build_restock_map(candidates, max_lot, base_fatigue, bargain_cfg, max_restock):
    """Compute leg outcomes for restock counts 0..max_restock."""
    by_restock = {}
    prev_leg = None
    for restock in range(0, max_restock + 1):
        leg = _pack_leg(candidates, max_lot, base_fatigue, bargain_cfg, restock, prev_leg)
        by_restock[restock] = leg
        prev_leg = leg
    return by_restock


def calc_direction_matrix(prices, player_config, bargain_cfg, data=None, max_restock=None):
    """Calculate optimal cargo combinations for all city pairs across restock counts 0..max_restock."""
    if not prices:
        return {}
    if data is None:
        data = load_columba_data()
    if max_restock is None:
        max_restock = player_config.get('onegraph', {}).get('maxRestock', 5)

    excluded = set(player_config.get('excludedCities', ()))
    active_cities = [city for city in data['cities'] if city not in excluded]
    return {
        from_city: _build_city_row(from_city, active_cities, prices, player_config, bargain_cfg, data, max_restock)
        for from_city in active_cities
    }


def _best_round_trip_route(src, dst, go_restocks, ret_matrix, max_restock):
    """Find the restock split between go and return legs maximizing total profit."""
    best_pair = None
    best_profit = 0
    for go_r in range(0, max_restock + 1):
        ret_r = max_restock - go_r
        g_leg = go_restocks.get(go_r)
        r_leg = ret_matrix.get(dst, {}).get(src, {}).get(ret_r)
        if g_leg is None or r_leg is None:
            continue
        total = g_leg['profit'] + r_leg['profit']
        if total > best_profit:
            best_profit = total
            best_pair = (g_leg, r_leg)
    if best_pair is None:
        return None
    g_leg, r_leg = best_pair
    fatigue = g_leg['fatigue'] + r_leg['fatigue']
    restock = g_leg['restock'] + r_leg['restock']
    gpi_denom = fatigue + 33 * restock
    return {
        'from_city': src,
        'to_city': dst,
        'go_and_return': True,
        'go': g_leg,
        'ret': r_leg,
        'profit': best_profit,
        'fatigue': fatigue,
        'restock': restock,
        'profit_per_fatigue': js_round(best_profit / fatigue) if fatigue > 0 else 0,
        'general_profit_index': js_round(best_profit / gpi_denom) if gpi_denom > 0 else 0,
    }


def _build_pair_route(src, dst, go_restocks, ret_matrix, go_and_return, max_restock):
    """Build a single one-way or round-trip route record for (src, dst)."""
    if not go_and_return:
        leg = go_restocks[max_restock]
        return {
            'from_city': src,
            'to_city': dst,
            'go_and_return': False,
            'go': leg,
            'ret': None,
            'profit': leg['profit'],
            'fatigue': leg['fatigue'],
            'restock': leg['restock'],
            'profit_per_fatigue': leg['profit_per_fatigue'],
            'general_profit_index': leg['general_profit_index'],
        }
    return _best_round_trip_route(src, dst, go_restocks, ret_matrix, max_restock)


def _collect_routes(go_matrix, ret_matrix, go_and_return, max_restock, from_city, to_city):
    """Collect candidate routes matching optional origin/destination filters."""
    routes = []
    for src, dsts in go_matrix.items():
        if from_city and src != from_city:
            continue
        _append_dst_routes(routes, src, dsts, ret_matrix, go_and_return, max_restock, to_city)
    return routes


def _append_dst_routes(routes, src, dsts, ret_matrix, go_and_return, max_restock, to_city):
    """Append routes from a single origin city matching optional destination filter."""
    for dst, go_restocks in dsts.items():
        if to_city and dst != to_city:
            continue
        route = _build_pair_route(src, dst, go_restocks, ret_matrix, go_and_return, max_restock)
        if route is not None:
            routes.append(route)


def recommend_routes(prices, player_config=None, data=None, sort_by='profit',
                     go_and_return=None, max_restock=None, from_city=None, to_city=None, limit=10):
    """Compute and sort one-way or round-trip trade routes."""
    sort_key = SORT_ALIASES.get(sort_by)
    if sort_key is None:
        raise ValueError('Unsupported sort_by: %r' % (sort_by,))
    if data is None:
        data = load_columba_data()
    cfg = normalize_player_config(player_config, data=data)
    if go_and_return is None:
        go_and_return = bool(cfg['onegraph'].get('goAndReturn', False))
    if max_restock is None:
        max_restock = int(cfg['onegraph'].get('maxRestock', 5))

    go_matrix = calc_direction_matrix(prices, cfg, cfg['bargain'], data=data, max_restock=max_restock)
    ret_matrix = (calc_direction_matrix(prices, cfg, cfg['returnBargain'], data=data, max_restock=max_restock)
                  if go_and_return else None)

    routes = _collect_routes(go_matrix, ret_matrix, go_and_return, max_restock, from_city, to_city)
    if go_and_return and not from_city and not to_city:
        pair_profits = {(r['from_city'], r['to_city']): r['profit'] for r in routes}
        routes = [
            r for r in routes
            if r['from_city'] < r['to_city']
            or pair_profits.get((r['to_city'], r['from_city'])) != r['profit']
        ]

    routes.sort(key=lambda r: r[sort_key], reverse=True)
    return routes if limit is None else routes[:limit]


def _format_buy_products(leg):
    """Format buy quantities ordered by descending base price."""
    return '  '.join(
        '%s %s' % (
            item['name'],
            '(买%d / 总%d)' % (item['buy_lot'], item['available_lot'])
            if item['buy_lot'] < item['available_lot'] else item['buy_lot'],
        )
        for item in leg['buy_order']
    )


def format_route_list(routes):
    """Format ranked routes into a human-readable summary table."""
    return '\n'.join(
        '%2d. %s %s %s | 利润: %d | 进货书: %d | 疲劳: %d | 利润/疲劳: %d | 综合参考利润: %d'
        % (idx, route['from_city'], '<->' if route['go_and_return'] else '->', route['to_city'],
           route['profit'], route['restock'], route['fatigue'],
           route['profit_per_fatigue'], route['general_profit_index'])
        for idx, route in enumerate(routes, 1)
    )


def _format_leg_detail(label, leg):
    """Format one leg of a trade route."""
    lines = [
        '%s利润: %d' % (label, leg['profit']),
        '%s进货书需求: %d' % (label, leg['restock']),
    ]
    if leg['is_wasting_restock']:
        lines.append('进货过多！使用超过%d本进货书后不会再产生收益。' % leg['last_not_wasting_restock'])
    lines.extend([
        '需要购买的产品: %s' % _format_buy_products(leg),
        '产品利润顺位: %s' % ' '.join(item['name'] for item in leg['combinations']),
        '所需舱位: %d' % leg['used_lot'],
        '疲劳: %d' % leg['fatigue'],
        '利润/疲劳: %d' % leg['profit_per_fatigue'],
    ])
    if leg['restock'] > 0:
        lines.append('综合参考利润: %d' % leg['general_profit_index'])
    return lines


def format_route_detail(route):
    """Format full cargo and profit breakdown for a single route."""
    arrow = '<->' if route['go_and_return'] else '->'
    lines = ['=== %s %s %s ===' % (route['from_city'], arrow, route['to_city'])]
    lines.extend(_format_leg_detail('', route['go']))
    if route['go_and_return'] and route['ret'] is not None:
        lines.append('--- 回程 (%s -> %s) ---' % (route['to_city'], route['from_city']))
        lines.extend(_format_leg_detail('回程', route['ret']))
        lines.extend([
            '--- 往返汇总 ---',
            '总利润: %d | 总进货书: %d | 总疲劳: %d | 利润/疲劳: %d | 综合参考利润: %d'
            % (route['profit'], route['restock'], route['fatigue'],
               route['profit_per_fatigue'], route['general_profit_index']),
        ])
    return '\n'.join(lines)


def _apply_bargain_args(bargain_cfg, pct_bargain, pct_raise, fatigue_bargain, fatigue_raise, disabled):
    """Apply CLI bargain/raise overrides onto a bargain dict."""
    for field, val in (('bargainPercent', pct_bargain), ('raisePercent', pct_raise),
                       ('bargainFatigue', fatigue_bargain), ('raiseFatigue', fatigue_raise)):
        if val is not None:
            bargain_cfg[field] = val
    if disabled:
        bargain_cfg['disabled'] = True


def _apply_prestige_args(prestige_cfg, specs):
    """Apply CLI prestige level specs onto the prestige dict."""
    for spec in specs or ():
        if '=' in spec:
            city, lv = spec.split('=', 1)
            prestige_cfg[city.strip()] = int(lv)
        else:
            prestige_cfg.update({city: int(spec) for city in prestige_cfg})


def _apply_cli_overrides(cfg, args):
    """Apply all CLI overrides onto normalized player config."""
    if args.max_lot is not None:
        cfg['maxLot'] = args.max_lot
    if args.restock is not None:
        cfg['onegraph']['maxRestock'] = args.restock
    if args.round_trip:
        cfg['onegraph']['goAndReturn'] = True
    _apply_bargain_args(cfg['bargain'], args.bargain, args.raise_pct,
                        args.bargain_fatigue, args.raise_fatigue, args.no_bargain)
    _apply_bargain_args(cfg['returnBargain'], args.ret_bargain, args.ret_raise,
                        args.ret_bargain_fatigue, args.ret_raise_fatigue, args.ret_no_bargain)
    _apply_prestige_args(cfg['prestige'], args.prestige)
    if args.exclude:
        cfg['excludedCities'] = list(set(cfg['excludedCities']) | set(args.exclude))
    return cfg


def _build_parser():
    """Create CLI argument parser for route recommendations."""
    parser = argparse.ArgumentParser(description='Resonance Solstice Columba trade route calculator')
    specs = (
        (('--sync-id',), {'help': 'Columba playerConfig sync ID'}),
        (('--max-lot',), {'type': int}),
        (('--restock',), {'type': int}),
        (('--bargain',), {'type': float}),
        (('--raise',), {'dest': 'raise_pct', 'type': float}),
        (('--bargain-fatigue',), {'type': int}),
        (('--raise-fatigue',), {'type': int}),
        (('--no-bargain',), {'action': 'store_true'}),
        (('--ret-bargain',), {'type': float}),
        (('--ret-raise',), {'type': float}),
        (('--ret-bargain-fatigue',), {'type': int}),
        (('--ret-raise-fatigue',), {'type': int}),
        (('--ret-no-bargain',), {'action': 'store_true'}),
        (('--prestige',), {'nargs': '*', 'help': 'Default level or City=Level pairs'}),
        (('--round-trip', '--go-and-return'), {'dest': 'round_trip', 'action': 'store_true'}),
        (('--sort',), {'default': 'profit', 'choices': ('profit', 'profit_per_fatigue', 'general_profit_index')}),
        (('--from',), {'dest': 'from_city'}),
        (('--to',), {'dest': 'to_city'}),
        (('--exclude',), {'nargs': '*'}),
        (('--top',), {'type': int, 'default': 10}),
        (('--detail',), {'type': int, 'default': 1, 'help': '1-based route index to expand (0 to hide)'}),
    )
    for flags, kwargs in specs:
        parser.add_argument(*flags, **kwargs)
    return parser


def main(argv=None):
    """Run CLI route query against live Columba market prices."""
    args = _build_parser().parse_args(argv)
    data = load_columba_data()
    raw_cfg = fetch_player_config(args.sync_id, data=data) if args.sync_id else None
    cfg = _apply_cli_overrides(normalize_player_config(raw_cfg, data=data), args)
    prices = fetch_prices(data=data)
    routes = recommend_routes(
        prices, player_config=cfg, data=data, sort_by=args.sort,
        from_city=args.from_city, to_city=args.to_city, limit=args.top,
    )
    if not routes:
        print('No profitable routes found.')
        return 0
    print(format_route_list(routes))
    if args.detail and 1 <= args.detail <= len(routes):
        print()
        print(format_route_detail(routes[args.detail - 1]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
