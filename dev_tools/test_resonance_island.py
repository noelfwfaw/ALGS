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


def _make_promo_modal(method='flyer'):
    from module.resonance import assets
    from module.resonance.island import PROMO_METHOD_TABS

    frame = _blank_with(
        assets.ISLAND_PROMO_MODAL,
        assets.ISLAND_PROMO_MAX,
        assets.ISLAND_PROMO_CONFIRM,
        assets.ISLAND_PROMO_CANCEL,
    )
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
    clean_garbage=True,
    promo_type='promotion',
    promo_method='flyer',
    play_vb=True,
    collect_income=True,
    friend_fight=True,
    friend_clean=True,
):
    from module.resonance.island import ResonanceIsland

    task = ResonanceIsland.__new__(ResonanceIsland)
    task.device = Mock()
    task.config = Mock()
    task.config.ResonanceIsland_CleanTrainGarbage = clean_garbage
    task.config.ResonanceIsland_PromotionType = promo_type
    task.config.ResonanceIsland_PromotionMethod = promo_method
    task.config.ResonanceIsland_PlayVolleyball = play_vb
    task.config.ResonanceIsland_CollectIncome = collect_income
    task.config.ResonanceIsland_FriendFight = friend_fight
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
            find_sidebar_template, is_promo_method_selected, is_promo_park_full, read_beach_income,
            read_promo_stock, ISLAND_CARD_ROI, SIDEBAR_ROI,
        )
        from module.resonance.island_friends import (
            detect_friend_monsters, has_friend_clean_coin, is_friend_next_enabled, is_garbage_full_toast,
            read_friend_assist_remaining, read_friend_clean_remaining, read_friend_monster_count,
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
        self.assertTrue(assets.OP_WIN.match(imgs['f_win'], offset=(5, 5)))

        # Promotion vision & OCR
        self.assertTrue(is_promo_method_selected(imgs['promo_modal'], 'flyer'))
        self.assertFalse(is_promo_method_selected(imgs['promo_modal'], 'ad_ticket'))
        self.assertFalse(is_promo_park_full(imgs['promo']))
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
        self.assertTrue(is_friend_next_enabled(imgs['f_mon1']))
        self.assertFalse(is_garbage_full_toast(imgs['f_clean']))
        self.assertTrue(is_garbage_full_toast(imgs['f_toast']))

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
            # Clean phase _open_friend_and_visit_first (skip_first=False): f_mon -> tab_visit -> flist -> sort -> flist -> visit -> f_coin
            f_mon,
            flist,
            flist,
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

    def test_island_run_orchestration(self):
        from module.resonance.page import page_resonance_island_beach

        task = _new_island_task(
            clean_garbage=True,
            promo_type='celebrity',
            promo_method='flyer',
            play_vb=True,
            collect_income=True,
            friend_fight=True,
            friend_clean=False,
        )
        task.clean_train_garbage = Mock()
        task.goto_island_hub = Mock()
        task.run_promotion = Mock()
        task.collect_daily_income = Mock()

        with patch('module.resonance.island.run_beach_volleyball') as m_vb, \
             patch('module.resonance.island.run_island_friends') as m_fr:
            task.run()

        task.clean_train_garbage.assert_called_once()
        task.goto_island_hub.assert_called_once()
        task.run_promotion.assert_called_once()
        m_vb.assert_called_once_with(task)
        task.ui_ensure.assert_called_once_with(page_resonance_island_beach, skip_first_screenshot=False)
        task.collect_daily_income.assert_called_once()
        m_fr.assert_called_once_with(task, fight=True, clean=False)
        task.ui_goto_main.assert_called_once()
        task.config.task_delay.assert_called_once_with(server_update=True)
