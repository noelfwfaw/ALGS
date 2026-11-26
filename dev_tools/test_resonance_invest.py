import os
import unittest
from itertools import count
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import cv2
import numpy as np
from PIL import Image

from module.base.utils import load_image
from module.config import server


class TestResonanceInvest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def test_parse_level_and_real_screenshot_slots_if_present(self):
        from module.resonance import assets
        from module.resonance.invest import (
            ResonanceInvest, inspect_invest_slot, is_invest_slot_selected, parse_invest_level,
        )

        self.assertEqual(parse_invest_level('LV.O'), 0)
        self.assertEqual(parse_invest_level('V.14'), 14)
        self.assertEqual(parse_invest_level('LV.20'), 20)
        self.assertIsNone(parse_invest_level('LV.25'))
        self.assertIsNone(parse_invest_level(''))

        base = 'C:/Users/14494/Documents/MuMu共享文件夹/Screenshots/'
        f1 = base + 'MuMu-20261125-212543-636.png'
        f2 = base + 'MuMu-20261125-212629-131.png'
        if not (os.path.exists(f1) and os.path.exists(f2)):
            return

        i1 = np.array(Image.open(f1).convert('RGB'))
        i2 = np.array(Image.open(f2).convert('RGB'))
        lock_gray = cv2.cvtColor(assets.TEMPLATE_INVEST_LOCK.image, cv2.COLOR_RGB2GRAY)

        self.assertTrue(assets.INVEST_CHECK.match(i1, offset=(5, 5)))
        self.assertTrue(assets.INVEST_MAX.match(i1, offset=(5, 5)))
        self.assertTrue(assets.INVEST_CONFIRM.match(i1, offset=(5, 5)))
        self.assertTrue(is_invest_slot_selected(i1, 0, 0))
        self.assertFalse(is_invest_slot_selected(i1, 0, 1))

        grid1 = [[inspect_invest_slot(i1, r, c, lock_gray) for c in range(3)] for r in range(3)]
        self.assertEqual(grid1, [
            ['unlocked', 'locked', 'locked'],
            ['locked', 'locked', 'locked'],
            ['locked', 'locked', 'locked'],
        ])
        grid2 = [[inspect_invest_slot(i2, r, c, lock_gray) for c in range(3)] for r in range(3)]
        self.assertEqual(grid2, [
            ['unlocked', 'unlocked', 'locked'],
            ['locked', 'locked', 'locked'],
            ['locked', 'locked', 'empty'],
        ])

        inv = ResonanceInvest.__new__(ResonanceInvest)
        inv.device = Mock()
        inv.device.image = i1
        self.assertEqual(inv.read_invest_level(), 0)
        self.assertEqual(inv.read_invest_cost(), 18500)
        inv.device.image = i2
        self.assertEqual(inv.read_invest_level(), 14)
        self.assertEqual(inv.read_invest_cost(), 1901600)

    def test_invest_current_city_skips_lv20_and_clicks_max_confirm_without_budget_gate(self):
        from module.resonance import assets
        from module.resonance.invest import GRID_DX, GRID_DY, GRID_X0, GRID_Y0, ResonanceInvest
        from module.resonance.page import page_resonance_trade_hub, page_resonance_trade_invest

        base = load_image(assets.INVEST_CHECK.file) + load_image(assets.INVEST_MAX.file) + load_image(assets.INVEST_CONFIRM.file)
        lock = assets.TEMPLATE_INVEST_LOCK.image

        def make_frame(unlocked_count, sel_col):
            img = base.copy()
            # Paint yellow border on selected col in row 0
            sx = GRID_X0 + sel_col * GRID_DX
            img[GRID_Y0:GRID_Y0 + 7, sx + 10:sx + 100] = (240, 190, 20)
            for r in range(3):
                for c in range(3):
                    idx = r * 3 + c
                    x1 = GRID_X0 + c * GRID_DX
                    y1 = GRID_Y0 + r * GRID_DY
                    # Dark footer so not empty
                    img[y1 + 112:y1 + 122, x1 + 15:x1 + 95] = (15, 15, 15)
                    if idx >= unlocked_count:
                        img[y1 + 48:y1 + 48 + lock.shape[0], x1 + 41:x1 + 41 + lock.shape[1]] = lock
            return img

        f_s0 = make_frame(2, 0)
        f_s1 = make_frame(2, 1)
        f_s1_done = make_frame(3, 1)
        f_s2 = make_frame(3, 2)
        f_s2_done = make_frame(4, 2)

        inv = ResonanceInvest.__new__(ResonanceInvest)
        inv.device = Mock()
        inv.device.image = f_s0
        inv.interval_timer = {}
        inv.enter_exchange = Mock()
        inv.ui_ensure = Mock()
        inv.wait_until_still = Mock(return_value=True)
        inv.wait_until_disappear = Mock(return_value=False)
        inv.read_invest_level = Mock(side_effect=[20, 9, 20, 0, 5])
        frames = iter([f_s1, f_s1_done, f_s2, f_s2_done])
        inv.device.screenshot.side_effect = lambda: setattr(inv.device, 'image', next(frames))

        with patch('module.base.timer.time', side_effect=count(100, 1.0)):
            upgrades = inv.invest_current_city()

        # Stops once (0,2) finishes at LV.5 (< 20), without moving into Row 1 despite slot (1,0) being unlocked
        self.assertEqual(upgrades, 2)
        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in inv.device.click.call_args_list]
        self.assertEqual(clicked, [
            'INVEST_SLOT_0_1', 'INVEST_MAX', 'INVEST_CONFIRM',
            'INVEST_SLOT_0_2', 'INVEST_MAX', 'INVEST_CONFIRM',
        ])
        self.assertEqual(inv.enter_exchange.call_args_list, [call(page_resonance_trade_hub)])
        self.assertEqual(inv.ui_ensure.call_args_list, [
            call(page_resonance_trade_invest, skip_first_screenshot=True),
            call(page_resonance_trade_hub, skip_first_screenshot=True),
        ])

    def test_invest_zero_budget_or_no_money_does_not_hang_or_raise(self):
        from module.resonance import assets
        from module.resonance.invest import GRID_DX, GRID_DY, GRID_X0, GRID_Y0, ResonanceInvest
        from module.resonance.page import page_resonance_trade_hub, page_resonance_trade_invest

        base = load_image(assets.INVEST_CHECK.file) + load_image(assets.INVEST_MAX.file) + load_image(assets.INVEST_CONFIRM.file)
        lock = assets.TEMPLATE_INVEST_LOCK.image
        img = base.copy()
        img[GRID_Y0:GRID_Y0 + 7, GRID_X0 + 10:GRID_X0 + 100] = (240, 190, 20)
        for r in range(3):
            for c in range(3):
                x1 = GRID_X0 + c * GRID_DX
                y1 = GRID_Y0 + r * GRID_DY
                img[y1 + 112:y1 + 122, x1 + 15:x1 + 95] = (15, 15, 15)
                if r * 3 + c >= 2:
                    img[y1 + 48:y1 + 48 + lock.shape[0], x1 + 41:x1 + 41 + lock.shape[1]] = lock

        inv = ResonanceInvest.__new__(ResonanceInvest)
        inv.device = Mock()
        inv.device.image = img
        inv.interval_timer = {}
        inv.enter_exchange = Mock()
        inv.ui_ensure = Mock()
        inv.wait_until_still = Mock(return_value=True)
        inv.wait_until_disappear = Mock(return_value=False)
        # Level stays 3 even after MAX -> CONFIRM (no money / budget 0), stops immediately without moving to (0,1)
        inv.read_invest_level = Mock(return_value=3)

        with patch('module.base.timer.time', side_effect=count(100, 1.0)):
            upgrades = inv.invest_current_city()

        self.assertEqual(upgrades, 0)
        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in inv.device.click.call_args_list]
        self.assertEqual(clicked, ['INVEST_MAX', 'INVEST_CONFIRM'])
        self.assertEqual(inv.ui_ensure.call_args_list, [
            call(page_resonance_trade_invest, skip_first_screenshot=True),
            call(page_resonance_trade_hub, skip_first_screenshot=True),
        ])

    def test_dimmed_lv20_selected_slot_switches_to_next_commodity(self):
        from module.resonance import assets
        from module.resonance.invest import (
            GRID_DX, GRID_DY, GRID_X0, GRID_Y0, ResonanceInvest, inspect_invest_slot, is_invest_slot_selected,
        )

        lock_gray = cv2.cvtColor(assets.TEMPLATE_INVEST_LOCK.image, cv2.COLOR_RGB2GRAY)
        base = load_image(assets.INVEST_CHECK.file) + load_image(assets.INVEST_MAX.file) + load_image(assets.INVEST_CONFIRM.file)
        lock = assets.TEMPLATE_INVEST_LOCK.image

        def make_dimmed_lv20_frame(sel_col):
            img = base.copy()
            for r in range(3):
                for c in range(3):
                    x1 = GRID_X0 + c * GRID_DX
                    y1 = GRID_Y0 + r * GRID_DY
                    img[y1 + 112:y1 + 122, x1 + 15:x1 + 95] = (15, 15, 15)
                    if r * 3 + c >= 2:
                        img[y1 + 48:y1 + 48 + lock.shape[0], x1 + 41:x1 + 41 + lock.shape[1]] = lock
            # Dimmed LV.20 yellow border on slot (0,0) when sel_col == 0
            sx = GRID_X0 + sel_col * GRID_DX
            if sel_col == 0:
                img[GRID_Y0:GRID_Y0 + 7, sx + 10:sx + 100] = (155, 133, 76)
                img[GRID_Y0 + 112:GRID_Y0 + 122, sx + 15:sx + 95] = (163, 118, 7)
            else:
                img[GRID_Y0:GRID_Y0 + 7, sx + 10:sx + 100] = (230, 175, 15)
                img[GRID_Y0 + 112:GRID_Y0 + 122, sx + 15:sx + 95] = (233, 171, 9)
            return img

        f_lv20 = make_dimmed_lv20_frame(0)
        self.assertTrue(is_invest_slot_selected(f_lv20, 0, 0))
        self.assertEqual(inspect_invest_slot(f_lv20, 0, 0, lock_gray), 'unlocked')

        f_s1 = make_dimmed_lv20_frame(1)
        f_s1_done = make_dimmed_lv20_frame(1)

        inv = ResonanceInvest.__new__(ResonanceInvest)
        inv.device = Mock()
        inv.device.image = f_lv20
        inv.interval_timer = {}
        inv.enter_exchange = Mock()
        inv.ui_ensure = Mock()
        inv.wait_until_still = Mock(return_value=True)
        inv.wait_until_disappear = Mock(return_value=False)
        inv.read_invest_level = Mock(side_effect=[20, 0, 5])
        frames = iter([f_s1, f_s1_done])
        inv.device.screenshot.side_effect = lambda: setattr(inv.device, 'image', next(frames))

        with patch('module.base.timer.time', side_effect=count(100, 1.0)):
            upgrades = inv.invest_current_city()

        self.assertEqual(upgrades, 1)
        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in inv.device.click.call_args_list]
        self.assertEqual(clicked, ['INVEST_SLOT_0_1', 'INVEST_MAX', 'INVEST_CONFIRM'])

        # Real LV.20 screenshot check if present
        real_lv20 = (
            'C:/Users/14494/.gemini/antigravity/brain/'
            'd55a543a-0e07-40cd-8969-2f09462460b5/.user_uploaded/media_1795631021209_6957097c.jpg'
        )
        if os.path.exists(real_lv20):
            from module.resonance.invest import is_invest_panel_maxed

            img_real = cv2.resize(np.array(Image.open(real_lv20).convert('RGB')), (1280, 720))
            self.assertTrue(is_invest_slot_selected(img_real, 0, 0))
            self.assertTrue(is_invest_panel_maxed(img_real))
            self.assertEqual(inspect_invest_slot(img_real, 0, 0, lock_gray), 'unlocked')
            self.assertEqual(inspect_invest_slot(img_real, 0, 1, lock_gray), 'unlocked')
            self.assertEqual(inspect_invest_slot(img_real, 0, 2, lock_gray), 'locked')
            inv_real = ResonanceInvest.__new__(ResonanceInvest)
            inv_real.device = Mock()
            inv_real.device.image = img_real
            self.assertEqual(inv_real.read_invest_level(), 20)

    def test_select_invest_slot_rate_limit_and_error_screenshot(self):
        from module.resonance import assets
        from module.resonance.invest import ResonanceInvest, is_invest_panel_maxed, is_invest_slot_selected

        blank = load_image(assets.INVEST_CHECK.file)
        inv = ResonanceInvest.__new__(ResonanceInvest)
        inv.device = Mock()
        inv.device.image = blank
        inv.interval_timer = {}
        with patch('module.base.timer.time', side_effect=count(100, 0.9)):
            self.assertFalse(inv._select_invest_slot(1, 2))
        self.assertLessEqual(inv.device.click.call_count, 3)
        self.assertTrue(inv.device.click_record_clear.called)

        err_path = 'log/error/1795654178709/2026-11-26_08-49-38-648250.png'
        if os.path.exists(err_path):
            img_err = load_image(err_path)
            self.assertTrue(is_invest_slot_selected(img_err, 1, 2))
            self.assertFalse(is_invest_panel_maxed(img_err))
            for r in range(3):
                for c in range(3):
                    if (r, c) != (1, 2):
                        self.assertFalse(is_invest_slot_selected(img_err, r, c))

    def test_caravan_auto_invest_runs_once_per_arrival_when_enabled(self):
        from dev_tools.test_resonance_caravan import _sample_prices
        from module.resonance.caravan import ResonanceCaravan
        from module.resonance.columba import PRESTIGE_CITIES

        prices = _sample_prices()
        profile = {'maxLot': 994, 'prestige': {c: 20 for c in PRESTIGE_CITIES}, 'roles': {}}

        for auto_invest, expected_calls in ((True, 1), (False, 0)):
            caravan = ResonanceCaravan.__new__(ResonanceCaravan)
            caravan.device = Mock()
            caravan.config = SimpleNamespace(
                ResonanceTrade_SortBy='profit',
                ResonanceTrade_RoundTrip=False,
                ResonanceTrade_RestockBooks=0,
                ResonanceTrade_BargainPercent=0,
                ResonanceTrade_RaisePercent=0,
                ResonanceTrade_ReturnBargain=False,
                ResonanceTrade_AutoInvest=auto_invest,
                ResonanceTrade_UseRamming=False,
                ResonanceTrade_UseRestArea=False,
                ResonanceTrade_UseBento=False,
                ResonanceTrade_UseFatigueItem='none',
                ResonanceTrade_ExcludedCities='武林源',
                ResonanceTrade_RefreshProfile=False,
                task_delay=Mock(),
            )
            caravan.ui_ensure = Mock()
            caravan.wait_until_docked = Mock()
            caravan.ensure_profile = Mock(return_value=profile)
            caravan.get_current_city = Mock(return_value='阿妮塔发射中心')
            caravan.sell_all = Mock(return_value=False)
            caravan.invest_current_city = Mock(return_value=1)
            caravan._read_current_fatigue = Mock(return_value=(890, 912))
            caravan.ui_goto_main = Mock()

            with patch('module.resonance.caravan.load_trade_state', return_value={}), \
                    patch('module.resonance.caravan.clear_trade_state'), \
                    patch('module.resonance.caravan.fetch_prices', return_value=prices):
                caravan.run()

            self.assertEqual(caravan.invest_current_city.call_count, expected_calls)
