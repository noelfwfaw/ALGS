import unittest
from itertools import count
from unittest.mock import Mock, call, patch

import numpy as np

from module.base.utils import load_image
from module.config import server


class TestResonanceTrade(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def test_city_page_takes_priority_over_main_check(self):
        from module.resonance import assets
        from module.resonance.page import page_main, page_resonance_city
        from module.resonance.resonance_ui import ResonanceUI

        city_and_main = load_image(assets.MAIN_CHECK.file) + load_image(assets.CITY_CHECK.file)
        main_only = load_image(assets.MAIN_CHECK.file)

        ui = ResonanceUI.__new__(ResonanceUI)
        ui.device = Mock()
        ui.interval_timer = {}
        ui.device.image = city_and_main
        self.assertIs(ui.ui_get_current_page(skip_first_screenshot=True), page_resonance_city)

        home_and_city = city_and_main + load_image(assets.DAILY_HOME.file)
        frames = iter([home_and_city, main_only])
        ui.device.screenshot.side_effect = lambda: setattr(ui.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 3)):
            ui.app_start()
        self.assertIs(ui.ui_current, page_main)
        self.assertEqual(ui.device.click.call_args_list, [call(assets.DAILY_HOME)])

    def test_parsers_and_target_splitting(self):
        from module.resonance.trade import (
            BARGAIN_PIP_XS, BARGAIN_PIP_Y, _make_card_button, count_bargain_pips_in_image, find_cyan_card_runs,
            match_buy_target, parse_cargo_text, parse_fatigue_text, parse_fraction_text, parse_pct_text,
            split_buy_targets,
        )

        self.assertEqual(match_buy_target('窑防热烧蚀材料', {'蜂窝防热烧蚀材料', '航天半导体'}), '蜂窝防热烧蚀材料')
        self.assertIsNone(match_buy_target('龙井茶', {'明前龙井'}))

        card_btn = _make_card_button('花呢上衣', 384, 496)
        self.assertGreaterEqual(card_btn.button[0], 650)
        self.assertLessEqual(card_btn.button[2], 830)

        self.assertEqual(parse_cargo_text('3/994'), (3, 0, 994))
        self.assertEqual(parse_cargo_text('108+226/994'), (108, 226, 994))
        self.assertEqual(parse_cargo_text('3-3/994'), (3, -3, 994))
        self.assertIsNone(parse_cargo_text(''))

        from module.resonance.trade import CARGO_OCR, ResonanceTrade
        t_cargo = ResonanceTrade.__new__(ResonanceTrade)
        t_cargo.device = Mock()
        t_cargo.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        with patch.object(CARGO_OCR, 'ocr', return_value=['108+226/994']):
            self.assertEqual(t_cargo.read_cargo(), (108, 226, 994))
            self.assertEqual(t_cargo.cargo_remaining(), 660)

        self.assertEqual(parse_fraction_text('8/912'), (8, 912))
        self.assertIsNone(parse_fraction_text('bad'))

        for raw, expected in (
            ('894/912', (894, 912)),
            ('894912', (894, 912)),
            ('902912', (902, 912)),
            ('907912', (907, 912)),
            ('864912', (864, 912)),
            ('45912', (45, 912)),
            ('8912', (8, 912)),
            ('0912', (0, 912)),
            ('451912', (451, 912)),
            ('8941912', (894, 912)),
            ('10201050', (1020, 1050)),
            ('102011050', (1020, 1050)),
            ('912', None),
            ('950912', None),
            ('9120', None),
            ('', None),
        ):
            self.assertEqual(parse_fatigue_text(raw), expected, msg=raw)
        self.assertEqual(parse_fatigue_text('894912', known_max=912), (894, 912))

        from module.resonance.trade import FATIGUE_OCR
        with patch.object(FATIGUE_OCR, 'ocr', side_effect=['8/912', '894912']):
            self.assertEqual(t_cargo.read_fatigue(), (8, 912))
            self.assertEqual(t_cargo._last_max_fatigue, 912)
            self.assertEqual(t_cargo.read_fatigue(), (894, 912))

        self.assertEqual(parse_pct_text('13.0%'), 13.0)
        self.assertEqual(parse_pct_text('0%'), 0.0)
        self.assertIsNone(parse_pct_text('13'))

        leg = {
            'restock': 2,
            'combinations': [
                {'name': '明前龙井', 'buy_lot': 9, 'available_lot': 9},
                {'name': '龙井茶', 'buy_lot': 30, 'available_lot': 30},
                {'name': '叫化童鸡', 'buy_lot': 104, 'available_lot': 120},
            ],
        }
        full, tail = split_buy_targets(leg)
        self.assertEqual(full, {'明前龙井', '龙井茶'})
        self.assertEqual(tail, '叫化童鸡')

        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        for x1, x2 in BARGAIN_PIP_XS[:5]:
            img[BARGAIN_PIP_Y[0]:BARGAIN_PIP_Y[1], x1:x2] = (195, 195, 195)
        for x1, x2 in BARGAIN_PIP_XS[5:]:
            img[BARGAIN_PIP_Y[0]:BARGAIN_PIP_Y[1], x1:x2] = (70, 75, 80)
        self.assertEqual(count_bargain_pips_in_image(img), 5)

        img[200:312, 484:494] = (30, 170, 210)
        img[400:430, 484:494] = (30, 170, 210)
        self.assertEqual(find_cyan_card_runs(img), [(200, 312)])

    def test_sell_all_skips_empty_and_executes_stocked_sale(self):
        from module.resonance import assets
        from module.resonance.trade import ResonanceTrade

        sell_base = load_image(assets.TRADE_SELL_CHECK.file)
        sell_all = sell_base + load_image(assets.TRADE_SELL_ALL.file)
        sell_stocked = sell_all.copy()
        sell_stocked[200:320, 484:494] = (230, 180, 40)
        sell_staged = sell_base + load_image(assets.TRADE_CANCEL_ALL.file) + load_image(assets.TRADE_RAISE.file) + load_image(assets.TRADE_SELL_CONFIRM.file)
        sell_blur = np.zeros((720, 1280, 3), dtype=np.uint8)
        sell_report = load_image(assets.TRADE_SELL_REPORT.file)

        # Empty cargo skips without clicking sell
        task = ResonanceTrade.__new__(ResonanceTrade)
        task.device = Mock()
        task.device.image = sell_all
        task.interval_timer = {}
        task.enter_exchange = Mock()
        task.ensure_max_mode = Mock()
        self.assertFalse(task.sell_all())
        task.device.click.assert_not_called()

        # Stocked cargo stages, raises once through blur, sells, and dismisses report
        task = ResonanceTrade.__new__(ResonanceTrade)
        task.device = Mock()
        task.device.image = sell_stocked
        task.interval_timer = {}
        task.enter_exchange = Mock()
        task.ensure_max_mode = Mock()
        task.read_sell_total = Mock(return_value=1500000)
        task.read_fatigue = Mock(return_value=(0, 912))
        task.count_bargain_pips = Mock(side_effect=[8, 7, 7])
        task.read_bargain_pct = Mock(side_effect=[0.0, 13.0, 13.0])

        frames = iter([sell_staged, sell_staged, sell_staged, sell_blur, sell_staged, sell_staged, sell_staged, sell_staged, sell_report, sell_all])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 0.6)):
            result = task.sell_all(raise_target=10)

        self.assertTrue(result)
        self.assertEqual(task.device.click.call_args_list, [
            call(assets.TRADE_SELL_ALL),
            call(assets.TRADE_RAISE),
            call(assets.TRADE_SELL_CONFIRM),
            call(assets.TRADE_SELL_REPORT),
        ])

        # Low-value cargo (< 300k) skips raising to avoid wasting fatigue
        task_low = ResonanceTrade.__new__(ResonanceTrade)
        task_low.device = Mock()
        task_low.device.image = sell_stocked
        task_low.interval_timer = {}
        task_low.enter_exchange = Mock()
        task_low.ensure_max_mode = Mock()
        task_low.read_sell_total = Mock(return_value=19166)
        frames_low = iter([sell_staged, sell_staged, sell_staged, sell_report, sell_all])
        task_low.device.screenshot.side_effect = lambda: setattr(task_low.device, 'image', next(frames_low))
        with patch('module.base.timer.time', side_effect=count(100, 0.6)):
            self.assertTrue(task_low.sell_all(raise_target=20))
        self.assertEqual(task_low.device.click.call_args_list, [
            call(assets.TRADE_SELL_ALL),
            call(assets.TRADE_SELL_CONFIRM),
            call(assets.TRADE_SELL_REPORT),
        ])

        # Local-only cargo fails to stage after 2 clicks -> skips safely without GameStuckError
        task_local = ResonanceTrade.__new__(ResonanceTrade)
        task_local.device = Mock()
        task_local.device.image = sell_stocked
        task_local.interval_timer = {}
        task_local.enter_exchange = Mock()
        task_local.ensure_max_mode = Mock()
        local_frames = iter([sell_stocked, sell_stocked, sell_stocked, sell_stocked])
        task_local.device.screenshot.side_effect = lambda: setattr(task_local.device, 'image', next(local_frames))
        with patch('module.base.timer.time', side_effect=count(100, 2.5)):
            self.assertFalse(task_local.sell_all(raise_target=20))

        # Race condition: after clicking SELL_ALL, left cargo empties before ripple clears off CANCEL_ALL
        sell_ripple_clear_cart = sell_base + load_image(assets.TRADE_SELL_CONFIRM.file)
        task_race = ResonanceTrade.__new__(ResonanceTrade)
        task_race.device = Mock()
        task_race.device.image = sell_stocked
        task_race.interval_timer = {}
        task_race.enter_exchange = Mock()
        task_race.ensure_max_mode = Mock()
        hub_frame = load_image(assets.TRADE_HUB_CHECK.file)
        race_frames = iter([sell_ripple_clear_cart, sell_staged, sell_staged, sell_staged, sell_report, hub_frame])
        task_race.device.screenshot.side_effect = lambda: setattr(task_race.device, 'image', next(race_frames))
        with patch('module.base.timer.time', side_effect=count(100, 0.5)):
            self.assertTrue(task_race.sell_all(raise_target=0))
        self.assertEqual(task_race.device.click.call_args_list, [
            call(assets.TRADE_SELL_ALL),
            call(assets.TRADE_SELL_CONFIRM),
            call(assets.TRADE_SELL_REPORT),
        ])

    def test_use_restock_books_sets_target_quantity_and_confirms(self):
        from module.resonance import assets
        from module.resonance.trade import RESTOCK_OWN_OCR, RESTOCK_QTY_OCR, ResonanceTrade

        buy_frame = load_image(assets.TRADE_BUY_CHECK.file) + load_image(assets.TRADE_USE_ITEM.file)
        items_frame = load_image(assets.TRADE_ITEMS_MODAL.file) + load_image(assets.TRADE_ITEM_RESTOCK_USE.file)
        restock_frame = (
            load_image(assets.TRADE_RESTOCK_MODAL.file)
            + load_image(assets.TRADE_RESTOCK_PLUS.file)
            + load_image(assets.TRADE_RESTOCK_CONFIRM.file)
            + load_image(assets.TRADE_RESTOCK_CANCEL.file)
        )

        task = ResonanceTrade.__new__(ResonanceTrade)
        task.device = Mock()
        task.device.image = buy_frame
        task.interval_timer = {}
        frames = iter([items_frame, restock_frame, restock_frame, buy_frame, buy_frame])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))

        with patch('module.base.timer.time', side_effect=count(100, 0.6)), \
                patch.object(RESTOCK_OWN_OCR, 'ocr', return_value='50'), \
                patch.object(RESTOCK_QTY_OCR, 'ocr', side_effect=['1/10', '2/10']):
            used = task.use_restock_books(2)

        self.assertEqual(used, 2)
        self.assertEqual(task.device.click.call_args_list, [
            call(assets.TRADE_USE_ITEM),
            call(assets.TRADE_ITEM_RESTOCK_USE),
            call(assets.TRADE_RESTOCK_PLUS),
            call(assets.TRADE_RESTOCK_CONFIRM),
        ])

        # Owned == 0 cancels safely without confirming
        task_zero = ResonanceTrade.__new__(ResonanceTrade)
        task_zero.device = Mock()
        task_zero.device.image = restock_frame
        task_zero.interval_timer = {}
        task_zero._open_restock_modal = Mock()
        zero_frames = iter([buy_frame])
        task_zero.device.screenshot.side_effect = lambda: setattr(task_zero.device, 'image', next(zero_frames))
        with patch('module.base.timer.time', side_effect=count(100, 0.6)), \
                patch.object(RESTOCK_OWN_OCR, 'ocr', return_value='0'):
            self.assertEqual(task_zero.use_restock_books(2), 0)
        self.assertEqual(task_zero.device.click.call_args_list, [call(assets.TRADE_RESTOCK_CANCEL)])

    def test_buy_plan_stages_full_items_before_tail_and_confirms(self):
        from module.resonance import assets
        from module.resonance.trade import ResonanceTrade

        buy_base = load_image(assets.TRADE_BUY_CHECK.file)
        buy_staged = buy_base + load_image(assets.TRADE_CANCEL_ALL.file) + load_image(assets.TRADE_BARGAIN.file) + load_image(assets.TRADE_BUY_CONFIRM.file)
        buy_report = load_image(assets.TRADE_BUY_REPORT.file)

        task = ResonanceTrade.__new__(ResonanceTrade)
        task.device = Mock()
        task.device.image = buy_staged
        task.interval_timer = {}
        task.enter_exchange = Mock()
        task.ensure_max_mode = Mock()
        task.use_restock_books = Mock(return_value=1)
        task.cargo_remaining = Mock(return_value=50)
        task.negotiate = Mock()

        staged_order = []
        task._select_buy_targets = Mock(side_effect=lambda names: staged_order.append(set(names)))
        frames = iter([buy_report, buy_base])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))

        leg = {
            'restock': 1,
            'combinations': [
                {'name': '明前龙井', 'buy_lot': 9, 'available_lot': 9},
                {'name': '叫化童鸡', 'buy_lot': 104, 'available_lot': 120},
            ],
        }
        with patch('module.base.timer.time', side_effect=count(100, 3)):
            result = task.buy_plan(leg, bargain_target=15)

        self.assertTrue(result)
        task.use_restock_books.assert_called_once_with(1)
        self.assertEqual(staged_order, [{'明前龙井'}, {'叫化童鸡'}])
        task.negotiate.assert_called_once_with(is_buy=True, target_pct=15, max_fatigue_ratio=0.95)
        self.assertEqual(task.device.click.call_args_list, [
            call(assets.TRADE_BUY_CONFIRM),
            call(assets.TRADE_BUY_REPORT),
        ])

    def test_settlement_report_dismiss_lands_on_trade_hub_and_handles_reward(self):
        from module.resonance import assets
        from module.resonance.page import page_resonance_trade_hub
        from module.resonance.trade import ResonanceTrade

        hub_frame = load_image(assets.TRADE_HUB_CHECK.file)
        reward_frame = load_image(assets.LOGIN_REWARD.file)

        # Sell settlement -> LOGIN_REWARD popup -> trade hub
        sell_base = load_image(assets.TRADE_SELL_CHECK.file)
        sell_stocked = (
            sell_base + load_image(assets.TRADE_SELL_ALL.file)
        )
        sell_stocked[200:320, 484:494] = (230, 180, 40)
        sell_staged = sell_base + load_image(assets.TRADE_CANCEL_ALL.file) + load_image(assets.TRADE_SELL_CONFIRM.file)
        sell_report = load_image(assets.TRADE_SELL_REPORT.file)

        task_sell = ResonanceTrade.__new__(ResonanceTrade)
        task_sell.device = Mock()
        task_sell.device.image = sell_stocked
        task_sell.interval_timer = {}
        task_sell.enter_exchange = Mock()
        task_sell.ensure_max_mode = Mock()
        sell_frames = iter([sell_staged, sell_staged, sell_staged, sell_report, reward_frame, hub_frame])
        task_sell.device.screenshot.side_effect = lambda: setattr(task_sell.device, 'image', next(sell_frames))
        with patch('module.base.timer.time', side_effect=count(100, 0.5)):
            self.assertTrue(task_sell.sell_all(raise_target=0))
        self.assertIs(task_sell.ui_current, page_resonance_trade_hub)
        self.assertEqual(task_sell.device.click.call_args_list, [
            call(assets.TRADE_SELL_ALL),
            call(assets.TRADE_SELL_CONFIRM),
            call(assets.TRADE_SELL_REPORT),
            call(assets.LOGIN_REWARD),
        ])

        # Buy settlement -> trade hub directly
        buy_base = load_image(assets.TRADE_BUY_CHECK.file)
        buy_staged = buy_base + load_image(assets.TRADE_CANCEL_ALL.file) + load_image(assets.TRADE_BUY_CONFIRM.file)
        buy_report = load_image(assets.TRADE_BUY_REPORT.file)

        task_buy = ResonanceTrade.__new__(ResonanceTrade)
        task_buy.device = Mock()
        task_buy.device.image = buy_staged
        task_buy.interval_timer = {}
        task_buy.enter_exchange = Mock()
        task_buy.ensure_max_mode = Mock()
        task_buy.cargo_remaining = Mock(return_value=50)
        task_buy._select_buy_targets = Mock()
        buy_frames = iter([buy_report, hub_frame])
        task_buy.device.screenshot.side_effect = lambda: setattr(task_buy.device, 'image', next(buy_frames))
        with patch('module.base.timer.time', side_effect=count(100, 3)):
            self.assertTrue(task_buy.buy_plan({'restock': 0, 'combinations': [{'name': '明前龙井', 'buy_lot': 5, 'available_lot': 10}]}))
        self.assertIs(task_buy.ui_current, page_resonance_trade_hub)
        self.assertEqual(task_buy.device.click.call_args_list, [
            call(assets.TRADE_BUY_CONFIRM),
            call(assets.TRADE_BUY_REPORT),
        ])

    def test_sell_all_waits_for_rolling_profit_animation_to_settle(self):
        from module.resonance import assets
        from module.resonance.trade import SELL_SUMMARY_AREA, ResonanceTrade

        sell_base = load_image(assets.TRADE_SELL_CHECK.file)
        sell_stocked = sell_base + load_image(assets.TRADE_SELL_ALL.file)
        sell_stocked[200:320, 484:494] = (230, 180, 40)
        staged = sell_base + load_image(assets.TRADE_CANCEL_ALL.file) + load_image(assets.TRADE_SELL_CONFIRM.file)
        x1, y1, x2, y2 = SELL_SUMMARY_AREA

        roll1 = staged.copy()
        roll1[y1:y2, x1:x2] = 60
        roll2 = staged.copy()
        roll2[y1:y2, x1:x2] = 120
        settled = staged.copy()
        settled[y1:y2, x1:x2] = 210
        sell_report = load_image(assets.TRADE_SELL_REPORT.file)

        task = ResonanceTrade.__new__(ResonanceTrade)
        task.device = Mock()
        task.device.image = sell_stocked
        task.interval_timer = {}
        task.enter_exchange = Mock()
        task.ensure_max_mode = Mock()
        frames = iter([roll1, roll2, settled, settled.copy(), sell_report, sell_stocked])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 0.3)):
            self.assertTrue(task.sell_all(raise_target=0))

        self.assertIsNotNone(task._last_sell_image)
        self.assertTrue(np.array_equal(task._last_sell_image[y1:y2, x1:x2], settled[y1:y2, x1:x2]))

    def test_negotiate_dismisses_fatigue_modal_and_stops_cleanly(self):
        from module.resonance import assets
        from module.resonance.trade import ResonanceTrade

        buy_staged = load_image(assets.TRADE_BUY_CHECK.file) + load_image(assets.TRADE_BARGAIN.file)
        fatigue_modal = load_image(assets.FATIGUE_MODAL_CHECK.file) + load_image(assets.OP_BACK.file)

        task = ResonanceTrade.__new__(ResonanceTrade)
        task.device = Mock()
        task.device.image = buy_staged
        task.interval_timer = {}
        task.count_bargain_pips = Mock(return_value=8)
        task.read_bargain_pct = Mock(return_value=0.0)
        task.read_fatigue = Mock(return_value=(850, 912))

        frames = iter([buy_staged, fatigue_modal, buy_staged])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 0.5)):
            task.negotiate(is_buy=True, target_pct=20)

        self.assertEqual(task.device.click.call_args_list, [
            call(assets.TRADE_BARGAIN),
            call(assets.OP_BACK),
        ])

    def test_negotiate_respects_reserve_fatigue_and_stops_on_unreadable_fatigue(self):
        from module.resonance import assets
        from module.resonance.trade import ResonanceTrade

        buy_staged = load_image(assets.TRADE_BUY_CHECK.file) + load_image(assets.TRADE_BARGAIN.file)

        # reserve_fatigue=100 at 802/912 leaves cap=812 -> 802 + 12 > 812 stops before clicking
        t_res = ResonanceTrade.__new__(ResonanceTrade)
        t_res.device = Mock()
        t_res.device.image = buy_staged
        t_res.interval_timer = {}
        t_res.count_bargain_pips = Mock(return_value=8)
        t_res.read_bargain_pct = Mock(return_value=0.0)
        t_res.read_fatigue = Mock(return_value=(802, 912))
        frames_res = iter([buy_staged])
        t_res.device.screenshot.side_effect = lambda: setattr(t_res.device, 'image', next(frames_res))
        with patch('module.base.timer.time', side_effect=count(100, 0.5)):
            t_res.negotiate(is_buy=True, target_pct=20, reserve_fatigue=100)
        t_res.device.click.assert_not_called()

        # Unreadable fatigue stops cleanly without clicking after 1 retry screenshot
        t_none = ResonanceTrade.__new__(ResonanceTrade)
        t_none.device = Mock()
        t_none.device.image = buy_staged
        t_none.interval_timer = {}
        t_none.count_bargain_pips = Mock(return_value=8)
        t_none.read_bargain_pct = Mock(return_value=0.0)
        t_none.read_fatigue = Mock(return_value=None)
        frames_none = iter([buy_staged, buy_staged])
        t_none.device.screenshot.side_effect = lambda: setattr(t_none.device, 'image', next(frames_none))
        with patch('module.base.timer.time', side_effect=count(100, 0.5)):
            t_none.negotiate(is_buy=True, target_pct=20)
        t_none.device.click.assert_not_called()

        # buy_plan forwards reserve_fatigue to negotiate when provided
        t_bp = ResonanceTrade.__new__(ResonanceTrade)
        t_bp.device = Mock()
        t_bp.device.image = buy_staged + load_image(assets.TRADE_CANCEL_ALL.file) + load_image(assets.TRADE_BUY_CONFIRM.file)
        t_bp.interval_timer = {}
        t_bp.enter_exchange = Mock()
        t_bp.ensure_max_mode = Mock()
        t_bp.cargo_remaining = Mock(return_value=50)
        t_bp._select_buy_targets = Mock()
        t_bp.negotiate = Mock()
        t_bp._confirm_and_dismiss_report = Mock()
        t_bp.buy_plan({'restock': 0, 'combinations': [{'name': '明前龙井', 'buy_lot': 9, 'available_lot': 9}]}, bargain_target=20, reserve_fatigue=98)
        t_bp.negotiate.assert_called_once_with(is_buy=True, target_pct=20, max_fatigue_ratio=0.95, reserve_fatigue=98)

        # sell_all defaults to max_fatigue_ratio=1.0 so reserved sell fatigue is usable up to 900/912, stopping at 902/912
        sell_base = load_image(assets.TRADE_SELL_CHECK.file)
        sell_stocked = sell_base + load_image(assets.TRADE_SELL_ALL.file)
        sell_stocked[200:320, 484:494] = (230, 180, 40)
        sell_staged = sell_base + load_image(assets.TRADE_CANCEL_ALL.file) + load_image(assets.TRADE_RAISE.file) + load_image(assets.TRADE_SELL_CONFIRM.file)
        sell_report = load_image(assets.TRADE_SELL_REPORT.file)

        t_sell = ResonanceTrade.__new__(ResonanceTrade)
        t_sell.device = Mock()
        t_sell.device.image = sell_stocked
        t_sell.interval_timer = {}
        t_sell.enter_exchange = Mock()
        t_sell.ensure_max_mode = Mock()
        t_sell.read_sell_total = Mock(return_value=1500000)
        t_sell.read_fatigue = Mock(side_effect=[(870, 912), (902, 912), (902, 912)])
        t_sell.count_bargain_pips = Mock(side_effect=[8, 8, 7, 7, 7])
        t_sell.read_bargain_pct = Mock(side_effect=[0.0, 11.0, 11.0])
        sell_frames = iter([sell_staged] * 9 + [sell_report, sell_stocked])
        t_sell.device.screenshot.side_effect = lambda: setattr(t_sell.device, 'image', next(sell_frames))
        with patch('module.base.timer.time', side_effect=count(100, 0.5)):
            self.assertTrue(t_sell.sell_all(raise_target=20))
        self.assertEqual(t_sell.device.click.call_args_list, [
            call(assets.TRADE_SELL_ALL),
            call(assets.TRADE_RAISE),
            call(assets.TRADE_SELL_CONFIRM),
            call(assets.TRADE_SELL_REPORT),
        ])
