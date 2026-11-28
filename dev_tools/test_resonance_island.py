import os
import unittest
from itertools import count
from unittest.mock import Mock, call, patch

import numpy as np
from PIL import Image

from module.base.utils import load_image
from module.config import server


def _paste_button(canvas, button, dx=0, dy=0):
    x1, y1, x2, y2 = button.area
    canvas[y1 + dy:y2 + dy, x1 + dx:x2 + dx] = load_image(button.file, button.area)


def _blank_with(*buttons):
    canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
    for btn in buttons:
        _paste_button(canvas, btn)
    return canvas


def _make_promo_modal(method='flyer', with_full_toast=False):
    from module.resonance import assets
    from module.resonance.island import PROMO_METHOD_TABS

    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame[336:384, 400:880] = 28 if with_full_toast else (140, 165, 195)
    for btn in (
        assets.ISLAND_PROMO_MODAL,
        assets.ISLAND_PROMO_MAX,
        assets.ISLAND_PROMO_CONFIRM,
        assets.ISLAND_PROMO_CANCEL,
    ):
        _paste_button(frame, btn)
    x1, y1, x2, y2 = PROMO_METHOD_TABS[method]
    frame[y1:y2, x1:x2] = (248, 248, 248)
    return frame


def _make_char_select(locked_indices=(), lock_idx=0):
    from module.resonance import assets
    from module.resonance.island_volleyball import CHAR_CARD_RECTS

    frame = _blank_with(assets.VB_CHAR_SELECT)
    for idx in range(2):
        x1, y1, x2, y2 = CHAR_CARD_RECTS[idx]
        if idx in locked_indices:
            frame[y1:y2, x1:x2] = (150, 180, 232)
        else:
            frame[y1:y2, x1:x2] = (180, 120, 90)
    if lock_idx is not None:
        tpl = load_image(assets.TEMPLATE_VB_LOCK_CLICK.file)
        lx = 36 + lock_idx * 138
        frame[636:636 + tpl.shape[0], lx:lx + tpl.shape[1]] = tpl
    return frame


def _make_court_with_tile(x1=360, y1=320, x2=480, y2=400):
    from module.resonance import assets

    frame = _blank_with(assets.VB_COURT_EXIT)
    frame[y1:y2, x1:x2] = (80, 195, 240)
    return frame


def _make_timing_bar(fill_end_x):
    from module.resonance import assets

    frame = _blank_with(assets.VB_TIMING_MISS)
    frame[553:568, 280:fill_end_x + 1] = (110, 200, 242)
    return frame


def _make_friend_island(next_enabled=True, with_coin=False, with_monster=False):
    from module.resonance import assets

    frame = _blank_with(
        assets.ISLAND_FRIEND_CHECK,
        assets.ISLAND_FRIEND_CLEAN,
        assets.ISLAND_FRIEND_TAB_VISIT,
        assets.OP_BACK,
    )
    # Bright beach background in toast band so is_garbage_full_toast() stays False
    frame[336:384, 400:880] = (200, 195, 185)
    if next_enabled:
        frame[648:674, 1110:1215] = (210, 155, 180)
    else:
        frame[648:674, 1110:1215] = (182, 184, 190)
    if with_coin:
        frame[490:530, 720:765] = (190, 160, 25)
    if with_monster:
        frame[300:352, 600:645] = (240, 95, 95)
        frame[312:334, 616:622] = (250, 250, 250)
        frame[312:334, 626:632] = (250, 250, 250)
    return frame


def _new_island_task(
    recycle_at_wilderness=False,
    promo_type='promotion',
    promo_method='flyer',
    play_vb=True,
    collect_income=True,
    friend_fight=True,
    friend_arrest=False,
    friend_clean=True,
):
    from module.resonance.island import ResonanceIsland

    task = ResonanceIsland.__new__(ResonanceIsland)
    task.device = Mock()
    task.config = Mock()
    task.config.config_name = 'island_test'
    # Mock() would answer truthy on its own; the switch is read through
    # cross_get, so give it an explicit return value.
    task.config.cross_get = Mock(return_value=recycle_at_wilderness)
    task.config.ResonanceIsland_PromotionType = promo_type
    task.config.ResonanceIsland_PromotionMethod = promo_method
    task.config.ResonanceIsland_PlayVolleyball = play_vb
    task.config.ResonanceIsland_CollectIncome = collect_income
    task.config.ResonanceIsland_FriendFight = friend_fight
    task.config.ResonanceIsland_FriendArrest = friend_arrest
    task.config.ResonanceIsland_FriendClean = friend_clean
    task.interval_timer = {}
    task.ui_ensure = Mock()
    task.ui_goto_main = Mock()
    return task


class TestResonanceIsland(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def test_island_assets_and_vision_on_real_screenshots(self):
        from module.resonance import assets
        from module.resonance.island import (
            PROMO_TOURIST_OCR, find_sidebar_template, is_promo_method_selected, is_promo_park_full,
            is_promo_park_full_toast, read_beach_income, read_promo_stock, ISLAND_CARD_ROI, SIDEBAR_ROI,
        )
        from module.resonance.island_friends import (
            detect_friend_monsters, find_friend_list_clean_row, has_friend_clean_coin,
            has_friend_clean_cooldown, has_friend_list_clean_icon, has_friend_list_row,
            is_friend_list_row_current, is_friend_next_enabled, is_friend_sort_active,
            is_garbage_full_toast, read_friend_assist_remaining, read_friend_clean_remaining,
            read_friend_monster_count,
        )
        from module.resonance.island_volleyball import (
            detect_grid_blue_marker, detect_timing_bar_x, find_char_lock_button, is_char_card_locked,
            is_timing_bar_resolved, read_volleyball_attempts,
        )

        base = 'C:/Users/14494/Documents/MuMu共享文件夹/Screenshots/'
        files = {
            'main': base + 'MuMu-20261126-003348-355.png',
            'maint': base + 'MuMu-20261126-003413-156.png',
            'garb_full': base + 'MuMu-20261126-003416-334.png',
            'garb_modal': base + 'MuMu-20261126-003420-551.png',
            'garb_empty': base + 'MuMu-20261126-003423-454.png',
            'term_biz': base + 'MuMu-20261126-002220-410.png',
            'hub': base + 'MuMu-20261126-002234-209.png',
            'promo': base + 'MuMu-20261126-002602-366.png',
            'promo_modal': base + 'MuMu-20261126-002605-757.png',
            'promo_res': base + 'MuMu-20261126-002620-351.png',
            'vb_mode': base + 'MuMu-20261126-002639-038.png',
            'vb_sel0': base + 'MuMu-20261126-002751-012.png',
            'vb_sel1': base + 'MuMu-20261126-002757-532.png',
            'vb_grid1': base + 'MuMu-20261126-002717-992.png',
            'vb_grid2': base + 'MuMu-20261126-002720-844.png',
            'vb_bar_early': base + 'MuMu-20261126-002731-720.png',
            'vb_bar_late': base + 'MuMu-20261126-002732-566.png',
            'vb_good': base + 'MuMu-20261126-002715-918.png',
            'beach': base + 'MuMu-20261126-002852-667.png',
            'beach_empty': base + 'MuMu-20261126-002937-746.png',
            'revenue': base + 'MuMu-20261126-002859-769.png',
            'reward': base + 'MuMu-20261126-002904-664.png',
            'flist': base + 'MuMu-20261126-003107-388.png',
            'f_mon1': base + 'MuMu-20261126-003115-765.png',
            'f_mon2': base + 'MuMu-20261126-003123-330.png',
            'f_team': base + 'MuMu-20261126-003126-203.png',
            'f_win': base + 'MuMu-20261126-003217-124.png',
            'f_win_arrest': base + 'MuMu-20261126-122425-490.png',
            'arrest_modal_1': base + 'MuMu-20261126-122430-449.png',
            'arrest_modal_max': base + 'MuMu-20261126-122433-380.png',
            'arrest_anim': base + 'MuMu-20261126-122438-012.png',
            'arrest_result': base + 'MuMu-20261126-122444-696.png',
            'f_clean': base + 'MuMu-20261126-003321-308.png',
            'f_toast': base + 'MuMu-20261126-003332-657.png',
        }
        if not all(os.path.exists(p) for p in files.values()):
            return

        imgs = {k: np.array(Image.open(p).convert('RGB')) for k, p in files.items()}

        # Verify expected button matches & cross-screen uniqueness
        expected_hits = [
            (assets.MAIN_TRAIN_PREP, {'main'}),
            (assets.TRAIN_MAINT_CHECK, {'maint'}),
            (assets.TRAIN_CLEAN_CHECK, {'maint'}),
            (assets.TRAIN_GARBAGE_ENTRY, {'maint'}),
            (assets.GARBAGE_CHECK, {'garb_full', 'garb_empty'}),
            (assets.GARBAGE_CLEAR_ALL, {'garb_full'}),
            (assets.GARBAGE_CONFIRM_MODAL, {'garb_modal'}),
            (assets.GARBAGE_CONFIRM_OK, {'garb_modal'}),
            (assets.ISLAND_ENTRY_TAB, {'term_biz', 'hub'}),
            (assets.ISLAND_HUB_CHECK, {'hub'}),
            (assets.ISLAND_HUB_PROMO, {'hub'}),
            (assets.ISLAND_HUB_VOLLEYBALL, {'hub'}),
            (assets.ISLAND_HUB_ENTER, {'hub'}),
            (assets.ISLAND_PROMO_CHECK, {'promo'}),
            (assets.ISLAND_PROMO_MODAL, {'promo_modal'}),
            (assets.ISLAND_PROMO_MAX, {'promo_modal'}),
            (assets.ISLAND_PROMO_CONFIRM, {'promo_modal'}),
            (assets.ISLAND_PROMO_CANCEL, {'promo_modal'}),
            (assets.ISLAND_PROMO_RESULT, {'promo_res'}),
            (assets.ISLAND_PROMO_GO_REVENUE, {'promo_res'}),
            (assets.VB_MODE_MATCH, {'vb_mode'}),
            (assets.VB_CHAR_SELECT, {'vb_sel0', 'vb_sel1'}),
            (assets.VB_COURT_EXIT, {'vb_grid1', 'vb_grid2'}),
            (assets.VB_TIMING_MISS, {'vb_bar_early', 'vb_bar_late', 'vb_good'}),
            (assets.ISLAND_BEACH_CHECK, {'beach', 'beach_empty', 'flist'}),
            (assets.ISLAND_INCOME_ENTRY, {'beach', 'beach_empty'}),
            (assets.ISLAND_REVENUE_CHECK, {'revenue'}),
            (assets.ISLAND_REVENUE_COLLECT, {'revenue'}),
            (assets.ISLAND_FRIEND_TAB, {'beach', 'beach_empty'}),
            (assets.ISLAND_FRIEND_TAB_VISIT, {'f_mon1', 'f_mon2', 'f_clean'}),
            (assets.ISLAND_FRIEND_LIST, {'flist'}),
            (assets.ISLAND_FRIEND_SORT_CLEAN, {'flist'}),
            (assets.ISLAND_FRIEND_SORT_SEC, {'flist'}),
            (assets.ISLAND_FRIEND_VISIT_0, {'flist'}),
            (assets.ISLAND_FRIEND_CHECK, {'f_mon1', 'f_mon2', 'f_clean', 'f_toast'}),
            (assets.ISLAND_FRIEND_CLEAN, {'f_mon1', 'f_mon2', 'f_clean', 'f_toast'}),
            (assets.ISLAND_FRIEND_NEXT, {'f_mon1', 'f_mon2', 'f_clean', 'f_toast'}),
            (assets.OP_WIN_ARREST, {'f_win_arrest'}),
            (assets.ARREST_MODAL, {'arrest_modal_1', 'arrest_modal_max'}),
            (assets.ARREST_MAX, {'arrest_modal_1', 'arrest_modal_max'}),
            (assets.ARREST_CONFIRM, {'arrest_modal_1', 'arrest_modal_max'}),
            (assets.ARREST_CANCEL, {'arrest_modal_1', 'arrest_modal_max'}),
            (assets.ARREST_ANIM_SKIP, {'arrest_anim'}),
            (assets.ARREST_RESULT, {'arrest_result'}),
        ]
        for btn, owners in expected_hits:
            for key, img in imgs.items():
                matched = btn.match(img, offset=(5, 5))
                self.assertEqual(matched, key in owners, f'{btn.name} on {key}: expected {key in owners}')

        self.assertIsNotNone(find_sidebar_template(imgs['term_biz'], assets.TEMPLATE_TERMINAL_BIZ_TAB, SIDEBAR_ROI))
        self.assertIsNotNone(find_sidebar_template(imgs['term_biz'], assets.TEMPLATE_ISLAND_ENTRY_TAB, ISLAND_CARD_ROI))
        self.assertTrue(assets.TAP_BLANK_EXIT.match(imgs['vb_mode'], offset=(5, 5)))
        self.assertTrue(assets.LOGIN_REWARD.match(imgs['reward'], offset=(30, 140), similarity=0.78))
        self.assertTrue(assets.OP_TEAM.match(imgs['f_team'], offset=(5, 5)))
        for key, img in imgs.items():
            self.assertEqual(assets.OP_WIN.match(img, offset=(5, 5)), key in {'f_win', 'f_win_arrest'}, key)
        sim_full_prisoners = imgs['arrest_result'].copy()
        sim_full_prisoners[685:694, 65:385] = (60, 140, 245)
        self.assertTrue(assets.ARREST_RESULT.match(sim_full_prisoners, offset=(5, 5)))

        # Promotion vision & OCR
        self.assertTrue(is_promo_method_selected(imgs['promo_modal'], 'flyer'))
        self.assertFalse(is_promo_method_selected(imgs['promo_modal'], 'ad_ticket'))
        self.assertFalse(is_promo_park_full(imgs['promo']))
        self.assertFalse(is_promo_park_full_toast(imgs['promo']))
        self.assertFalse(is_promo_park_full_toast(imgs['promo_modal']))
        sim_full_bar = imgs['promo'].copy()
        sim_full_bar[47:51, 1126:1264] = 245
        self.assertEqual(PROMO_TOURIST_OCR.ocr(sim_full_bar), '90/360')
        self.assertEqual(read_promo_stock(imgs['promo'], 'flyer'), 500)
        self.assertEqual(read_promo_stock(imgs['promo'], 'ad_ticket'), 2203)
        self.assertGreater(read_beach_income(imgs['beach']), 0)
        self.assertEqual(read_beach_income(imgs['beach_empty']), 0)

        # Volleyball vision & OCR
        self.assertEqual(read_volleyball_attempts(imgs['vb_mode']), (2, 3))
        self.assertFalse(is_char_card_locked(imgs['vb_sel0'], 0))
        self.assertTrue(is_char_card_locked(imgs['vb_sel1'], 0))
        _, cx0 = find_char_lock_button(imgs['vb_sel0'])
        _, cx1 = find_char_lock_button(imgs['vb_sel1'])
        self.assertIsNotNone(cx0)
        self.assertIsNotNone(cx1)
        self.assertLess(cx0, 140)
        self.assertGreater(cx1, 140)
        self.assertIsNotNone(detect_grid_blue_marker(imgs['vb_grid1']))
        self.assertIsNotNone(detect_grid_blue_marker(imgs['vb_grid2']))
        self.assertLess(detect_timing_bar_x(imgs['vb_bar_early']), 350)
        self.assertGreater(detect_timing_bar_x(imgs['vb_bar_late']), 520)
        self.assertFalse(is_timing_bar_resolved(imgs['vb_bar_early']))
        self.assertTrue(is_timing_bar_resolved(imgs['vb_good']))

        # Friends vision & OCR
        self.assertEqual(read_friend_assist_remaining(imgs['f_mon1']), 5)
        self.assertEqual(read_friend_assist_remaining(imgs['f_clean']), 4)
        self.assertEqual(read_friend_clean_remaining(imgs['f_mon1']), 3)
        self.assertEqual(read_friend_monster_count(imgs['f_mon1']), 12)
        self.assertEqual(len(detect_friend_monsters(imgs['f_mon1'])), 5)
        self.assertEqual(len(detect_friend_monsters(imgs['f_mon2'])), 5)
        self.assertEqual(len(detect_friend_monsters(imgs['f_clean'])), 0)
        self.assertEqual(len(detect_friend_monsters(imgs['beach'])), 0)
        self.assertFalse(has_friend_clean_coin(imgs['f_mon1']))
        self.assertTrue(has_friend_clean_coin(imgs['f_clean']))
        self.assertFalse(has_friend_clean_cooldown(imgs['f_clean']))
        self.assertFalse(has_friend_clean_cooldown(imgs['f_mon1']))
        self.assertTrue(is_friend_next_enabled(imgs['f_mon1']))
        self.assertFalse(is_garbage_full_toast(imgs['f_clean']))
        self.assertTrue(is_garbage_full_toast(imgs['f_toast']))
        self.assertEqual([has_friend_list_clean_icon(imgs['flist'], r) for r in range(4)], [False, False, False, True])
        self.assertFalse(is_friend_sort_active(imgs['flist'], assets.ISLAND_FRIEND_SORT_CLEAN))
        self.assertEqual(find_friend_list_clean_row(imgs['flist']), 3)
        clean_path = base + 'MuMu-20261126-131806-690.png'
        if os.path.exists(clean_path):
            flist_clean = np.array(Image.open(clean_path).convert('RGB'))
            self.assertEqual([has_friend_list_row(flist_clean, r) for r in range(4)], [True, True, True, True])
            self.assertEqual([has_friend_list_clean_icon(flist_clean, r) for r in range(4)], [True, True, True, True])
            self.assertEqual([is_friend_list_row_current(flist_clean, r) for r in range(4)], [True, False, False, False])
            self.assertTrue(is_friend_sort_active(flist_clean, assets.ISLAND_FRIEND_SORT_CLEAN))
            self.assertEqual(find_friend_list_clean_row(flist_clean), 0)
            self.assertEqual(find_friend_list_clean_row(flist_clean, skip_current=True), 1)
        clean_res_path = base + 'MuMu-20261126-133440-910.png'
        if os.path.exists(clean_res_path):
            f_clean_res = np.array(Image.open(clean_res_path).convert('RGB'))
            self.assertTrue(assets.ISLAND_FRIEND_CLEAN_RESULT.match(f_clean_res, offset=(5, 5)))
            self.assertTrue(assets.TAP_BLANK_EXIT.match(f_clean_res, offset=(40, 100), similarity=0.80))
            self.assertLess(assets.TAP_BLANK_EXIT.button[3], 720)
            self.assertFalse(is_garbage_full_toast(f_clean_res))
        cooldown_path = base + 'MuMu-20261126-134711-707.png'
        if os.path.exists(cooldown_path):
            f_cd = np.array(Image.open(cooldown_path).convert('RGB'))
            self.assertTrue(assets.ISLAND_FRIEND_CHECK.match(f_cd, offset=(5, 5)))
            self.assertTrue(has_friend_clean_cooldown(f_cd))
        for key, img in imgs.items():
            self.assertFalse(assets.ISLAND_FRIEND_CLEAN_RESULT.match(img, offset=(5, 5)), key)

    def test_volleyball_timing_physics(self):
        from module.resonance.island_volleyball import should_trigger_timing_hit

        self.assertFalse(should_trigger_timing_hit(None, None, 0.05))
        self.assertFalse(should_trigger_timing_hit(350, 330, 0.08))
        # At 250 px/s, 535 + 250 * 0.12 = 565 -> trigger right before center
        self.assertTrue(should_trigger_timing_hit(535, 515, 0.08))
        self.assertTrue(should_trigger_timing_hit(522, None, 0.0))
        self.assertFalse(should_trigger_timing_hit(602, 585, 0.08))

    def test_page_graph_and_scheduler_registration(self):
        from module.config.config_manual import ManualConfig
        from module.resonance.assets import (
            DAILY_HOME, ISLAND_HUB_ENTER, ISLAND_HUB_PROMO, ISLAND_INCOME_ENTRY, MAIN_TRAIN_PREP, OP_BACK,
            TRAIN_GARBAGE_ENTRY,
        )
        from module.resonance.page import (
            page_main, page_resonance_garbage, page_resonance_island_beach, page_resonance_island_friend,
            page_resonance_island_hub, page_resonance_island_promo, page_resonance_island_revenue,
            page_resonance_train_maint,
        )
        from module.resonance.resonance_ui import ResonanceUI

        self.assertIs(page_main.links[page_resonance_train_maint], MAIN_TRAIN_PREP)
        self.assertIs(page_resonance_train_maint.links[page_resonance_garbage], TRAIN_GARBAGE_ENTRY)
        self.assertIs(page_resonance_garbage.links[page_main], DAILY_HOME)
        self.assertIs(page_resonance_island_hub.links[page_resonance_island_promo], ISLAND_HUB_PROMO)
        self.assertIs(page_resonance_island_hub.links[page_resonance_island_beach], ISLAND_HUB_ENTER)
        self.assertIs(page_resonance_island_promo.links[page_resonance_island_hub], OP_BACK)
        self.assertIs(page_resonance_island_beach.links[page_resonance_island_revenue], ISLAND_INCOME_ENTRY)
        self.assertIs(page_resonance_island_revenue.links[page_resonance_island_beach], OP_BACK)
        self.assertIs(page_resonance_island_friend.links[page_resonance_island_beach], OP_BACK)

        for p in (
            page_resonance_train_maint,
            page_resonance_garbage,
            page_resonance_island_hub,
            page_resonance_island_promo,
            page_resonance_island_beach,
            page_resonance_island_revenue,
            page_resonance_island_friend,
        ):
            self.assertIn(p, ResonanceUI.pages)
        self.assertIn('ResonanceIsland', ManualConfig.SCHEDULER_PRIORITY)

    def test_clean_train_garbage_full_and_empty(self):
        from module.resonance import assets

        garb_full = _blank_with(assets.GARBAGE_CHECK, assets.GARBAGE_CLEAR_ALL)
        garb_modal = _blank_with(assets.GARBAGE_CONFIRM_MODAL, assets.GARBAGE_CONFIRM_OK)
        garb_modal_shifted = _blank_with(assets.GARBAGE_CONFIRM_OK)
        _paste_button(garb_modal_shifted, assets.GARBAGE_CONFIRM_MODAL, dx=-25)
        garb_empty = _blank_with(assets.GARBAGE_CHECK)

        task = _new_island_task()
        task.device.image = garb_full
        frames = iter([garb_full, garb_modal, garb_empty, garb_empty, garb_empty, garb_empty])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 1.0)):
            task.clean_train_garbage()

        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in task.device.click.call_args_list]
        self.assertEqual(clicked, ['GARBAGE_CLEAR_ALL', 'GARBAGE_CONFIRM_OK'])

        # Shifted modal text (shorter coin cost) also confirms cleanly
        task_shift = _new_island_task()
        task_shift.device.image = garb_full
        frames_shift = iter([garb_modal_shifted, garb_empty, garb_empty, garb_empty, garb_empty])
        task_shift.device.screenshot.side_effect = lambda: setattr(task_shift.device, 'image', next(frames_shift))
        with patch('module.base.timer.time', side_effect=count(100, 1.0)):
            task_shift.clean_train_garbage()
        clicked_shift = [getattr(c[0][0], 'name', str(c[0][0])) for c in task_shift.device.click.call_args_list]
        self.assertEqual(clicked_shift, ['GARBAGE_CLEAR_ALL', 'GARBAGE_CONFIRM_OK'])

        # Already empty fast exit without clicks
        task2 = _new_island_task()
        task2.device.image = garb_empty
        frames2 = iter([garb_empty, garb_empty, garb_empty, garb_empty])
        task2.device.screenshot.side_effect = lambda: setattr(task2.device, 'image', next(frames2))
        with patch('module.base.timer.time', side_effect=count(100, 1.0)):
            task2.clean_train_garbage()
        task2.device.click.assert_not_called()

    def test_run_promotion_ad_ticket_max_and_skips(self):
        from module.resonance import assets

        hub = _blank_with(assets.ISLAND_HUB_CHECK, assets.ISLAND_HUB_VOLLEYBALL)
        promo = _blank_with(assets.ISLAND_PROMO_CHECK)
        modal_flyer = _make_promo_modal('flyer')
        modal_ad = _make_promo_modal('ad_ticket')
        result = _blank_with(assets.ISLAND_PROMO_RESULT, assets.ISLAND_PROMO_GO_REVENUE)

        task = _new_island_task(promo_type='theme', promo_method='ad_ticket')
        task.device.image = promo
        frames = iter([modal_flyer, modal_ad, modal_ad, result, promo])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))

        with patch('module.resonance.island.is_promo_park_full', return_value=False), \
             patch('module.resonance.island.read_promo_stock', return_value=120), \
             patch('module.base.timer.time', side_effect=count(100, 3.0)):
            task.run_promotion()

        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in task.device.click.call_args_list]
        self.assertEqual(
            clicked,
            ['PROMO_CARD_theme', 'PROMO_TAB_ad_ticket', 'ISLAND_PROMO_MAX', 'ISLAND_PROMO_CONFIRM', 'ISLAND_PROMO_RESULT'],
        )

        # Skip when park is full
        task2 = _new_island_task()
        task2.device.image = promo
        with patch('module.resonance.island.is_promo_park_full', return_value=True):
            task2.run_promotion()
        task2.device.click.assert_not_called()
        _ = hub

    def test_run_promotion_aborts_on_full_toast_and_confirm_stall(self):
        from module.resonance import assets

        promo = _blank_with(assets.ISLAND_PROMO_CHECK)
        modal_flyer = _make_promo_modal('flyer')
        modal_toast = _make_promo_modal('flyer', with_full_toast=True)

        # Case 1: 游客已满 toast inside modal cancels and exits back to hub
        task1 = _new_island_task(promo_type='promotion', promo_method='flyer')
        task1.device.image = promo
        frames1 = iter([modal_flyer, modal_flyer, modal_toast, promo])
        task1.device.screenshot.side_effect = lambda: setattr(task1.device, 'image', next(frames1))
        with patch('module.resonance.island.is_promo_park_full', return_value=False), \
             patch('module.resonance.island.read_promo_stock', return_value=120), \
             patch('module.resonance.island_friends.TOAST_OCR.ocr', return_value='游客已满!'), \
             patch('module.base.timer.time', side_effect=count(100, 3.0)):
            task1.run_promotion()

        clicked1 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task1.device.click.call_args_list]
        self.assertEqual(
            clicked1,
            ['PROMO_CARD_promotion', 'ISLAND_PROMO_MAX', 'ISLAND_PROMO_CONFIRM', 'ISLAND_PROMO_CANCEL'],
        )

        # Case 2: confirm stall fallback cancels after 2 unresponsive confirm clicks
        task2 = _new_island_task(promo_type='promotion', promo_method='flyer')
        task2.device.image = promo
        frames2 = iter([modal_flyer, modal_flyer, modal_flyer, modal_flyer, promo])
        task2.device.screenshot.side_effect = lambda: setattr(task2.device, 'image', next(frames2))
        with patch('module.resonance.island.is_promo_park_full', return_value=False), \
             patch('module.resonance.island.read_promo_stock', return_value=120), \
             patch('module.base.timer.time', side_effect=count(100, 3.0)):
            task2.run_promotion()

        clicked2 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task2.device.click.call_args_list]
        self.assertEqual(
            clicked2,
            [
                'PROMO_CARD_promotion',
                'ISLAND_PROMO_MAX',
                'ISLAND_PROMO_CONFIRM',
                'ISLAND_PROMO_CONFIRM',
                'ISLAND_PROMO_CANCEL',
            ],
        )

        # Case 3: entry frame not yet showing full -> post-settle re-check skips before opening modal
        task3 = _new_island_task(promo_type='promotion', promo_method='flyer')
        task3.device.image = promo
        task3.device.screenshot.side_effect = lambda: setattr(task3.device, 'image', promo)
        with patch('module.resonance.island.is_promo_park_full', side_effect=[False, True]), \
             patch('module.resonance.island.read_promo_stock', return_value=120), \
             patch('module.base.timer.time', side_effect=count(100, 3.0)):
            task3.run_promotion()

        task3.device.click.assert_not_called()

    def test_volleyball_full_match_and_interval_restore(self):
        from module.resonance import assets
        from module.resonance.island_volleyball import run_beach_volleyball

        hub = _blank_with(assets.ISLAND_HUB_CHECK, assets.ISLAND_HUB_VOLLEYBALL)
        vb_mode = _blank_with(assets.VB_MODE_MATCH, assets.TAP_BLANK_EXIT)
        sel0 = _make_char_select(locked_indices=(), lock_idx=0)
        sel1 = _make_char_select(locked_indices=(0,), lock_idx=1)
        court = _make_court_with_tile()
        bar1 = _make_timing_bar(360)
        bar2 = _make_timing_bar(535)
        reward = _blank_with(assets.LOGIN_REWARD)

        task = _new_island_task()
        task.device.image = hub
        frames = iter([
            # _open_and_check_volleyball #1 (skip_first=False -> hub -> click VOLLEYBALL -> vb_mode)
            hub,
            vb_mode,
            # _enter_volleyball_match (skip_first=True -> vb_mode -> click VB_MODE_MATCH -> sel0)
            sel0,
            # play_single_volleyball_match: skip_first=True (sel0 -> lock0 -> sel1 -> lock1 -> court -> bar1 -> bar2 -> reward -> vb_mode)
            sel1,
            court,
            bar1,
            bar2,
            reward,
            vb_mode,
            # _open_and_check_volleyball #2 (skip_first=False -> vb_mode reads 0/3)
            vb_mode,
            # _close_volleyball_mode_select (skip_first=False -> vb_mode -> TAP_BLANK_EXIT -> hub)
            vb_mode,
            hub,
        ])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))

        with patch('module.resonance.island_volleyball.read_volleyball_attempts', side_effect=[(1, 3), (0, 3)]), \
             patch('module.base.timer.time', side_effect=count(100, 1.0)), \
             patch('module.resonance.island_volleyball.time.monotonic', side_effect=[10.0, 10.7, 10.8, 10.9]):
            run_beach_volleyball(task)

        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in task.device.click.call_args_list]
        self.assertEqual(
            clicked,
            [
                'ISLAND_HUB_VOLLEYBALL',
                'VB_MODE_MATCH',
                'TEMPLATE_VB_LOCK_CLICK',
                'TEMPLATE_VB_LOCK_CLICK',
                'VB_GRID_TILE',
                'VB_TIMING_HIT',
                'LOGIN_REWARD',
                'TAP_BLANK_EXIT',
            ],
        )
        self.assertEqual(task.device.screenshot_interval_set.call_args_list, [call(0.03), call()])

    def test_collect_daily_income_and_zero_skip(self):
        from module.resonance import assets

        beach = _blank_with(assets.ISLAND_BEACH_CHECK)
        revenue = _blank_with(assets.ISLAND_REVENUE_CHECK, assets.ISLAND_REVENUE_COLLECT)
        reward = _blank_with(assets.LOGIN_REWARD)

        task = _new_island_task()
        task.device.image = beach
        frames = iter([revenue, reward, revenue])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))

        with patch('module.resonance.island.read_beach_income', return_value=5536973), \
             patch('module.base.timer.time', side_effect=count(100, 2.0)):
            task.collect_daily_income()

        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in task.device.click.call_args_list]
        self.assertEqual(clicked, ['ISLAND_REVENUE_COLLECT', 'LOGIN_REWARD'])

        task2 = _new_island_task()
        task2.device.image = beach
        with patch('module.resonance.island.read_beach_income', return_value=0):
            task2.collect_daily_income()
        task2.device.click.assert_not_called()

    def test_friend_fight_and_clean_abort_on_full_toast(self):
        from module.resonance import assets
        from module.resonance.island_friends import run_island_friends

        beach = _blank_with(assets.ISLAND_BEACH_CHECK, assets.ISLAND_FRIEND_TAB)
        flist = _blank_with(
            assets.ISLAND_FRIEND_LIST,
            assets.ISLAND_FRIEND_SORT_SEC,
            assets.ISLAND_FRIEND_SORT_CLEAN,
            assets.ISLAND_FRIEND_VISIT_0,
        )
        flist_clean = flist.copy()
        flist_clean[214:230, 434:456] = 250
        f_mon = _make_friend_island(next_enabled=True, with_monster=True)
        op_team = _blank_with(assets.OP_TEAM, assets.OP_TEAM_START)
        op_win = _blank_with(assets.OP_WIN, assets.OP_NEXT)
        f_coin = _make_friend_island(next_enabled=False, with_coin=True)
        toast = _blank_with(assets.ISLAND_FRIEND_CHECK, assets.OP_BACK)
        toast[336:384, 400:880] = 30

        task = _new_island_task()
        task.device.image = beach
        frames = iter([
            # Fight phase _open_friend_and_visit_first (skip_first=False): beach -> tab -> flist -> sort -> flist -> visit -> f_mon
            beach,
            flist,
            flist,
            f_mon,
            # Click monster -> OP_TEAM -> win -> back at f_mon (assists now 0/5!)
            op_team,
            op_win,
            f_mon,
            # Clean phase _open_friend_and_visit_first (skip_first=False): f_mon -> tab_visit -> flist_clean -> sort -> flist_clean -> visit -> f_coin
            f_mon,
            flist_clean,
            flist_clean,
            f_coin,
            # Clean clicks -> garbage-full toast
            toast,
            # _exit_friend_island (skip_first=True -> toast -> click OP_BACK -> beach)
            beach,
        ])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))

        with patch('module.resonance.island_friends.read_friend_assist_remaining', side_effect=[5, 0, 0]), \
             patch('module.resonance.island_friends.read_friend_clean_remaining', return_value=3), \
             patch('module.resonance.island_friends.TOAST_OCR.ocr', return_value='火车垃圾箱的垃圾块暂存区没有空间'), \
             patch('module.base.timer.time', side_effect=count(100, 1.5)):
            run_island_friends(task, fight=True, clean=True)

        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in task.device.click.call_args_list]
        self.assertEqual(
            clicked,
            [
                'ISLAND_FRIEND_TAB',
                'ISLAND_FRIEND_SORT_SEC',
                'ISLAND_FRIEND_VISIT_0',
                'FRIEND_MONSTER',
                'OP_TEAM_START',
                'OP_NEXT',
                'ISLAND_FRIEND_TAB_VISIT',
                'ISLAND_FRIEND_SORT_CLEAN',
                'ISLAND_FRIEND_VISIT_0',
                'ISLAND_FRIEND_CLEAN',
                'OP_BACK',
            ],
        )

    def test_friend_clean_uses_broom_icon_and_skips_empty(self):
        from module.resonance import assets
        from module.resonance.island_friends import run_island_friends

        beach = _blank_with(assets.ISLAND_BEACH_CHECK, assets.ISLAND_FRIEND_TAB)
        flist_no_broom = _blank_with(assets.ISLAND_FRIEND_LIST, assets.ISLAND_FRIEND_SORT_CLEAN)
        flist_no_broom[210:276, 470:548] = (235, 160, 180)

        # Case 1: sorted by 清扫 with 0 broom icons -> close drawer without visiting anyone
        task1 = _new_island_task()
        task1.device.image = beach
        frames1 = iter([beach, flist_no_broom, flist_no_broom, beach])
        task1.device.screenshot.side_effect = lambda: setattr(task1.device, 'image', next(frames1))
        with patch('module.base.timer.time', side_effect=count(100, 1.5)):
            run_island_friends(task1, fight=False, clean=True)
        clicked1 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task1.device.click.call_args_list]
        self.assertEqual(clicked1, ['ISLAND_FRIEND_TAB', 'ISLAND_FRIEND_SORT_CLEAN', 'FRIEND_DRAWER_CLOSE'])

        # Case 2: active 清扫 chevron + Row 0 current pink without broom -> clicks Row 1 directly, then exits on empty
        flist_row1 = _blank_with(assets.ISLAND_FRIEND_LIST)
        flist_row1[154:169, 298:328] = (230, 160, 180)   # active 清扫 chevron
        flist_row1[207:237, 300:360] = (220, 170, 195)   # Row 0 pink current (no broom)
        flist_row1[210:276, 470:548] = (235, 160, 180)   # Row 0 visit triangle
        flist_row1[331:361, 300:360] = (120, 185, 240)   # Row 1 blue other
        flist_row1[334:400, 470:548] = (235, 160, 180)   # Row 1 visit triangle
        flist_row1[336:354, 434:456] = 250               # Row 1 white broom icon
        flist_active_empty = _blank_with(assets.ISLAND_FRIEND_LIST)
        flist_active_empty[154:169, 298:328] = (230, 160, 180)

        f_coin = _make_friend_island(with_coin=True)
        clean_res = _blank_with(assets.ISLAND_FRIEND_CLEAN_RESULT)
        f_done = _make_friend_island(with_coin=False)
        task2 = _new_island_task()
        task2.device.image = beach
        frames2 = iter([beach, flist_row1, f_coin, clean_res, f_done, f_done, flist_active_empty, f_done, beach])
        task2.device.screenshot.side_effect = lambda: setattr(task2.device, 'image', next(frames2))
        with patch('module.resonance.island_friends.read_friend_clean_remaining', side_effect=[3, 2]), \
             patch('module.base.timer.time', side_effect=count(100, 1.5)):
            run_island_friends(task2, fight=False, clean=True)
        clicked2 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task2.device.click.call_args_list]
        self.assertEqual(
            clicked2,
            [
                'ISLAND_FRIEND_TAB',
                'ISLAND_FRIEND_VISIT_1',
                'ISLAND_FRIEND_CLEAN',
                'ISLAND_FRIEND_CLEAN_RESULT',
                'ISLAND_FRIEND_TAB_VISIT',
                'FRIEND_DRAWER_CLOSE',
                'OP_BACK',
            ],
        )

        # Case 3: confirmed cooldown friends are skipped once each, then the phase exits
        f_coin_cd = f_coin.copy()
        f_coin_cd[68:84, 1035:1075] = (235, 130, 155)
        flist_2clean = _blank_with(assets.ISLAND_FRIEND_LIST)
        flist_2clean[154:169, 298:328] = (230, 160, 180)
        flist_2clean[210:276, 470:548] = (235, 160, 180)
        flist_2clean[214:230, 434:456] = 250
        flist_2clean_next = flist_2clean.copy()
        flist_2clean_next[207:237, 300:360] = (220, 170, 195)
        flist_2clean_next[334:400, 470:548] = (235, 160, 180)
        flist_2clean_next[336:354, 434:456] = 250

        task3 = _new_island_task()
        task3.device.image = beach
        frames3 = iter([
            beach, flist_2clean, f_coin, clean_res, f_coin_cd,
            f_coin_cd, flist_2clean_next, f_coin_cd,
            f_coin_cd, flist_2clean_next, beach,
        ])
        task3.device.screenshot.side_effect = lambda: setattr(task3.device, 'image', next(frames3))
        with patch('module.base.timer.time', side_effect=count(100, 1.5)):
            run_island_friends(task3, fight=False, clean=True)
        clicked3 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task3.device.click.call_args_list]
        self.assertEqual(
            clicked3,
            [
                'ISLAND_FRIEND_TAB',
                'ISLAND_FRIEND_VISIT_0',
                'ISLAND_FRIEND_CLEAN',
                'ISLAND_FRIEND_CLEAN_RESULT',
                'ISLAND_FRIEND_TAB_VISIT',
                'ISLAND_FRIEND_VISIT_1',
                'ISLAND_FRIEND_TAB_VISIT',
                'FRIEND_DRAWER_CLOSE',
            ],
        )

    def test_friend_clean_requires_confirmation(self):
        from module.resonance.island_friends import (
            _clean_current_friend, has_friend_clean_coin, has_friend_clean_cooldown,
            is_friend_next_enabled, read_friend_clean_remaining,
        )

        f_coin = _make_friend_island(with_coin=True)
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'screenshots', 'resonance', 'island_cleanup_skipped_20261128.png')
        if os.path.exists(path):
            original = np.array(Image.open(path).convert('RGB'))
            self.assertEqual(read_friend_clean_remaining(original), 3)
            self.assertTrue(has_friend_clean_coin(original))
            self.assertFalse(has_friend_clean_cooldown(original))
            self.assertTrue(is_friend_next_enabled(original))
            cases = [(original, 3, 'unknown')]
        else:
            cases = []
        cases += [(f_coin, 3, 'unknown'), (f_coin, 2, 'cleaned')]
        for image, remaining, expected in cases:
            task = _new_island_task()
            task.device.image = image
            task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', image)
            with patch('module.resonance.island_friends.read_friend_clean_remaining',
                       side_effect=[3, remaining]), \
                 patch('module.base.timer.time', side_effect=count(100, 1.5)):
                self.assertEqual(_clean_current_friend(task), expected)
            self.assertEqual([c[0][0].name for c in task.device.click.call_args_list], ['ISLAND_FRIEND_CLEAN'])

    def test_friend_clean_unknown_moves_to_later_candidate(self):
        from module.resonance.island_friends import _run_friend_clean_phase

        task = _new_island_task()
        task.device.image = _make_friend_island()
        seen_rows = []

        def open_friend(*args, **kwargs):
            seen_rows.append(set(kwargs['skip_rows']))
            return [1, 3, False][len(seen_rows) - 1]

        with patch('module.resonance.island_friends._open_friend_and_visit_first',
                   side_effect=open_friend), \
             patch('module.resonance.island_friends._clean_current_friend',
                   side_effect=['unknown', 'cleaned']):
            _run_friend_clean_phase(task)
        self.assertEqual(seen_rows, [set(), {1}, {1, 3}])

    def test_friend_fight_arrest_flow_and_fallbacks(self):
        from module.resonance import assets
        from module.resonance.island_friends import _wait_friend_battle

        op_team = _blank_with(assets.OP_TEAM, assets.OP_TEAM_START)
        op_win = _blank_with(assets.OP_WIN, assets.OP_NEXT)
        op_win_arrest = _blank_with(assets.OP_WIN, assets.OP_NEXT, assets.OP_WIN_ARREST)
        modal = _blank_with(
            assets.ARREST_MODAL,
            assets.ARREST_MAX,
            assets.ARREST_CONFIRM,
            assets.ARREST_CANCEL,
            assets.TAP_BLANK_EXIT,
        )
        anim = _blank_with(assets.ARREST_ANIM_SKIP)
        result = _blank_with(assets.ARREST_RESULT)
        blank_exit_only = _blank_with(assets.TAP_BLANK_EXIT)
        friend = _make_friend_island(next_enabled=True)

        # Case 1: Happy path closes ARREST_RESULT directly back to friend island without clicking OP_NEXT
        task1 = _new_island_task(friend_arrest=True)
        task1.device.image = op_team
        frames1 = iter([op_win_arrest, modal, modal, anim, result, friend])
        task1.device.screenshot.side_effect = lambda: setattr(task1.device, 'image', next(frames1))
        with patch('module.base.timer.time', side_effect=count(100, 3.0)):
            _wait_friend_battle(task1, arrest=True)
        clicked1 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task1.device.click.call_args_list]
        self.assertEqual(
            clicked1,
            ['OP_TEAM_START', 'OP_WIN_ARREST', 'ARREST_MAX', 'ARREST_CONFIRM', 'ARREST_ANIM_SKIP', 'ARREST_RESULT'],
        )

        # Case 2: Non-capturable monster (OP_WIN without OP_WIN_ARREST) settles and clicks OP_NEXT
        task2 = _new_island_task(friend_arrest=True)
        task2.device.image = op_team
        frames2 = iter([op_win, op_win, friend])
        task2.device.screenshot.side_effect = lambda: setattr(task2.device, 'image', next(frames2))
        with patch('module.base.timer.time', side_effect=count(100, 3.0)):
            _wait_friend_battle(task2, arrest=True)
        clicked2 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task2.device.click.call_args_list]
        self.assertEqual(clicked2, ['OP_TEAM_START', 'OP_NEXT'])

        # Case 3: Confirm stall cancels modal back to victory screen, then exits via OP_NEXT once
        task3 = _new_island_task(friend_arrest=True)
        task3.device.image = op_team
        frames3 = iter([op_win_arrest, modal, modal, modal, modal, op_win_arrest, friend])
        task3.device.screenshot.side_effect = lambda: setattr(task3.device, 'image', next(frames3))
        with patch('module.base.timer.time', side_effect=count(100, 3.0)):
            _wait_friend_battle(task3, arrest=True)
        clicked3 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task3.device.click.call_args_list]
        self.assertEqual(
            clicked3,
            [
                'OP_TEAM_START',
                'OP_WIN_ARREST',
                'ARREST_MAX',
                'ARREST_CONFIRM',
                'ARREST_CONFIRM',
                'ARREST_CANCEL',
                'OP_NEXT',
            ],
        )

        # Case 4: Variant 0-caught result screen closes cleanly via TAP_BLANK_EXIT fallback
        task4 = _new_island_task(friend_arrest=True)
        task4.device.image = op_team
        frames4 = iter([op_win_arrest, modal, modal, blank_exit_only, friend])
        task4.device.screenshot.side_effect = lambda: setattr(task4.device, 'image', next(frames4))
        with patch('module.base.timer.time', side_effect=count(100, 3.0)):
            _wait_friend_battle(task4, arrest=True)
        clicked4 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task4.device.click.call_args_list]
        self.assertEqual(
            clicked4,
            ['OP_TEAM_START', 'OP_WIN_ARREST', 'ARREST_MAX', 'ARREST_CONFIRM', 'TAP_BLANK_EXIT'],
        )

    def test_volleyball_zoom_pan_blue_tile_and_training_end(self):
        from module.resonance import assets
        from module.resonance.island_volleyball import (
            _click_char_select, detect_grid_blue_marker, play_single_volleyball_match,
        )

        # 1) Distractors alone (ocean, ▼ arrow, thin net pole, umbrella, hint pill) -> None
        base_noise = np.full((720, 1280, 3), 180, dtype=np.uint8)
        base_noise[0:215, :] = (20, 160, 235)          # Ocean top band
        base_noise[290:325, 420:450] = (50, 175, 240)  # Small overhead ▼ arrow
        base_noise[240:420, 628:644] = (50, 175, 240)  # Thin vertical net pole
        base_noise[225:275, 920:1080] = (80, 200, 245) # Top-right beach umbrella
        base_noise[650:695, 900:1240] = (90, 185, 240) # Bottom-right hint pill
        self.assertIsNone(detect_grid_blue_marker(base_noise))

        # 2) Zoomed/shifted hollow tiles past x=635, above y=310, or near bottom edge
        for x1, y1, x2, y2 in ((700, 350, 880, 440), (260, 615, 460, 700), (300, 235, 460, 305)):
            frame = base_noise.copy()
            frame[y1:y2, x1:x2] = (80, 195, 240)
            frame[y1 + 14:y2 - 14, x1 + 22:x2 - 22] = (180, 180, 180)
            pos = detect_grid_blue_marker(frame)
            self.assertIsNotNone(pos, f'missed shifted/zoomed tile {(x1, y1, x2, y2)}')
            self.assertLess(abs(pos[0] - (x1 + x2) // 2), 15)
            self.assertLess(abs(pos[1] - (y1 + y2) // 2), 15)

        # 3) _click_char_select stays idle once both cards are locked
        both_locked = _make_char_select(locked_indices=(0, 1), lock_idx=None)
        idle_task = _new_island_task()
        idle_task.device.image = both_locked
        _click_char_select(idle_task, Mock(reached=Mock(return_value=True)))
        idle_task.device.click.assert_not_called()

        # 4) play_single_volleyball_match clicks VB_TRAINING_END on Defeat screen to exit
        sel0 = _make_char_select(locked_indices=(), lock_idx=0)
        sel1 = _make_char_select(locked_indices=(0,), lock_idx=1)
        court = _make_court_with_tile(x1=710, y1=240, x2=890, y2=330)
        training_end = _blank_with(assets.VB_TRAINING_END)
        vb_mode = _blank_with(assets.VB_MODE_MATCH)

        end_task = _new_island_task(play_vb=True)
        end_task.device.image = sel0
        frames = iter([sel1, court, training_end, vb_mode])
        end_task.device.screenshot.side_effect = lambda: setattr(end_task.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 1.0)):
            self.assertTrue(play_single_volleyball_match(end_task))
        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in end_task.device.click.call_args_list]
        self.assertEqual(clicked, ['TEMPLATE_VB_LOCK_CLICK', 'TEMPLATE_VB_LOCK_CLICK', 'VB_GRID_TILE', 'VB_TRAINING_END'])

    def test_island_run_orchestration(self):
        from module.resonance.page import page_resonance_island_beach

        task = _new_island_task(
            recycle_at_wilderness=False,
            promo_type='celebrity',
            promo_method='flyer',
            play_vb=True,
            collect_income=True,
            friend_fight=True,
            friend_arrest=True,
            friend_clean=False,
        )
        task.clean_train_garbage = Mock()
        task.goto_island_hub = Mock()
        task.run_promotion = Mock()
        task.collect_daily_income = Mock()
        mark_cleaned = Mock()

        with patch('module.resonance.island.load_garbage_clean_record',
                   return_value=(Mock(return_value=False), mark_cleaned)), \
             patch('module.resonance.island.run_beach_volleyball') as m_vb, \
             patch('module.resonance.island.run_island_friends') as m_fr:
            task.run()

        task.clean_train_garbage.assert_called_once()
        mark_cleaned.assert_called_once_with('island_test')
        task.goto_island_hub.assert_called_once()
        task.run_promotion.assert_called_once()
        m_vb.assert_called_once_with(task)
        task.ui_ensure.assert_called_once_with(page_resonance_island_beach, skip_first_screenshot=False)
        task.collect_daily_income.assert_called_once()
        m_fr.assert_called_once_with(task, fight=True, clean=False, arrest=True)
        task.ui_goto_main.assert_called_once()
        task.config.task_delay.assert_called_once_with(server_update=True)

    def test_island_reads_recycle_switch_through_cross_get(self):
        from module.resonance.island import RECYCLE_AT_WILDERNESS

        task = _new_island_task(recycle_at_wilderness=False)
        self.assertFalse(task.is_recycle_at_wilderness())
        task.config.cross_get.assert_called_once_with(
            'ResonanceTrade.ResonanceTrade.RecycleAtWilderness', False)
        self.assertEqual(RECYCLE_AT_WILDERNESS, 'ResonanceTrade.ResonanceTrade.RecycleAtWilderness')

        task_on = _new_island_task(recycle_at_wilderness=True)
        self.assertTrue(task_on.is_recycle_at_wilderness())

        # A config object without cross_get keeps the original paid cleanup.
        task_plain = _new_island_task()
        task_plain.config = Mock(spec=['config_name'])
        self.assertFalse(task_plain.is_recycle_at_wilderness())

    def test_island_recycle_switch_on_real_config(self):
        from module.config.config import AlasConfig
        from module.config.utils import read_file
        from module.resonance.island import ResonanceIsland

        task = ResonanceIsland.__new__(ResonanceIsland)
        task.config = AlasConfig.__new__(AlasConfig)
        task.config.data = read_file('config/template.json')

        # Default off: the island keeps the original paid train-car cleanup.
        self.assertFalse(task.is_recycle_at_wilderness())
        task.config.data['ResonanceTrade']['ResonanceTrade']['RecycleAtWilderness'] = True
        self.assertTrue(task.is_recycle_at_wilderness())

    def test_island_generated_recycle_default(self):
        from module.config.config_generated import GeneratedConfig
        from module.config.deep import deep_get
        from module.config.utils import read_file

        self.assertFalse(GeneratedConfig.ResonanceTrade_RecycleAtWilderness)
        self.assertFalse(hasattr(GeneratedConfig, 'ResonanceIsland_CleanTrainGarbage'))

        args = read_file('module/config/argument/args.json')
        entry = deep_get(args, 'ResonanceTrade.ResonanceTrade.RecycleAtWilderness')
        self.assertEqual(entry, {'type': 'checkbox', 'value': False})
        self.assertIsNone(deep_get(args, 'ResonanceIsland.ResonanceIsland.CleanTrainGarbage'))

    def test_island_paid_clean_skipped_when_wilderness_mode_on(self):
        task = _new_island_task(
            recycle_at_wilderness=True,
            promo_type='theme',
            play_vb=True,
            collect_income=True,
            friend_fight=True,
            friend_clean=True,
        )
        task.clean_train_garbage = Mock()
        task.goto_island_hub = Mock()
        task.run_promotion = Mock()
        task.collect_daily_income = Mock()

        with patch('module.resonance.island.load_garbage_clean_record') as load_record, \
             patch('module.resonance.island.run_beach_volleyball') as m_vb, \
             patch('module.resonance.island.run_island_friends') as m_fr:
            task.run()

        task.clean_train_garbage.assert_not_called()
        load_record.assert_not_called()
        # The rest of the island routine still runs.
        task.goto_island_hub.assert_called_once()
        task.run_promotion.assert_called_once()
        m_vb.assert_called_once_with(task)
        task.collect_daily_income.assert_called_once()
        m_fr.assert_called_once_with(task, fight=True, clean=True, arrest=False)
        task.ui_goto_main.assert_called_once()
        task.config.task_delay.assert_called_once_with(server_update=True)

    def test_island_paid_clean_skipped_when_already_cleaned_today(self):
        task = _new_island_task(
            recycle_at_wilderness=False,
            promo_type='none',
            play_vb=False,
            collect_income=False,
            friend_fight=False,
            friend_clean=False,
        )
        task.clean_train_garbage = Mock()
        mark_cleaned = Mock()

        with patch('module.resonance.island.load_garbage_clean_record',
                   return_value=(Mock(return_value=True), mark_cleaned)):
            task.run()

        task.clean_train_garbage.assert_not_called()
        mark_cleaned.assert_not_called()
        task.ui_goto_main.assert_called_once()
        task.config.task_delay.assert_called_once_with(server_update=True)

    def test_island_paid_clean_failure_keeps_day_unmarked(self):
        from module.exception import GameStuckError

        task = _new_island_task(
            recycle_at_wilderness=False,
            promo_type='none',
            play_vb=False,
            collect_income=False,
            friend_fight=False,
            friend_clean=False,
        )
        task.clean_train_garbage = Mock(side_effect=GameStuckError('compactor timeout'))
        mark_cleaned = Mock()
        is_cleaned_today = Mock(return_value=False)

        with patch('module.resonance.island.load_garbage_clean_record',
                   return_value=(is_cleaned_today, mark_cleaned)):
            with self.assertRaises(GameStuckError):
                task.run()

        is_cleaned_today.assert_called_once_with('island_test')
        mark_cleaned.assert_not_called()

    def test_island_marks_empty_compactor_as_cleaned(self):
        from module.resonance import assets

        garb_empty = _blank_with(assets.GARBAGE_CHECK)
        task = _new_island_task(
            recycle_at_wilderness=False,
            promo_type='none',
            play_vb=False,
            collect_income=False,
            friend_fight=False,
            friend_clean=False,
        )
        task.device.image = garb_empty
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', garb_empty)
        mark_cleaned = Mock()

        with patch('module.resonance.island.load_garbage_clean_record',
                   return_value=(Mock(return_value=False), mark_cleaned)), \
             patch('module.base.timer.time', side_effect=count(100, 1.0)):
            task.run()

        task.device.click.assert_not_called()
        mark_cleaned.assert_called_once_with('island_test')
        task.config.task_delay.assert_called_once_with(server_update=True)
