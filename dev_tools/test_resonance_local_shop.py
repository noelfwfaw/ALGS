import os
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from itertools import permutations
from unittest.mock import Mock, call, patch

import numpy as np
from PIL import Image

from module.config import server

# Replay the user's sold-out shop screenshot without storing its local path in the test.
SOLD_OUT_SCREENSHOT = os.environ.get('RESONANCE_LOCAL_SHOP_SCREENSHOT')


class TestResonanceLocalShop(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')
        global local_shop
        from module.resonance import local_shop

    def test_week_resets_at_five_on_monday(self):
        reset = datetime(2026, 11, 30, 5, tzinfo=local_shop.CHINA_TIME)
        self.assertEqual(local_shop.week_reset(reset), reset)
        self.assertEqual(local_shop.week_reset(reset - timedelta(seconds=1)), reset - timedelta(days=7))

    def test_route_minimizes_fatigue_from_current_city(self):
        fatigue = local_shop.load_columba_data()['fatigue_map']
        cities = set(local_shop.CITIES)
        for current in ('海角城', '贡露城', '曼德矿场', '铁盟哨站'):
            with self.subTest(current=current):
                route = local_shop.plan_route(current, cities, fatigue)
                self.assertEqual(set(route), cities)
                if current in cities:
                    self.assertEqual(route[0], current)

                def cost(legs):
                    return sum(fatigue[frozenset((a, b))] for a, b in zip((current,) + legs, legs) if a != b)

                self.assertEqual(cost(route), min(cost(path) for path in permutations(cities)))

    def make_task(self):
        task = local_shop.ResonanceLocalShop.__new__(local_shop.ResonanceLocalShop)
        task.config = Mock(config_name='local-shop-test', ResonanceLocalShop_Rescan=False)
        task.device = Mock()
        task.device.image = None
        task.get_current_city = Mock(return_value='贡露城')
        task.ui_goto_main = Mock()
        task.open_local_shop = Mock()
        return task

    def test_resume_only_missing_city_and_record_only_confirmed_purchase(self):
        task = self.make_task()
        task.buy_local_stock = Mock(side_effect=[False, True])
        record = {'week': local_shop.week_reset().date().isoformat(),
                  'cities': [city for city in local_shop.CITIES if city != '贡露城']}
        with patch.object(local_shop, '_read_json_dict', return_value=record), \
                patch.object(local_shop, '_write_json_dict') as save:
            task.run()
            save.assert_not_called()
            task.run()
            save.assert_called_once()
        self.assertEqual(set(save.call_args[0][0]['cities']), set(local_shop.CITIES))
        self.assertEqual(task.open_local_shop.call_count, 2)

    def test_completed_week_skips_navigation_and_rescan_clears_record(self):
        task = self.make_task()
        task.buy_local_stock = Mock(return_value=False)
        record = {'week': local_shop.week_reset().date().isoformat(), 'cities': list(local_shop.CITIES)}
        with patch.object(local_shop, '_read_json_dict', return_value=record), \
                patch.object(local_shop, '_write_json_dict') as save:
            task.run()
            task.get_current_city.assert_not_called()
            task.config.ResonanceLocalShop_Rescan = True
            task.run()
            save.assert_called_once()
        self.assertEqual(save.call_args[0][0]['cities'], [])
        self.assertFalse(task.config.ResonanceLocalShop_Rescan)
        task.open_local_shop.assert_called_once()

    def test_fatigue_over_cap_delays_the_next_unfinished_city(self):
        task = self.make_task()
        task._open_profile_drawer = Mock()
        task._close_profile_drawer = Mock()
        task._read_drawer_bars = Mock(return_value=((993, 912), 400))
        task.travel_to = Mock()
        record = {'week': local_shop.week_reset().date().isoformat(),
                  'cities': [city for city in local_shop.CITIES if city != '海角城']}
        with patch.object(local_shop, '_read_json_dict', return_value=record):
            task.run()
        task.open_local_shop.assert_not_called()
        task.travel_to.assert_not_called()
        fatigue = local_shop.load_columba_data()['fatigue_map']
        travel = fatigue[frozenset(('贡露城', '海角城'))]
        self.assertEqual(task.config.task_delay.call_args[1]['minute'], (81 + travel) * 6 + 2)

    def test_batch_purchase_requires_local_tab_and_does_not_resubmit(self):
        all_items = call(local_shop.assets.LOCAL_SHOP_ALL)
        buy = call(local_shop.assets.LOCAL_SHOP_BUY)
        for ready, totals, balances, receipts, completed, expected in (
            (False, [], [], [], False, []),
            (True, [0, 100], ['50'], [], False, [all_items]),
            (True, [0, 100, 0], ['200', '200', '200'], [[False]], False, [all_items, buy]),
            (True, [0, 100], ['200'], [[True, False]], True, [all_items, buy]),
            (True, [0, 127820], ['709098517', '708970697'], [[False]], True, [all_items, buy]),
            (True, [0, 100], ['200', '150'], [[False]], False, [all_items, buy]),
            (True, [0, 100, 100], ['200', '200', '200', '100'], [[False], [False]],
             True, [all_items, buy, buy]),
            (True, [0, 100, 100], ['200', '200', '200', '200'], [[False], [False]],
             False, [all_items, buy, buy]),
        ):
            with self.subTest(ready=ready, balances=balances, receipts=receipts):
                task = self.make_task()
                task.local_batch_ready = Mock(return_value=ready)
                task.local_shop_empty = Mock(return_value=False)
                task.appear = Mock(return_value=True)
                task.appear_then_click = Mock(return_value=False)
                task.read_gold_total = Mock(side_effect=totals)
                task.loop = Mock(side_effect=[iter(range(2)), *(iter(phase) for phase in receipts)])
                task.handle_reward_popup = Mock(side_effect=[seen for phase in receipts for seen in phase])
                with patch.object(local_shop.BALANCE, 'ocr', side_effect=balances), \
                        patch.object(local_shop, 'Timer') as timer:
                    timer.return_value.start.return_value.reached.return_value = True
                    self.assertEqual(task.buy_local_stock(local_shop.week_reset()), completed)
                self.assertEqual(task.device.click.call_args_list, expected)

    def test_receipt_without_returning_to_shop_does_not_allow_retry(self):
        task = self.make_task()
        task.loop = Mock(return_value=iter((None, None)))
        task.handle_reward_popup = Mock(side_effect=[True, False])
        task.appear = Mock(return_value=False)
        self.assertIsNone(task.wait_for_local_purchase(200, 100))

    def test_select_all_waits_for_batch_and_accepts_the_unselected_footer(self):
        task = self.make_task()
        task.local_batch_ready = Mock(side_effect=[False, False, True, True, True])
        task.local_shop_empty = Mock(return_value=False)
        task.appear = Mock(side_effect=lambda button, **kw: button != local_shop.assets.LOCAL_SHOP_ALL)
        task.appear_then_click = Mock(side_effect=[True, False])
        task.read_gold_total = Mock(side_effect=[None, 0, 100])
        task.loop = Mock(return_value=iter(range(5)))
        with patch.object(local_shop, 'Timer') as timer:
            timer.return_value.start.return_value.reached.return_value = True
            self.assertEqual(task.select_all(), 100)
        task.device.click.assert_called_once_with(local_shop.assets.LOCAL_SHOP_ALL)

    def test_empty_local_stock_needs_no_confirmation(self):
        task = self.make_task()
        task.loop = Mock(return_value=iter(range(1)))
        task.local_shop_empty = Mock(return_value=True)
        with patch.object(local_shop, 'Timer') as timer:
            timer.return_value.start.return_value.reached.return_value = True
            self.assertTrue(task.buy_local_stock(local_shop.week_reset()))
        task.device.click.assert_not_called()

    def shop_image(self, sold_out):
        image = np.zeros((720, 1280, 3), dtype=np.uint8)
        for left, top, right, bottom in local_shop.SOLD_OUT_SLOTS[:sold_out]:
            image[top:bottom, left:right] = local_shop.SOLD_OUT_PLATE
        return image

    def shop_task(self, sold_out=8, local_tab=True, loaded=True):
        task = self.make_task()
        task.device.image = self.shop_image(sold_out)
        task.appear = Mock(side_effect=lambda button, **kwargs: loaded and (
            button is local_shop.assets.LOCAL_SHOP_CHECK
            or (local_tab and button is local_shop.assets.LOCAL_SHOP_SELECTED)
        ))
        return task

    def test_empty_local_stock_needs_every_sold_out_plate(self):
        for sold_out, expected in ((8, True), (7, False), (0, False)):
            with self.subTest(sold_out=sold_out):
                self.assertEqual(self.shop_task(sold_out).local_shop_empty(), expected)

    def test_empty_local_stock_requires_the_loaded_local_tab(self):
        for loaded, local_tab in ((True, False), (False, True), (False, False)):
            with self.subTest(loaded=loaded, local_tab=local_tab):
                self.assertFalse(self.shop_task(local_tab=local_tab, loaded=loaded).local_shop_empty())

    def test_mixed_stock_is_not_empty_and_keeps_the_purchase_guard(self):
        task = self.shop_task(sold_out=7)
        task.local_batch_ready = Mock(return_value=True)
        task.appear = Mock(side_effect=lambda button, **kwargs: button is not local_shop.assets.LOCAL_SHOP_ALL)
        task.read_gold_total = Mock(side_effect=[100, 100])
        task.loop = Mock(return_value=iter(range(2)))
        with patch.object(local_shop, 'Timer') as timer:
            timer.return_value.start.return_value.reached.return_value = True
            self.assertEqual(task.select_all(), 100)
        self.assertEqual(task.device.click.call_args_list, [call(local_shop.assets.LOCAL_SHOP_ALL)])
        task.read_gold_balance = Mock(return_value=99)
        task.select_all = Mock(return_value=100)
        self.assertFalse(task.buy_local_stock(local_shop.week_reset()))
        self.assertEqual(task.device.click.call_args_list, [call(local_shop.assets.LOCAL_SHOP_ALL)])

    @unittest.skipUnless(SOLD_OUT_SCREENSHOT, 'set RESONANCE_LOCAL_SHOP_SCREENSHOT to replay a sold-out shop')
    def test_sold_out_screenshot_records_the_city_without_purchase_or_amount_ocr(self):
        task = self.make_task()
        task.device.image = np.asarray(Image.open(SOLD_OUT_SCREENSHOT).convert('RGB'))
        task.get_current_city = Mock(return_value='修格里城')
        task.loop = Mock(return_value=iter((None,)))
        record = {'week': local_shop.week_reset().date().isoformat(),
                  'cities': [city for city in local_shop.CITIES if city != '修格里城']}
        with patch.object(local_shop, '_read_json_dict', return_value=record), \
                patch.object(local_shop, '_write_json_dict') as save, \
                patch.object(local_shop.BALANCE, 'ocr') as balance, \
                patch.object(local_shop.TOTAL, 'ocr') as total, \
                patch.object(local_shop.assets.TEMPLATE_LOCAL_SHOP_GOLD, 'match_multi') as gold, \
                patch.object(local_shop, 'Timer') as timer:
            timer.return_value.start.return_value.reached.return_value = True
            task.run()
        save.assert_called_once()
        self.assertEqual(save.call_args[0][0]['cities'], sorted(local_shop.CITIES))
        task.device.click.assert_not_called()
        task.ui_goto_main.assert_called_once()
        task.config.task_delay.assert_called_once()
        balance.assert_not_called()
        total.assert_not_called()
        gold.assert_not_called()

    def test_trade_plan_compares_total_profit_across_stops(self):
        first = {'profit': 90}
        later = {'profit': 120}
        matrix = {'A': {'B': {0: first}, 'C': {0: later}}, 'B': {'C': {0: {'profit': 50}}}}
        self.assertEqual(local_shop.plan_sweep_trade(('A', 'B', 'C'), matrix), ('B', first))
        matrix['B']['C'][0]['profit'] = 20
        self.assertEqual(local_shop.plan_sweep_trade(('A', 'B', 'C'), matrix), ('C', later))
        self.assertIsNone(local_shop.plan_sweep_trade(('A', 'C'), {'A': {'C': {0: {'profit': -1}, 1: later}}}))

    def test_zero_book_load_survives_intermediate_stop_and_resumes_at_its_sale_city(self):
        task = self.make_task()
        a, b, c = '贡露城', '曼德矿场', '修格里城'
        record = {'week': local_shop.week_reset().date().isoformat(),
                  'cities': list(set(local_shop.CITIES) - {a, b, c})}
        task.get_current_city = Mock(side_effect=[a, b, b, c])
        task._open_profile_drawer = Mock()
        task._close_profile_drawer = Mock()
        task._read_drawer_bars = Mock(return_value=((0, 912), 400))
        task.travel_to = Mock()
        task.buy_local_stock = Mock(side_effect=[True, False, True, True])
        task.enter_exchange = Mock()
        task.read_cargo = Mock(side_effect=[(0, 0, 400), (300, 0, 400), (380, 0, 400)])
        task.ensure_profile = Mock(return_value={'prestige': {}, 'roles': {}})
        leg = {'profit': 120, 'restock': 0}
        top_up = {'profit': 60, 'restock': 0}
        task.buy_plan = Mock(return_value=True)
        task.sell_all = Mock(side_effect=lambda **kwargs: kwargs['approve'](None))

        def save(state, _path):
            record.update(deepcopy(state))
            if 'cargo' not in state:
                record.pop('cargo', None)

        with patch.object(local_shop, '_read_json_dict', side_effect=lambda _: deepcopy(record)), \
                patch.object(local_shop, '_write_json_dict', side_effect=save), \
                patch.object(local_shop, 'fetch_prices'), \
                patch.object(local_shop, 'calc_direction_matrix',
                             return_value={a: {c: {0: leg}}, b: {c: {0: top_up}}}) as calculate, \
                patch.object(local_shop, 'read_sell_profit', return_value=120), \
                patch.object(local_shop, 'record_trade_profit') as profit:
            task.run()
            task.sell_all.assert_not_called()
            self.assertEqual(record['cargo'], {'bought_city': a, 'target_city': c, 'restock_used': 0})
            task.run()
            profit.assert_called_once_with('local-shop-test', 120, from_city=a, to_city=c, restock_used=0)
        self.assertEqual([args[0][1]['maxLot'] for args in calculate.call_args_list], [400, 100])
        self.assertTrue(all(args[1]['max_restock'] == 0 for args in calculate.call_args_list))
        self.assertEqual(task.buy_plan.call_args_list, [
            call(leg, restock_books=0, bargain_target=0), call(top_up, restock_books=0, bargain_target=0),
        ])
        self.assertEqual(task.travel_to.call_args_list, [call(b), call(c)])
        self.assertNotIn('cargo', record)

    def test_sweep_sale_keeps_legacy_restock_usage_unknown(self):
        task = self.make_task()
        task.enter_exchange = Mock()
        task.read_cargo = Mock(return_value=(300, 0, 400))
        task.ensure_max_mode = Mock()
        task.interval_timer = {}
        task.appear = Mock(return_value=True)
        task.loop = Mock(return_value=iter((None,)))
        task.wait_until_still = Mock(return_value=True)
        task.appear_then_click = Mock(return_value=True)
        task.wait_until_disappear = Mock(return_value=True)
        task._confirm_and_dismiss_report = Mock()
        task.sell_all = Mock(side_effect=lambda **kwargs: kwargs['approve'](None))
        state = {'cargo': {'bought_city': '贡露城', 'target_city': '修格里城'}}
        with patch.object(local_shop, 'read_sell_profit', return_value=120), \
                patch.object(local_shop, '_write_json_dict') as save, \
                patch.object(local_shop, 'record_trade_profit') as profit:
            self.assertTrue(task.sell_sweep_cargo('修格里城', state, 'unused'))
        profit.assert_called_once_with(
            'local-shop-test', 120, from_city='贡露城', to_city='修格里城', restock_used=None,
        )
        self.assertNotIn('cargo', state)
        save.assert_called_once()

    def test_negative_profit_cancels_staged_sale_and_keeps_checkpoint(self):
        task = self.make_task()
        task.enter_exchange = Mock()
        task.read_cargo = Mock(return_value=(300, 0, 400))
        task.ensure_max_mode = Mock()
        task.interval_timer = {}
        task.appear = Mock(return_value=True)
        task.loop = Mock(return_value=iter((None,)))
        task.wait_until_still = Mock(return_value=True)
        task.appear_then_click = Mock(return_value=True)
        task.wait_until_disappear = Mock(return_value=True)
        task._confirm_and_dismiss_report = Mock()
        record = {'cargo': {'bought_city': '贡露城', 'target_city': '修格里城'}}
        with patch.object(local_shop, 'read_sell_profit', return_value=-15), \
                patch.object(local_shop, '_write_json_dict') as save:
            self.assertFalse(task.sell_sweep_cargo('修格里城', record, 'unused'))
        self.assertIn('cargo', record)
        save.assert_not_called()
        task._confirm_and_dismiss_report.assert_not_called()
        task.appear_then_click.assert_called_once_with(local_shop.assets.TRADE_CANCEL_ALL, offset=(5, 5), interval=2)

    def test_regular_trading_waits_while_sweep_cargo_has_a_destination(self):
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance import smart_state

        task = ResonanceCaravan.__new__(ResonanceCaravan)
        task.config = Mock(config_name='local-shop-test')
        task.config.cross_get.return_value = True
        task.ui_ensure = Mock()
        with patch.object(smart_state, '_read_json_dict', return_value={'cargo': {'target_city': '修格里城'}}):
            task.run()
        task.ui_ensure.assert_not_called()
        task.config.task_delay.assert_called_once_with(minute=15)
