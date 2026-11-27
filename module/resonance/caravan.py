"""Scheduled automated caravan trading task for 雷索纳斯 (Resonance Solstice)."""

import copy
from datetime import datetime, timedelta
import json
import os

import numpy as np

from module.logger import logger
from module.ocr.ocr import Ocr
from module.resonance.columba import fetch_prices, load_columba_data, normalize_player_config
from module.resonance.fatigue import (
    REST_AREA_MAX_DRINKS, REST_AREA_MIN_FATIGUE, compute_fatigue_recovery_minutes,
    is_rest_area_done_today, mark_rest_area_done, nearest_rest_area_city, normalize_fatigue_item_mode,
)
from module.resonance.invest import ResonanceInvest
from module.resonance.map_nav import MAP_COORDS_05X, canonical_city_name
from module.resonance.market import (
    MARKET_FILTER_THRESHOLDS, MARKET_OVERFLOW_FATIGUE, build_market_status_record, evaluate_market_quality,
    save_market_status,
)
from module.resonance.page import page_main, page_resonance_trade_buy
from module.resonance.profit_log import parse_sell_profit_text, record_trade_profit
from module.resonance.route import _calc_fatigue, recommend_routes
from module.resonance.shop import filter_names
from module.resonance.smart_cycle import (
    DRIVE_FATIGUE_BUFFER, format_cycle_summary, leg_atomic_fatigue_budget, load_smart_state, plan_smart_cycle_leg,
    plan_smart_endgame_leg, record_negotiation_fatigue, record_zero_book_buy, safe_negotiation_budget,
    update_smart_books,
)

TRADE_STATE_PATH = os.path.join('config', 'state', 'resonance_trade_state.json')
PROFIT_OCR = Ocr((1050, 534, 1255, 566), lang='cnocr', threshold=128, alphabet='0123456789,+-', name='Sell profit')


def load_trade_state(path=TRADE_STATE_PATH):
    """Load persisted crash-recovery checkpoint for cargo origin/target."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_trade_state(bought_city, target_city, negotiate_sell=False, expected_profit=0,
                     sell_raise_target=None, path=TRADE_STATE_PATH):
    """Persist pending transit state after buying cargo in `bought_city`."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + '.tmp'
    payload = {
        'bought_city': bought_city, 'target_city': target_city,
        'negotiate_sell': bool(negotiate_sell), 'expected_profit': int(expected_profit or 0),
    }
    if sell_raise_target is not None:
        payload['sell_raise_target'] = int(sell_raise_target)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)


def clear_trade_state(path=TRADE_STATE_PATH):
    """Remove pending transit checkpoint after arriving and selling cargo."""
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def build_player_config(profile, config, data):
    """Merge auto-scanned player profile with WebUI trading parameters."""
    raw_excluded = filter_names(getattr(config, 'ResonanceTrade_ExcludedCities', '武林源'))
    excluded = {canonical_city_name(name) for name in raw_excluded if canonical_city_name(name)}
    for city in data['cities']:
        if city not in MAP_COORDS_05X:
            excluded.add(city)

    bargain_pct = int(getattr(config, 'ResonanceTrade_BargainPercent', 20) or 0)
    raise_pct = int(getattr(config, 'ResonanceTrade_RaisePercent', 20) or 0)
    return_bargain = bool(getattr(config, 'ResonanceTrade_ReturnBargain', False))
    bargain_cfg = {
        'bargainPercent': bargain_pct, 'raisePercent': raise_pct,
        'bargainFatigue': 0, 'raiseFatigue': 0, 'disabled': bargain_pct == 0 and raise_pct == 0,
    }
    ret_bargain_cfg = (
        dict(bargain_cfg) if return_bargain
        else {'bargainPercent': 0, 'raisePercent': 0, 'bargainFatigue': 0, 'raiseFatigue': 0, 'disabled': True}
    )
    raw = {
        'maxLot': int(profile.get('maxLot', 500) or 500),
        'prestige': dict(profile.get('prestige', {})), 'roles': dict(profile.get('roles', {})),
        'onegraph': {
            'maxRestock': int(getattr(config, 'ResonanceTrade_RestockBooks', 2) or 0),
            'goAndReturn': bool(getattr(config, 'ResonanceTrade_RoundTrip', False)),
        },
        'bargain': dict(bargain_cfg), 'returnBargain': ret_bargain_cfg, 'excludedCities': sorted(excluded),
    }
    return normalize_player_config(raw, data=data)


def _empty_leg(from_city, to_city, roles, data):
    """Construct an empty repositioning leg when no goods are profitable."""
    return {
        'combinations': [], 'buy_order': [], 'profit': 0, 'restock': 0,
        'fatigue': _calc_fatigue(from_city, to_city, roles, data),
        'profit_per_fatigue': 0, 'general_profit_index': 0, 'used_lot': 0,
    }


def _reposition_leg(from_city, to_city, prices, player_config, data, best_route):
    """Plan a 0-restock repositioning leg from `from_city` to `to_city` without negotiation."""
    repo_cfg = copy.deepcopy(player_config)
    repo_cfg['onegraph']['maxRestock'] = 0
    repo_cfg['onegraph']['goAndReturn'] = False
    repo_cfg['bargain'] = {'bargainPercent': 0, 'raisePercent': 0, 'bargainFatigue': 0, 'raiseFatigue': 0, 'disabled': True}
    repo_cfg['excludedCities'] = [c for c in repo_cfg.get('excludedCities', ()) if c != from_city]
    repo_routes = recommend_routes(prices, player_config=repo_cfg, data=data, sort_by='profit', go_and_return=False, max_restock=0, from_city=from_city, to_city=to_city, limit=1)
    repo_leg = repo_routes[0]['go'] if repo_routes and repo_routes[0]['profit'] > 0 else _empty_leg(from_city, to_city, player_config['roles'], data)
    return {'from_city': from_city, 'to_city': to_city, 'leg': repo_leg, 'is_reposition': True, 'is_return': False, 'best_route': best_route}


def _plan_manual_leg(current_city, city_a, city_b, prices, player_config, data):
    """Plan next profitable leg between two manually chosen cities (or 0-restock reposition to closer)."""
    manual_cfg = copy.deepcopy(player_config)
    manual_cfg['excludedCities'] = [c for c in manual_cfg.get('excludedCities', ()) if c not in (city_a, city_b)]
    roles = manual_cfg.get('roles', {})
    if current_city in (city_a, city_b):
        is_return = current_city == city_b
        src, dst = (city_b, city_a) if is_return else (city_a, city_b)
        cfg = copy.deepcopy(manual_cfg)
        if is_return:
            cfg['bargain'] = dict(cfg['returnBargain'])
        routes = recommend_routes(prices, player_config=cfg, data=data, sort_by='profit', go_and_return=False, from_city=src, to_city=dst, limit=1)
        leg = routes[0]['go'] if routes and routes[0]['profit'] > 0 else _empty_leg(src, dst, roles, data)
        return {'from_city': src, 'to_city': dst, 'leg': leg, 'is_reposition': False, 'is_return': is_return, 'best_route': routes[0] if routes else None}
    entry = min((city_a, city_b), key=lambda c: _calc_fatigue(current_city, c, roles, data))
    return _reposition_leg(current_city, entry, prices, manual_cfg, data, None)


def plan_next_leg(current_city, prices, player_config, sort_by, data, manual_cities=None):
    """Pick optimal leg: manual A<->B shuttle if configured, else global best A->B with 0-restock C->A."""
    if manual_cities:
        city_a, city_b = canonical_city_name(manual_cities[0]), canonical_city_name(manual_cities[1])
        if city_a and city_b and city_a != city_b and city_a in MAP_COORDS_05X and city_b in MAP_COORDS_05X:
            return _plan_manual_leg(current_city, city_a, city_b, prices, player_config, data)

    routes = recommend_routes(prices, player_config=player_config, data=data, sort_by=sort_by, limit=1)
    if not routes:
        return None
    best = routes[0]
    src, dst = best['from_city'], best['to_city']
    if current_city == src:
        return {'from_city': src, 'to_city': dst, 'leg': best['go'], 'is_reposition': False, 'is_return': False, 'best_route': best}
    if best['go_and_return'] and current_city == dst and best['ret'] is not None:
        return {'from_city': dst, 'to_city': src, 'leg': best['ret'], 'is_reposition': False, 'is_return': True, 'best_route': best}
    return _reposition_leg(current_city, src, prices, player_config, data, best)


def read_sell_profit(image):
    """Read staged sell profit (signed int) from the exchange sell panel, or None."""
    if image is None:
        return None
    crop = image[534:566, 1050:1255]
    gray = crop.max(axis=2)
    up = np.repeat(np.repeat(gray, 2, axis=0), 2, axis=1)
    rgb = np.stack((up, up, up), axis=2)
    raw = PROFIT_OCR.ocr([rgb], direct_ocr=True)
    text = str(raw[0] if isinstance(raw, list) and raw else raw or '').strip()
    val = parse_sell_profit_text(text)
    if val is None:
        return None
    if val > 0:
        bright = crop[crop.max(axis=2) > 140].astype(int)
        if len(bright):
            red_mask = (bright[:, 0] - bright[:, 1] > 60) & (bright[:, 0] > 150)
            if int(red_mask.sum()) > len(bright) * 0.4:
                val = -val
    return val


class ResonanceCaravan(ResonanceInvest):
    """Scheduled multi-leg trading loop with repositioning and fatigue recovery."""

    def _sell_and_record_profit(self, current_city, state, raise_target=0):
        """Sell cargo and persist actual (or expected fallback) profit into the 30-day ledger."""
        sold = self.sell_all(raise_target=raise_target)
        if not sold:
            return False
        profit = read_sell_profit(getattr(self, '_last_sell_image', None))
        estimated = False
        if profit is None and state.get('expected_profit'):
            profit = int(state['expected_profit'])
            estimated = True
        if profit is not None:
            from_city = state.get('bought_city') or ''
            config_name = getattr(self.config, 'config_name', '') or 'default'
            record_trade_profit(config_name, profit, from_city=from_city, to_city=current_city, estimated=estimated)
            tag = ' (预估)' if estimated else ''
            logger.info('跑商卖出利润: %+d (%s -> %s%s)', profit, from_city or '未知', current_city, tag)
        return True

    @staticmethod
    def _estimate_leg_fatigue(leg, bargain_pct, raise_pct, is_reposition, is_return=False, return_bargain=False):
        """Estimate conservative atomic fatigue needed for buy-neg, driving, and sell-neg."""
        allow_neg = (not is_reposition) and (not is_return or return_bargain) and bool(leg.get('combinations'))
        bp, rp = (bargain_pct, raise_pct) if allow_neg else (0, 0)
        return leg_atomic_fatigue_budget(leg.get('fatigue', 0), bp, rp)

    def _schedule_fatigue_wait(self, cur_fatigue, max_fatigue, needed_fatigue):
        """Return to main screen and schedule NextRun based on 6 min/fatigue recovery."""
        wait_min = max(6, compute_fatigue_recovery_minutes(cur_fatigue, max_fatigue, needed_fatigue))
        remaining = max(0, max_fatigue - cur_fatigue)
        logger.info('琐呐跑商疲劳不足 (剩余 %d, 本趟预计需要 %d), 已排期 %d 分钟后继续', remaining, needed_fatigue, wait_min)
        self.ui_goto_main()
        self.config.task_delay(minute=wait_min)

    def _has_or_recover_fatigue(self, cur_fatigue, max_fatigue, needed_fatigue, item_mode, use_bento):
        """Return True if remaining fatigue suffices or can be recovered via items/bento."""
        if max_fatigue - cur_fatigue >= needed_fatigue:
            return True
        return (use_bento or item_mode != 'none') and self.recover_fatigue(cur_fatigue, max_fatigue, needed_fatigue, item_mode=item_mode, use_bento=use_bento)

    def _ensure_fatigue_for_leg(self, cur_fatigue, max_fatigue, needed_fatigue, item_mode, use_bento):
        """Ensure sufficient fatigue to execute the next leg, recovering or delaying if short."""
        if self._has_or_recover_fatigue(cur_fatigue, max_fatigue, needed_fatigue, item_mode, use_bento):
            return True
        self._schedule_fatigue_wait(cur_fatigue, max_fatigue, needed_fatigue)
        return False

    def _read_current_fatigue(self, profile):
        """Read live (cur, max) fatigue from the top bar, retrying briefly before returning None."""
        fatigue = self.read_fatigue()
        if fatigue is not None:
            return fatigue
        self.enter_exchange(page_resonance_trade_buy)
        for attempt in range(3):
            if attempt > 0:
                self.device.screenshot()
            fatigue = self.read_fatigue()
            if fatigue is not None:
                return fatigue
        logger.warning('当前疲劳值 OCR 多次失败，无法确认剩余疲劳')
        return None

    def _delay_unreadable_fatigue(self):
        """Return to main screen and retry later when live fatigue cannot be read."""
        logger.warning('无法读取当前疲劳值，暂不跑商，10 分钟后重试')
        self.ui_goto_main()
        self.config.task_delay(minute=10)

    def _resume_pending_transit(self, current_city, state, use_ramming, item_mode, use_bento, data):
        """Depart directly if crash happened after buying cargo in `current_city`."""
        bought = state.get('bought_city')
        target = state.get('target_city')
        if bought != current_city or not target or target == current_city or target not in MAP_COORDS_05X:
            return current_city, False

        logger.info('检测到上次在 %s 购入货物尚未出发，跳过卖出并直接前往 %s', bought, target)
        fatigue = self._read_current_fatigue({})
        if fatigue is None:
            self._delay_unreadable_fatigue()
            return None, False
        cur_f, max_f = fatigue
        needed = _calc_fatigue(current_city, target, {}, data) + DRIVE_FATIGUE_BUFFER
        if not self._ensure_fatigue_for_leg(cur_f, max_f, needed, item_mode, use_bento):
            return None, False
        self.travel_to(target, use_ramming=use_ramming, configure_assist=True)
        return target, True

    def _maybe_drink_rest_area(self, current_city, player_cfg, state, use_ramming, assist_done, data):
        """Visit nearest rest area to drink sodas when fatigue >= 300 and daily quota remains."""
        if is_rest_area_done_today() or state.get('bought_city') == current_city:
            return current_city, assist_done
        fatigue = self._read_current_fatigue(player_cfg)
        if fatigue is None:
            return current_city, assist_done
        cur_f, max_f = fatigue
        if cur_f < REST_AREA_MIN_FATIGUE:
            logger.info('当前疲劳 %d 低于 %d，暂不去休息区喝汽水', cur_f, REST_AREA_MIN_FATIGUE)
            return current_city, assist_done

        rest_city, travel_f = nearest_rest_area_city(current_city, player_cfg['roles'], data)
        if rest_city != current_city:
            if max_f - cur_f < travel_f + DRIVE_FATIGUE_BUFFER:
                return current_city, assist_done
            logger.info('当前疲劳 %d >= %d，前往最近休息区 %s 喝汽水', cur_f, REST_AREA_MIN_FATIGUE, rest_city)
            self._sell_and_record_profit(current_city, state, raise_target=0)
            clear_trade_state()
            state.clear()
            self.travel_to(rest_city, use_ramming=use_ramming, configure_assist=not assist_done)
            current_city = rest_city
            assist_done = True

        drinks, exhausted, _ = self.drink_rest_area_soda(max_drinks=REST_AREA_MAX_DRINKS)
        if exhausted or drinks >= REST_AREA_MAX_DRINKS:
            mark_rest_area_done()
        return current_city, assist_done

    def _check_market_gate(self, prices, player_cfg, sort_by, manual_cities, cur_fatigue,
                           market_filter, overflow_protect, wait_min, data, route_mode='auto'):
        """Evaluate live market quality, persist WebUI status, and gate poor markets."""
        config_name = getattr(self.config, 'config_name', '') or 'default'
        smart_state = load_smart_state(config_name) if route_mode == 'smart_cycle' else None
        mq = evaluate_market_quality(prices, player_cfg, sort_by, data, manual_cities=manual_cities, route_mode=route_mode, smart_state=smart_state)
        if mq is None:
            return True
        threshold = MARKET_FILTER_THRESHOLDS.get(market_filter)
        if threshold is None:
            save_market_status(config_name, build_market_status_record(mq, 'open', market_filter, fatigue=cur_fatigue))
            return True
        if mq['index'] >= threshold:
            save_market_status(config_name, build_market_status_record(mq, 'pass', market_filter, fatigue=cur_fatigue))
            logger.info('当前行情指数 %.1f >= 门槛 %.0f (实时=%d, 平价基准=%d, 常规上限=%d)，继续跑商', mq['index'], threshold, mq['live'], mq['base'], mq['good'])
            return True
        if overflow_protect and cur_fatigue <= MARKET_OVERFLOW_FATIGUE:
            save_market_status(config_name, build_market_status_record(mq, 'overflow', market_filter, fatigue=cur_fatigue))
            logger.info('当前行情指数 %.1f < 门槛 %.0f，但当前疲劳 %d <= %d（防疲劳溢出），放行跑商', mq['index'], threshold, cur_fatigue, MARKET_OVERFLOW_FATIGUE)
            return True
        delay_min = max(5, int(wait_min or 30))
        next_check = (datetime.now() + timedelta(minutes=delay_min)).strftime('%Y-%m-%d %H:%M:%S')
        save_market_status(config_name, build_market_status_record(mq, 'wait', market_filter, fatigue=cur_fatigue, next_check=next_check))
        logger.info('当前行情指数 %.1f < 门槛 %.0f (实时=%d, 平价基准=%d, 常规上限=%d)，暂不跑商，%d 分钟后复查', mq['index'], threshold, mq['live'], mq['base'], mq['good'], delay_min)
        self.ui_goto_main()
        self.config.task_delay(minute=delay_min)
        return False

    def _plan_leg_for_mode(self, current_city, prices, player_cfg, sort_by, manual_cities, route_mode, config_name, data):
        """Select the next trading leg using smart multi-city cycle, manual shuttle, or auto mode."""
        if route_mode == 'smart_cycle':
            return plan_smart_cycle_leg(current_city, prices, player_cfg, data, smart_state=load_smart_state(config_name))
        return plan_next_leg(current_city, prices, player_cfg, sort_by, data, manual_cities=manual_cities)

    def _execute_one_leg(self, current_city, prices, player_cfg, state, opts):
        """Sell arrived cargo, plan next leg, buy if needed, and travel to next city."""
        (sort_by, bargain_pct, raise_pct, return_bargain, use_ramming, item_mode,
         use_bento, use_rest_area, auto_invest, invest_state, route_mode, manual_cities, assist_done,
         market_opts, data) = opts
        market_filter, overflow_protect, wait_min = market_opts
        config_name = getattr(self.config, 'config_name', '') or 'default'

        if state.get('bought_city') != current_city:
            sell_raise = state.get('sell_raise_target')
            if sell_raise is None:
                sell_raise = raise_pct if state.get('negotiate_sell', False) else 0
            sold = self._sell_and_record_profit(current_city, state, raise_target=int(sell_raise))
            if route_mode == 'smart_cycle' and sold and int(sell_raise) > 0 and getattr(self, '_last_negotiate_fatigue', None):
                record_negotiation_fatigue(config_name, False, int(sell_raise), self._last_negotiate_fatigue)
                self._last_negotiate_fatigue = None
            clear_trade_state()
            state.clear()
            if use_rest_area:
                current_city, assist_done = self._maybe_drink_rest_area(current_city, player_cfg, state, use_ramming, assist_done, data)
        if auto_invest and invest_state.get('city') != current_city and state.get('bought_city') != current_city:
            self.invest_current_city()
            invest_state['city'] = current_city
        fatigue = self._read_current_fatigue(player_cfg)
        if fatigue is None:
            self._delay_unreadable_fatigue()
            return None, assist_done
        if state.get('bought_city') != current_city and not self._check_market_gate(prices, player_cfg, sort_by, manual_cities, fatigue[0], market_filter, overflow_protect, wait_min, data, route_mode=route_mode):
            return None, assist_done
        plan = self._plan_leg_for_mode(current_city, prices, player_cfg, sort_by, manual_cities, route_mode, config_name, data)
        if plan is None:
            logger.warning('琐呐跑商未找到盈利路线，30 分钟后重试')
            self.ui_goto_main()
            self.config.task_delay(minute=30)
            return None, assist_done
        needed = (
            int(plan.get('atomic_fatigue') or leg_atomic_fatigue_budget(
                plan['leg'].get('fatigue', 0), plan.get('bargain_target', 0), plan.get('raise_target', 0),
            ))
            if plan.get('is_smart_cycle') else self._estimate_leg_fatigue(
                plan['leg'], bargain_pct, raise_pct, plan['is_reposition'],
                is_return=plan['is_return'], return_bargain=return_bargain,
            )
        )
        if not self._has_or_recover_fatigue(fatigue[0], fatigue[1], needed, item_mode, use_bento):
            endgame = None
            if plan.get('is_smart_cycle'):
                if use_bento or item_mode != 'none':
                    fatigue = self._read_current_fatigue(player_cfg) or fatigue
                endgame = plan_smart_endgame_leg(
                    current_city, plan.get('_edges'), plan.get('cycle'),
                    max(0, fatigue[1] - fatigue[0]), book_weight=plan['cycle']['book_weight'],
                )
            if endgame is None:
                self._schedule_fatigue_wait(fatigue[0], fatigue[1], needed)
                return None, assist_done
            plan = endgame

        buy_bargain, next_negotiate_sell, next_sell_raise = self._log_planned_leg(plan, bargain_pct, raise_pct, return_bargain)
        if plan['leg'].get('combinations'):
            sell_r = next_sell_raise if next_sell_raise is not None else (raise_pct if next_negotiate_sell else 0)
            buy_reserve = int(plan['leg'].get('fatigue', 0)) + safe_negotiation_budget(sell_r) + DRIVE_FATIGUE_BUFFER
            bought = self.buy_plan(plan['leg'], restock_books=plan['leg']['restock'], bargain_target=buy_bargain, reserve_fatigue=buy_reserve)
            if bought:
                self._finish_bought_leg(current_city, plan, state, buy_bargain, next_negotiate_sell, next_sell_raise, route_mode, config_name)
        self.travel_to(plan['to_city'], use_ramming=use_ramming, configure_assist=not assist_done)
        return plan['to_city'], True

    def _finish_bought_leg(self, current_city, plan, state, buy_bargain, next_negotiate_sell, next_sell_raise, route_mode, config_name):
        """Persist post-buy checkpoint state and update smart-cycle telemetry."""
        exp_profit = plan['leg'].get('profit', 0)
        save_trade_state(current_city, plan['to_city'], negotiate_sell=next_negotiate_sell, expected_profit=exp_profit, sell_raise_target=next_sell_raise)
        state.update({'bought_city': current_city, 'target_city': plan['to_city'], 'negotiate_sell': next_negotiate_sell, 'expected_profit': exp_profit})
        if next_sell_raise is not None:
            state['sell_raise_target'] = next_sell_raise
        if route_mode != 'smart_cycle':
            return
        restock_owned = getattr(self, '_last_restock_owned', None)
        if restock_owned is not None:
            update_smart_books(config_name, restock_owned)
            self._last_restock_owned = None
        if plan['leg'].get('restock', 0) == 0:
            record_zero_book_buy(config_name, current_city)
        neg_f = getattr(self, '_last_negotiate_fatigue', None)
        if buy_bargain > 0 and neg_f:
            record_negotiation_fatigue(config_name, True, buy_bargain, neg_f)
            self._last_negotiate_fatigue = None

    def _log_planned_leg(self, plan, bargain_pct, raise_pct, return_bargain):
        """Log planned leg details and return `(buy_bargain, next_negotiate_sell, next_sell_raise)`."""
        if plan.get('is_smart_cycle'):
            buy_bargain, next_sell_raise = int(plan.get('bargain_target', 0)), int(plan.get('raise_target', 0))
            logger.info(
                '琐呐跑商[智能环路]: %s -> %s (书=%d, 砍%d/抬%d, 预计利润=%d, 疲劳=%d+%d) | %s',
                plan['from_city'], plan['to_city'], plan['leg'].get('restock', 0), buy_bargain, next_sell_raise,
                plan['leg'].get('profit', 0), plan['leg'].get('fatigue', 0), plan.get('expected_neg_fatigue', 0),
                format_cycle_summary(plan.get('cycle')),
            )
            return buy_bargain, next_sell_raise > 0, next_sell_raise
        allow_neg = (not plan['is_reposition']) and (not plan['is_return'] or return_bargain)
        buy_bargain = bargain_pct if allow_neg else 0
        leg_kind = '接驳段(0本)' if plan['is_reposition'] else ('回程' if plan['is_return'] else '主路线')
        logger.info('琐呐跑商[%s]: %s -> %s (进货书=%d, 预计利润=%d, 路程疲劳=%d)',
                    leg_kind, plan['from_city'], plan['to_city'], plan['leg'].get('restock', 0), plan['leg'].get('profit', 0), plan['leg'].get('fatigue', 0))
        return buy_bargain, allow_neg and (raise_pct > 0), None

    def _collect_run_config(self):
        """Collect runtime ResonanceTrade options from config into a flat tuple."""
        cfg = self.config
        route_mode = getattr(cfg, 'ResonanceTrade_RouteMode', 'auto')
        manual = (getattr(cfg, 'ResonanceTrade_ManualCityA', ''), getattr(cfg, 'ResonanceTrade_ManualCityB', '')) if route_mode == 'manual' else None
        market_opts = (
            getattr(cfg, 'ResonanceTrade_MarketFilter', 'all'),
            bool(getattr(cfg, 'ResonanceTrade_MarketOverflowProtect', True)),
            max(5, int(getattr(cfg, 'ResonanceTrade_MarketWaitMinutes', 30) or 30)),
        )
        return (
            getattr(cfg, 'ResonanceTrade_SortBy', 'profit_per_fatigue'),
            int(getattr(cfg, 'ResonanceTrade_BargainPercent', 20) or 0), int(getattr(cfg, 'ResonanceTrade_RaisePercent', 20) or 0),
            bool(getattr(cfg, 'ResonanceTrade_ReturnBargain', False)), bool(getattr(cfg, 'ResonanceTrade_UseRamming', False)),
            normalize_fatigue_item_mode(getattr(cfg, 'ResonanceTrade_UseFatigueItem', 'none')),
            bool(getattr(cfg, 'ResonanceTrade_UseBento', False)), bool(getattr(cfg, 'ResonanceTrade_UseRestArea', False)),
            bool(getattr(cfg, 'ResonanceTrade_AutoInvest', False)), route_mode, manual, market_opts,
        )

    def run(self):
        """Run automated trading legs until fatigue runs out and schedule next run."""
        from module.resonance.local_shop import local_shop_state_path
        from module.resonance.smart_state import _read_json_dict

        cross_get = getattr(self.config, 'cross_get', None)
        if (cross_get and cross_get('ResonanceLocalShop.Scheduler.Enable', False)
                and _read_json_dict(local_shop_state_path(self.config.config_name)).get('cargo')):
            logger.info('扫货任务有沿途货物待售，本次常规跑商延后')
            self.config.task_delay(minute=15)
            return
        data = load_columba_data()
        self.ui_ensure(page_main, skip_first_screenshot=False)
        self.wait_until_docked()
        force_refresh = bool(getattr(self.config, 'ResonanceTrade_RefreshProfile', False))
        profile = self.ensure_profile(force_refresh=force_refresh)
        if force_refresh:
            self.config.ResonanceTrade_RefreshProfile = False
        player_cfg = build_player_config(profile, self.config, data)
        current_city = self.get_current_city()
        if current_city not in MAP_COORDS_05X:
            logger.warning('当前城市 %r 暂未收录世界地图坐标，无法自动跑商', current_city)
            self.ui_goto_main()
            self.config.task_delay(minute=60)
            return

        (sort_by, bargain_pct, raise_pct, return_bargain, use_ramming, item_mode,
         use_bento, use_rest_area, auto_invest, route_mode, manual_cities, market_opts) = self._collect_run_config()
        state, invest_state = load_trade_state(), {'city': None}
        current_city, assist_done = self._resume_pending_transit(current_city, state, use_ramming, item_mode, use_bento, data)
        if current_city is None:
            return
        if use_rest_area:
            current_city, assist_done = self._maybe_drink_rest_area(current_city, player_cfg, state, use_ramming, assist_done, data)

        for _ in range(30):
            prices = fetch_prices(ttl=180, data=data)
            opts = (sort_by, bargain_pct, raise_pct, return_bargain, use_ramming, item_mode, use_bento,
                    use_rest_area, auto_invest, invest_state, route_mode, manual_cities, assist_done, market_opts, data)
            next_city, assist_done = self._execute_one_leg(current_city, prices, player_cfg, state, opts)
            if next_city is None:
                return
            current_city = next_city
        self.ui_goto_main()
        self.config.task_delay(minute=10)
