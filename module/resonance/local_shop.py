"""Weekly circuit of the six main-city Night Chains stores."""

import os
import re
from datetime import datetime, timedelta, timezone
from itertools import permutations

from requests import RequestException

from module.base.timer import Timer
from module.config.utils import filepath_config
from module.exception import GameStuckError
from module.logger import logger
from module.ocr.ocr import Ocr
from module.resonance import assets
from module.resonance.caravan import read_sell_profit
from module.resonance.columba import fetch_prices, load_columba_data, normalize_player_config
from module.resonance.fatigue import compute_fatigue_recovery_minutes
from module.resonance.map_nav import canonical_city_name
from module.resonance.page import (
    page_resonance_fatigue, page_resonance_rest_area, page_resonance_trade_buy, page_resonance_trade_sell,
)
from module.resonance.profit_log import record_trade_profit
from module.resonance.profile import ResonanceProfile
from module.resonance.route import calc_direction_matrix
from module.resonance.smart_state import _read_json_dict, _write_json_dict


CITIES = ('海角城', '贡露城', '七号自由港', '澄明数据中心', '修格里城', '曼德矿场')
CHINA_TIME = timezone(timedelta(hours=8))
OFFSET = (5, 5)
TOTAL_CURRENCY = (923, 653, 1035, 686)
BALANCE = Ocr((1118, 20, 1264, 48), lang='cnocr', threshold=95,
              alphabet='0123456789', name='Local shop balance')
TOTAL = Ocr((0, 0, 1, 1), threshold=95, alphabet='0123456789', name='Local shop total')
# Each of the eight local-shop cards keeps a near-white SOLD OUT plate here, even though
# the item icon and its gold price stay on the card.
SOLD_OUT_PLATE = (250, 250, 248)
SOLD_OUT_SLOTS = tuple(
    (721 + 336 * column, 193 + 130 * row, 806 + 336 * column, 233 + 130 * row)
    for row in range(4) for column in range(2)
)


def week_reset(now=None):
    """Monday at 05:00 in China time, at the start of the active shop week."""
    now = datetime.now(CHINA_TIME) if now is None else now.astimezone(CHINA_TIME)
    day = now - timedelta(hours=5)
    return (day - timedelta(days=day.weekday())).replace(hour=5, minute=0, second=0, microsecond=0)


def plan_route(current, pending, fatigue):
    """Find the minimum-fatigue open route, buying locally before departing."""
    start = (current,) if current in pending else ()
    remaining = sorted(pending - {current})

    def cost(route):
        return sum(fatigue[frozenset((src, dst))] for src, dst in zip((current,) + route, route))

    return start + min(permutations(remaining), key=cost)


def local_shop_state_path(config_name):
    profile = os.path.splitext(os.path.basename(filepath_config(config_name)))[0]
    return os.path.join('config', 'state', f'resonance_local_shop_{profile}.json')


def plan_sweep_trade(stops, matrix):
    """Choose the first zero-book load in the most profitable sequence of whole-cargo sales."""
    profit = [0] * len(stops)
    first = None
    for i in range(len(stops) - 2, -1, -1):
        profit[i] = profit[i + 1]
        for j in range(i + 1, len(stops)):
            leg = matrix.get(stops[i], {}).get(stops[j], {}).get(0)
            if leg and leg['profit'] > 0 and leg['profit'] + profit[j] >= profit[i]:
                profit[i] = leg['profit'] + profit[j]
                if i == 0:
                    first = (stops[j], leg)
    return first


class ResonanceLocalShop(ResonanceProfile):
    def run(self):
        reset = week_reset()
        week = reset.date().isoformat()
        next_week = (reset + timedelta(days=7)).astimezone().replace(tzinfo=None)
        path = local_shop_state_path(self.config.config_name)
        state = _read_json_dict(path)
        recorded = state.get('cities')
        done = set()
        if state.get('week') == week and isinstance(recorded, list):
            done = {city for city in CITIES if city in recorded}
        rescan = self.config.ResonanceLocalShop_Rescan
        if rescan:
            done.clear()
        state.update(week=week, cities=sorted(done))
        if rescan:
            _write_json_dict(state, path)
            self.config.ResonanceLocalShop_Rescan = False
        pending = set(CITIES) - done
        cargo = state.get('cargo')
        if not pending and not cargo:
            logger.info('琐呐本地黑月商店本周已完成')
            self.config.task_delay(target=next_week)
            return

        current = canonical_city_name(self.get_current_city())
        data = load_columba_data()
        if current not in data['cities']:
            raise GameStuckError('Resonance local shop could not identify the departure city')
        if cargo and cargo['bought_city'] == current:
            loaded = self.read_sweep_cargo(page_resonance_trade_buy)
            self.ui_goto_main()
            if loaded is None:
                self.config.task_delay(minute=15, target=next_week)
                return
            if loaded[:2] == (0, 0):
                state.pop('cargo')
                _write_json_dict(state, path)
                cargo = None
        fatigue = data['fatigue_map']
        stops = pending | ({cargo['target_city']} if cargo else set())
        route = plan_route(current, stops, fatigue)
        if not route or route[0] != current:
            route = (current,) + route
        logger.info('琐呐本地黑月商店路线 %s', ' → '.join((current,) + tuple(city for city in route if city != current)))
        for index, city in enumerate(route):
            if week_reset() != reset:
                self.config.task_delay(minute=1)
                return
            if city != current:
                self._open_profile_drawer()
                meter, _ = self._read_drawer_bars()
                self._close_profile_drawer()
                if meter is None:
                    raise GameStuckError('Resonance local shop could not read the fatigue bar')
                needed = fatigue[frozenset((current, city))] + max(0, meter[0] - meter[1])
                wait = compute_fatigue_recovery_minutes(*meter, needed)
                if wait:
                    logger.info('前往 %s 的疲劳额度不足，等待自然恢复', city)
                    self.config.task_delay(minute=wait, target=next_week)
                    return
                if not self.buy_sweep_cargo(route[index - 1:], data, state, path):
                    self.ui_goto_main()
                    self.config.task_delay(minute=15, target=next_week)
                    return
                self.travel_to(city)
                current = canonical_city_name(self.get_current_city())
                if current != city:
                    raise GameStuckError(f'Resonance local shop did not verify arrival at {city}')
            if city in pending:
                self.open_local_shop()
                if not self.buy_local_stock(reset):
                    logger.warning('%s 本地黑月商店尚未完成，稍后重试', city)
                    self.ui_goto_main()
                    self.config.task_delay(minute=60, target=next_week)
                    return
                done.add(city)
                state['cities'] = sorted(done)
                _write_json_dict(state, path)
                logger.info('%s 本地黑月商店已完成（%s/%s）', city, len(done), len(CITIES))
                self.ui_goto_main()
            if state.get('cargo', {}).get('target_city') == city:
                if not self.sell_sweep_cargo(city, state, path):
                    self.ui_goto_main()
                    self.config.task_delay(minute=30, target=next_week)
                    return
        self.config.task_delay(target=next_week)

    def read_sweep_cargo(self, page):
        self.enter_exchange(page)
        for attempt in range(3):
            if attempt:
                self.device.screenshot()
            cargo = self.read_cargo()
            if cargo is not None and cargo[2] > 0:
                return cargo
        return None

    def buy_sweep_cargo(self, stops, data, state, path):
        held = state.get('cargo')
        cargo = self.read_sweep_cargo(page_resonance_trade_buy)
        if cargo is None:
            logger.warning('无法读取扫货列车货舱，稍后再发车')
            return False
        loaded, staged, capacity = cargo
        if staged or loaded >= capacity or (loaded and not held):
            return True
        if held and not loaded:
            state.pop('cargo')
            _write_json_dict(state, path)
            held = None
        if held:
            stops = (stops[0], held['target_city'])
        try:
            prices = fetch_prices(data=data)
        except (RequestException, ValueError) as exc:
            logger.warning('未能获取沿途跑商行情：%s', exc)
            return bool(held and loaded)
        profile = getattr(self, '_sweep_profile', None)
        if profile is None:
            self.ui_goto_main()
            profile = self._sweep_profile = self.ensure_profile()
        cfg = normalize_player_config({
            'maxLot': capacity - loaded, 'prestige': profile['prestige'], 'roles': profile['roles'],
            'excludedCities': sorted(set(data['cities']) - set(stops)),
        }, data=data)
        matrix = calc_direction_matrix(prices, cfg, {'disabled': True}, data=data, max_restock=0)
        while True:
            plan = plan_sweep_trade(stops, matrix)
            if plan is None:
                logger.info('本站无沿途 0 书买入计划')
                return True
            target, leg = plan
            # Save the destination and known zero usage in case the receipt is interrupted.
            if not held:
                state['cargo'] = {'bought_city': stops[0], 'target_city': target, 'restock_used': 0}
                _write_json_dict(state, path)
            if self.buy_plan(leg, restock_books=0, bargain_target=0):
                logger.info('扫货沿途 0 书买入：%s → %s（预计利润 %s）', stops[0], target, leg['profit'])
                return True
            if self.read_sweep_cargo(page_resonance_trade_buy) != cargo:
                logger.warning('沿途买入后的货舱状态待确认，保留记录以便续跑')
                return False
            if not held:
                state.pop('cargo')
                _write_json_dict(state, path)
            del matrix[stops[0]][target]

    def sell_sweep_cargo(self, city, state, path):
        cargo = self.read_sweep_cargo(page_resonance_trade_sell)
        if cargo is None:
            return False
        if cargo[0]:
            profit = None

            def approve(image):
                nonlocal profit
                profit = read_sell_profit(image)
                return profit is not None and profit > 0

            if not self.sell_all(raise_target=0, approve=approve):
                logger.warning('%s 无法确认沿途货物可盈利卖出，保留货物稍后重试（利润 %s）', city, profit)
                return False
            record_trade_profit(self.config.config_name, profit, from_city=state['cargo']['bought_city'], to_city=city,
                                restock_used=state['cargo'].get('restock_used'))
            logger.info('扫货沿途卖出利润：+%s（%s）', profit, city)
        state.pop('cargo')
        _write_json_dict(state, path)
        self.ui_goto_main()
        return True

    def open_local_shop(self):
        self._open_profile_drawer()
        for _ in self.loop(timeout=8):
            if self.ui_page_appear(page_resonance_fatigue, offset=OFFSET):
                break
            self.appear_then_click(assets.LOCAL_SHOP_FATIGUE, offset=OFFSET, interval=2)
        else:
            raise GameStuckError('Resonance fatigue page did not open from the profile drawer')
        self.ui_ensure(page_resonance_rest_area, skip_first_screenshot=True)
        self.wait_until_still(assets.LOCAL_SHOP_REST_ENTRY, timeout=4, skip_first_screenshot=False)
        for _ in self.loop(timeout=12):
            if self.ui_page_appear(page_resonance_rest_area, offset=OFFSET):
                self.appear_then_click(assets.LOCAL_SHOP_REST_ENTRY, offset=OFFSET, interval=2)
                continue
            if self.appear(assets.LOCAL_SHOP_CHECK, offset=OFFSET):
                if self.appear(assets.LOCAL_SHOP_SELECTED, offset=OFFSET):
                    return
                self.appear_then_click(assets.LOCAL_SHOP_TAB, offset=OFFSET, interval=2)
        raise GameStuckError('Resonance local shop tab did not open')

    def local_batch_ready(self):
        return all(self.appear(button, offset=OFFSET) for button in (
            assets.LOCAL_SHOP_CHECK, assets.LOCAL_SHOP_SELECTED, assets.LOCAL_SHOP_BATCH_ON,
        ))

    def read_gold_total(self):
        icons = assets.TEMPLATE_LOCAL_SHOP_GOLD.match_multi(
            self.image_crop(TOTAL_CURRENCY), similarity=0.88, threshold=8,
        )
        if len(icons) == 1:
            left = TOTAL_CURRENCY[0] + icons[0].area[2]
            total = TOTAL.ocr([self.image_crop((left, 654, 1044, 687))], direct_ocr=True)
            if re.fullmatch(r'\d+', total):
                return int(total)
        return None

    def local_shop_empty(self):
        """All eight cards show the sold-out plate on the local tab.

        The plate is the only reliable proof: a sold-out card keeps its item icon and gold
        price, so the total and the footer All label can be empty with stock still listed.
        """
        if not (self.appear(assets.LOCAL_SHOP_CHECK, offset=OFFSET)
                and self.appear(assets.LOCAL_SHOP_SELECTED, offset=OFFSET)):
            return False
        # A full plate holds about 2000 matching pixels; the text ink takes the rest.
        return all(
            self.image_color_count(slot, SOLD_OUT_PLATE, threshold=12, count=1200)
            for slot in SOLD_OUT_SLOTS
        )

    def buy_local_stock(self, reset):
        total = self.select_all()
        if total == 0:
            return True
        if total is None:
            return False
        balance = self.read_gold_balance()
        if balance is None or balance < total:
            logger.warning('本地商店无法核对金币余额或余额不足（合计 %s，余额 %s）', total, balance)
            return False
        for attempt in range(2):
            if week_reset() != reset:
                return False
            if self.local_batch_ready() and self.appear(assets.LOCAL_SHOP_BUY, offset=OFFSET):
                self.device.click(assets.LOCAL_SHOP_BUY)
            else:
                return False
            result = self.wait_for_local_purchase(balance, total)
            if result:
                return True
            if (result is None or attempt or not self.local_batch_ready() or self.read_gold_balance() != balance
                    or self.read_gold_total() != total):
                break
            logger.info('本地商店金币余额及订单合计均未变，重试确认购买一次')
        logger.warning('本地商店未能核实购买结果（原余额 %s，订单合计 %s）', balance, total)
        return False

    def read_gold_balance(self):
        value = BALANCE.ocr(self.device.image)
        return int(value) if re.fullmatch(r'\d+', value) else None

    def wait_for_local_purchase(self, balance, total):
        """Return None if there was a receipt or discernible debit but settlement is uncertain."""
        received = False
        balance_changed = False
        check_balance = Timer(1).start()
        for _ in self.loop(skip_first=False, timeout=15):
            if self.handle_reward_popup():
                received = True
                continue
            if self.appear(assets.LOCAL_SHOP_CHECK, offset=OFFSET):
                if received:
                    return True
                if self.appear(assets.LOCAL_SHOP_SELECTED, offset=OFFSET) and check_balance.reached():
                    check_balance.reset()
                    remaining = self.read_gold_balance()
                    if remaining is not None and remaining != balance:
                        balance_changed = True
                        if remaining == balance - total:
                            logger.info('本地商店未看到获得物品弹窗，已核实扣除金币 %s', total)
                            return True
        return None if received or balance_changed else False

    def select_all(self):
        # Batch mode can appear before the footer finishes animating.
        clicks = 0
        settle = Timer(0.65).start()
        for _ in self.loop(skip_first=False, timeout=10):
            if not settle.reached():
                continue
            if self.local_shop_empty():
                return 0
            if self.local_batch_ready() and self.appear(assets.LOCAL_SHOP_BUY, offset=OFFSET):
                total = self.read_gold_total()
                if clicks and total:
                    return total
                if total is not None and clicks < 2:
                    # The All label changes colors; its position is fixed in this footer.
                    self.device.click(assets.LOCAL_SHOP_ALL)
                    clicks += 1
                    settle.reset()
            elif self.appear(assets.LOCAL_SHOP_SELECTED, offset=OFFSET):
                if self.appear_then_click(assets.LOCAL_SHOP_BATCH_OFF, offset=OFFSET, interval=2):
                    settle.reset()
        logger.warning('本地商店未读到可确认的金币合计（已点击全部 %s 次）', clicks)
        return None
