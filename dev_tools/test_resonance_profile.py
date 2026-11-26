import os
import tempfile
import unittest
from itertools import count
from unittest.mock import Mock, patch

import numpy as np

from module.base.utils import load_image
from module.config import server


class TestResonanceProfile(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def test_prestige_thresholds_and_city_matching(self):
        from module.resonance.profile import match_prestige_city, prestige_points_to_level

        cases = (
            (0, 1), (499, 1), (500, 1), (999, 1), (1000, 2),
            (2500, 5), (3499, 5), (3500, 6), (7500, 10),
            (9000, 11), (15000, 15), (17000, 16), (21574, 18), (23000, 19), (25000, 20), (143654, 20),
        )
        for pts, expected_lv in cases:
            self.assertEqual(prestige_points_to_level(pts), expected_lv, msg='pts=%d' % pts)

        ocr_cases = (
            ('修格里坡', '修格里城'),
            ('7号自由港', '七号自由港'),
            ('曼德矿场', '曼德矿场'),
            ('贡露坡', '贡露城'),
            ('海角坡', '海角城'),
            ('塔图站', '塔图站'),
            ('明数据中心', '澄明数据中心'),
            ('妮塔发射中心', '阿妮塔发射中心'),
            ('铁山啵', '铁山城'),
            ('岚心坡', '岚心城'),
            ('雪金坡', '雪金城'),
            ('式林源', '武林源'),
        )
        for raw, expected in ocr_cases:
            self.assertEqual(match_prestige_city(raw), expected, msg='raw=%r' % raw)

    def test_crew_role_matching_protects_alters(self):
        from module.resonance.columba import load_columba_data
        from module.resonance.profile import match_crew_role

        known = set(load_columba_data()['resonance_skills'].keys())
        self.assertIsNone(match_crew_role('卡塔斯·业火', known))
        self.assertIsNone(match_crew_role('卡塔斯业火', known))
        self.assertIsNone(match_crew_role('夏洛蒂·澄心', known))
        self.assertEqual(match_crew_role('马吉拉星仪', known), '马吉拉·星仪')
        self.assertEqual(match_crew_role('卡洛淋_l', known), '卡洛琳')
        self.assertEqual(match_crew_role('真唉_」', known), '真咲')
        self.assertEqual(match_crew_role('伊卡拉」', known), '伊卡菈')
        self.assertEqual(match_crew_role('那由他', known), '那由他')
        self.assertIsNone(match_crew_role('圣剑波克士', known))
        self.assertIsNone(match_crew_role('伽罗尔', known))
        self.assertIsNone(match_crew_role('柯娜', known))
        self.assertEqual(match_crew_role('狮鬓', known), '狮鬃')
        self.assertEqual(match_crew_role('乌刹', known), '乌刹娜')
        self.assertEqual(match_crew_role('罗洁尔定格', known), '罗洁尔·定格')
        self.assertEqual(match_crew_role('静流逐夏', known), '静流·逐夏')
        self.assertEqual(match_crew_role('冯里奈', known), '冯·里奈')
        self.assertEqual(match_crew_role('蓝鹊儿', known), '蓝鹊儿')

    def test_classify_crew_resonance_templates_0_to_5(self):
        from module.resonance import assets
        from module.resonance.profile import _crew_x0, classify_crew_resonance

        for expected in range(6):
            tmpl = getattr(assets, 'TEMPLATE_CREW_RES_%d' % expected).image
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            x0 = _crew_x0(col=2)
            y0 = 150
            frame[y0:y0 + 39, x0 + 134:x0 + 162] = tmpl
            self.assertEqual(classify_crew_resonance(frame, x0, y0), expected, msg='digit=%d' % expected)

    def test_fatigue_item_plan_and_recovery_minutes(self):
        from module.resonance.fatigue import (
            choose_fatigue_item_plan, compute_fatigue_recovery_minutes,
        )

        items = [
            {'key': 'lollipop', 'recover': 60, 'owned': 8},
            {'key': 'gum', 'recover': 100, 'owned': 89},
            {'key': 'cactus', 'recover': 900, 'owned': 0},
        ]
        # Prefer lollipop first, avoid wasting past 0 when 2 lollipops cover shortfall
        self.assertEqual(choose_fatigue_item_plan(150, 95, items), ('lollipop', 2))
        self.assertEqual(choose_fatigue_item_plan(90, 95, items), ('lollipop', 1))

        # Fall back to gum when lollipop owned == 0
        no_lolli = [{'key': 'lollipop', 'recover': 60, 'owned': 0}] + items[1:]
        self.assertEqual(choose_fatigue_item_plan(220, 150, no_lolli), ('gum', 2))

        # Empty consumables -> None (never spend premium currency)
        empty = [{'key': 'lollipop', 'recover': 60, 'owned': 0}]
        self.assertIsNone(choose_fatigue_item_plan(200, 100, empty))

        # 6 min per missing fatigue point + 2 min buffer
        self.assertEqual(compute_fatigue_recovery_minutes(800, 912, 100), 0)
        self.assertEqual(compute_fatigue_recovery_minutes(890, 912, 30), 8 * 6 + 2)

    def test_fatigue_tiers_bento_first_and_rest_area_soda(self):
        from datetime import datetime
        from module.resonance import assets
        from module.resonance.columba import load_columba_data
        from module.resonance.fatigue import (
            FATIGUE_ITEM_TIERS, SKIP_NO_PROMPT_INNER, ResonanceFatigue, choose_fatigue_item_plan,
            is_rest_area_done_today, mark_rest_area_done, nearest_rest_area_city, normalize_fatigue_item_mode,
            server_day_key,
        )

        self.assertEqual(normalize_fatigue_item_mode(False), 'none')
        self.assertEqual(normalize_fatigue_item_mode(True), 'all')
        self.assertEqual(normalize_fatigue_item_mode('lollipop_gum'), 'lollipop_gum')
        self.assertEqual(normalize_fatigue_item_mode('invalid'), 'none')

        items_gum_cactus = [
            {'key': 'lollipop', 'recover': 60, 'owned': 0},
            {'key': 'gum', 'recover': 100, 'owned': 5},
            {'key': 'cactus', 'recover': 900, 'owned': 2},
        ]
        self.assertIsNone(choose_fatigue_item_plan(200, 120, items_gum_cactus, FATIGUE_ITEM_TIERS['lollipop']))
        self.assertEqual(choose_fatigue_item_plan(200, 120, items_gum_cactus, FATIGUE_ITEM_TIERS['lollipop_gum']), ('gum', 2))
        self.assertEqual(choose_fatigue_item_plan(800, 500, items_gum_cactus[:1] + items_gum_cactus[2:], FATIGUE_ITEM_TIERS['all']), ('cactus', 1))

        # 05:00 server reset boundary & daily persistence
        self.assertEqual(server_day_key(datetime(2026, 11, 25, 4, 59)), '2026-11-24')
        self.assertEqual(server_day_key(datetime(2026, 11, 25, 5, 0)), '2026-11-25')
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, 'daily.json')
            self.assertFalse(is_rest_area_done_today(state_path, now=datetime(2026, 11, 25, 21, 0)))
            mark_rest_area_done(state_path, now=datetime(2026, 11, 25, 21, 0))
            self.assertTrue(is_rest_area_done_today(state_path, now=datetime(2026, 11, 26, 4, 59)))
            self.assertFalse(is_rest_area_done_today(state_path, now=datetime(2026, 11, 26, 5, 1)))

        data = load_columba_data()
        rest_city, dist_f = nearest_rest_area_city('阿妮塔战备工厂', {}, data)
        self.assertEqual(rest_city, '七号自由港')
        self.assertGreater(dist_f, 0)
        self.assertEqual(nearest_rest_area_city('修格里城', {}, data), ('修格里城', 0))

        # Bento first avoids spending lollipop/gum when bento alone closes the shortfall
        fat = ResonanceFatigue.__new__(ResonanceFatigue)
        fat.device = Mock()
        fat.interval_timer = {}
        fat.ui_ensure = Mock()
        bento_ready = load_image(assets.BENTO_CHECK.file) + load_image(assets.BENTO_USE_ALL.file)
        bento_done = load_image(assets.BENTO_CHECK.file)
        fat.device.image = bento_ready
        fat.read_bento_fatigue = Mock(side_effect=[(880, 912), (880, 912), (808, 912)])
        b_frames = iter([bento_ready, bento_done])
        fat.device.screenshot.side_effect = lambda: setattr(fat.device, 'image', next(b_frames))
        with patch('module.base.timer.time', side_effect=count(100, 1.0)):
            self.assertTrue(fat.recover_fatigue(880, 912, 80, item_mode='none', use_bento=True))
        self.assertEqual(fat.device.click.call_args_list, [unittest.mock.call(assets.BENTO_USE_ALL)])

        # Bento confirmation modal (with shifted centered text) -> confirmed via GARBAGE_CONFIRM_OK, and ui_additional cancels safely
        bento_confirm = np.zeros((720, 1280, 3), dtype=np.uint8)
        bx1, by1, bx2, by2 = assets.BENTO_CONFIRM_MODAL.area
        bento_confirm[by1:by2, bx1 - 20:bx2 - 20] = load_image(
            assets.BENTO_CONFIRM_MODAL.file, assets.BENTO_CONFIRM_MODAL.area,
        )
        okx1, oky1, okx2, oky2 = assets.GARBAGE_CONFIRM_OK.area
        bento_confirm[oky1:oky2, okx1:okx2] = load_image(
            assets.GARBAGE_CONFIRM_OK.file, assets.GARBAGE_CONFIRM_OK.area,
        )
        fat_c = ResonanceFatigue.__new__(ResonanceFatigue)
        fat_c.device = Mock()
        fat_c.interval_timer = {}
        fat_c.ui_ensure = Mock()
        fat_c.device.image = bento_ready
        fat_c.read_bento_fatigue = Mock(side_effect=[(880, 912), (880, 912), (682, 912)])
        bc_frames = iter([bento_ready, bento_confirm, bento_done])
        fat_c.device.screenshot.side_effect = lambda: setattr(fat_c.device, 'image', next(bc_frames))
        with patch('module.base.timer.time', side_effect=count(100, 2.0)):
            self.assertTrue(fat_c.recover_fatigue(880, 912, 80, item_mode='none', use_bento=True))
        self.assertEqual(
            fat_c.device.click.call_args_list,
            [unittest.mock.call(assets.BENTO_USE_ALL), unittest.mock.call(assets.GARBAGE_CONFIRM_OK)],
        )

        stray_ui = ResonanceFatigue.__new__(ResonanceFatigue)
        stray_ui.device = Mock()
        stray_ui.interval_timer = {}
        stray_ui.device.image = bento_confirm
        self.assertTrue(stray_ui.ui_additional())
        self.assertEqual(stray_ui.device.click.call_args_list, [unittest.mock.call(assets.BENTO_CONFIRM_MODAL)])

        err_shot = 'log/error/1795677579642/2026-11-26_15-19-39-605164.png'
        if os.path.exists(err_shot):
            im = load_image(err_shot)
            self.assertTrue(assets.BENTO_CONFIRM_MODAL.match(im, offset=(60, 10)))
            self.assertTrue(assets.GARBAGE_CONFIRM_OK.match(im, offset=(5, 5)))

        # Rest area drink flow: buy -> SKIP -> skip modal (ticks checkbox + confirm) -> fatigue -50 -> exhausted
        drink_page = load_image(assets.REST_AREA_DRINK_BUY.file)
        skip_page = load_image(assets.REST_AREA_SKIP.file)
        modal_unchecked = load_image(assets.REST_AREA_SKIP_MODAL.file) + load_image(assets.REST_AREA_SKIP_CONFIRM.file)
        modal_checked = modal_unchecked.copy()
        x1, y1, x2, y2 = SKIP_NO_PROMPT_INNER
        modal_checked[y1 + 2:y2 - 2, x1 + 2:x2 - 2] = (240, 240, 240)

        rest = ResonanceFatigue.__new__(ResonanceFatigue)
        rest.device = Mock()
        rest.interval_timer = {}
        rest.ui_ensure = Mock()
        rest.ui_goto_main = Mock()
        rest.device.image = drink_page
        # 1st drink drops 350 -> 300; 2nd drink fails after 2 clicks with no drop/cutscene -> stops cleanly
        rest.read_rest_drink_fatigue = Mock(side_effect=[
            (350, 912), (350, 912), (300, 912),
            (300, 912), (300, 912), (300, 912), (300, 912), (300, 912),
        ])
        r_frames = iter([
            drink_page, skip_page, modal_unchecked, modal_checked, drink_page,
            drink_page, drink_page, drink_page, drink_page, drink_page,
        ])
        rest.device.screenshot.side_effect = lambda: setattr(rest.device, 'image', next(r_frames))
        with patch('module.base.timer.time', side_effect=count(100, 1.0)):
            drinks, exhausted, latest = rest.drink_rest_area_soda(max_drinks=6)
        self.assertEqual(drinks, 1)
        self.assertTrue(exhausted)
        self.assertEqual(latest, (300, 912))
        clicked_names = [
            getattr(c[0][0], 'name', str(c[0][0])) for c in rest.device.click.call_args_list
        ]
        self.assertEqual(clicked_names, [
            'REST_AREA_DRINK_BUY', 'REST_AREA_SKIP', 'REST_AREA_SKIP_NO_PROMPT',
            'REST_AREA_SKIP_CONFIRM', 'REST_AREA_DRINK_BUY', 'REST_AREA_DRINK_BUY',
        ])

        # Buff overwrite confirm dialog ("再喝一杯") flow + real screenshot check
        again_modal = load_image(assets.REST_AREA_DRINK_AGAIN.file)
        rest2 = ResonanceFatigue.__new__(ResonanceFatigue)
        rest2.device = Mock()
        rest2.interval_timer = {}
        rest2.ui_ensure = Mock()
        rest2.ui_goto_main = Mock()
        rest2.device.image = drink_page
        rest2.read_rest_drink_fatigue = Mock(side_effect=[(340, 912), (340, 912), (290, 912)])
        r2_frames = iter([drink_page, again_modal, skip_page, drink_page])
        rest2.device.screenshot.side_effect = lambda: setattr(rest2.device, 'image', next(r2_frames))
        with patch('module.base.timer.time', side_effect=count(100, 1.0)):
            drinks2, exhausted2, latest2 = rest2.drink_rest_area_soda(max_drinks=1)
        self.assertEqual(drinks2, 1)
        self.assertFalse(exhausted2)
        self.assertEqual(latest2, (290, 912))
        self.assertEqual(
            [getattr(c[0][0], 'name', str(c[0][0])) for c in rest2.device.click.call_args_list],
            ['REST_AREA_DRINK_BUY', 'REST_AREA_DRINK_AGAIN', 'REST_AREA_SKIP'],
        )

        m_again = 'C:/Users/14494/Documents/MuMu共享文件夹/Screenshots/MuMu-20261126-084210-823.png'
        m_bar = 'C:/Users/14494/Documents/MuMu共享文件夹/Screenshots/MuMu-20261126-084229-879.png'
        if os.path.exists(m_again) and os.path.exists(m_bar):
            self.assertTrue(assets.REST_AREA_DRINK_AGAIN.match(load_image(m_again), offset=(5, 5)))
            self.assertFalse(assets.REST_AREA_DRINK_AGAIN.match(load_image(m_bar), offset=(5, 5)))

        from module.resonance.page import page_resonance_rest_area, page_resonance_rest_drink
        from module.resonance.resonance_ui import ResonanceUI
        rest_area_frame = load_image(assets.REST_AREA_DRINK_ENTRY.file)
        rest_open = ResonanceFatigue.__new__(ResonanceFatigue)
        rest_open.device = Mock()
        rest_open.interval_timer = {}
        rest_open.ui_ensure = Mock()
        rest_open.wait_until_still = Mock(return_value=True)
        rest_open.device.image = rest_area_frame
        open_frames = iter([rest_area_frame, rest_area_frame, drink_page])
        rest_open.device.screenshot.side_effect = lambda: setattr(rest_open.device, 'image', next(open_frames))
        with patch('module.base.timer.time', side_effect=count(100, 1.6)):
            rest_open._open_rest_drink()
        rest_open.ui_ensure.assert_called_once_with(page_resonance_rest_area, skip_first_screenshot=False)
        rest_open.wait_until_still.assert_called_once()
        self.assertIs(rest_open.ui_current, page_resonance_rest_drink)
        self.assertEqual(
            [c[0][0] for c in rest_open.device.click.call_args_list],
            [assets.REST_AREA_DRINK_ENTRY, assets.REST_AREA_DRINK_ENTRY],
        )

        ui = ResonanceUI.__new__(ResonanceUI)
        ui.device = Mock()
        ui.interval_timer = {}
        if os.path.exists(m_bar):
            bar_img = load_image(m_bar)
            self.assertFalse(assets.CITY_CHECK.match(bar_img, offset=(30, 30)))
            ui.device.image = bar_img
            self.assertIs(ui.ui_get_current_page(skip_first_screenshot=True), page_resonance_rest_drink)

        live_rest = (
            'C:/Users/14494/.gemini/antigravity/brain/'
            'd55a543a-0e07-40cd-8969-2f09462460b5/scratch/live_rest_check.png'
        )
        if os.path.exists(live_rest):
            rest_img = load_image(live_rest)
            self.assertFalse(assets.CITY_CHECK.match(rest_img, offset=(30, 30)))
            ui.device.image = rest_img
            self.assertIs(ui.ui_get_current_page(skip_first_screenshot=True), page_resonance_rest_area)

    def test_profile_persistence_and_wait_docked(self):
        from module.resonance import assets
        from module.resonance.profile import ResonanceProfile, load_profile, save_profile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'profile.json')
            sample = {'maxLot': 994, 'prestige': {'修格里城': 20}, 'roles': {'星花': {'resonance': 5}}}
            save_profile(sample, path=path)
            self.assertEqual(load_profile(path=path), sample)

        driving = load_image(assets.MAIN_CHECK.file)
        docked = load_image(assets.MAIN_CHECK.file) + load_image(assets.MAIN_VISIT_CITY.file)
        prof = ResonanceProfile.__new__(ResonanceProfile)
        prof.device = Mock()
        prof.device.image = driving
        prof.interval_timer = {}
        frames = iter([driving, docked, docked])
        prof.device.screenshot.side_effect = lambda: setattr(prof.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 0.6)):
            prof.wait_until_docked(timeout=30)
        self.assertTrue(prof.device.stuck_record_clear.called)

        driving_terminal = load_image(assets.MAIN_TERMINAL.file)
        docked_bright = load_image(assets.MAIN_TERMINAL.file) + load_image(assets.MAIN_VISIT_CITY.file)
        prof2 = ResonanceProfile.__new__(ResonanceProfile)
        prof2.device = Mock()
        prof2.device.image = driving_terminal
        prof2.interval_timer = {}
        frames2 = iter([driving_terminal, docked_bright, docked_bright])
        prof2.device.screenshot.side_effect = lambda: setattr(prof2.device, 'image', next(frames2))
        with patch('module.base.timer.time', side_effect=count(100, 0.6)):
            prof2.wait_until_docked(timeout=30)
        self.assertTrue(prof2.device.stuck_record_clear.called)
