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


def _make_setting_drawer(selected_keys):
    from module.resonance import assets
    from module.resonance.preparation import TREE_ROWS

    frame = _blank_with(assets.SURVEY_CHECK, assets.SURVEY_AUTO_START, assets.SURVEY_SETTING)
    # Paste grayscale template inside BIRCH_ROI so is_setting_panel_open() sees the drawer
    tpl = load_image(assets.TEMPLATE_SURVEY_BIRCH.file)
    frame[539:573, 88:215] = tpl
    for key, (_, y1, _, y2) in TREE_ROWS:
        if key in selected_keys:
            frame[y1 + 8:y2 - 8, 250:330] = (140, 231, 200)
        else:
            frame[y1 + 8:y2 - 8, 250:330] = (18, 22, 20)
    return frame


def _make_prep_screen(with_badge):
    from module.resonance import assets

    frame = _blank_with(assets.PREP_CHECK, assets.PREP_SURVEY_ENTRY, assets.PREP_WEEKLY_REWARD)
    if with_badge:
        frame[628:642, 595:609] = (230, 30, 30)
    return frame


def _make_reward_modal():
    from module.resonance import assets
    from module.resonance.preparation import DEFAULT_MILESTONE_BOXES

    frame = _blank_with(assets.PREP_REWARD_MODAL)
    for x1, y1, x2, y2 in DEFAULT_MILESTONE_BOXES:
        frame[y1:y1 + 4, x1:x2] = (50, 120, 230)
        frame[y2 - 4:y2, x1:x2] = (50, 120, 230)
        frame[y1:y2, x1:x1 + 4] = (50, 120, 230)
        frame[y1:y2, x2 - 4:x2] = (50, 120, 230)
    return frame


def _make_op_victory():
    from module.resonance import assets

    return _blank_with(assets.OP_WIN, assets.OP_NEXT)


def _new_task(purple=True, rainbow=True, white=True, red=True, use_clarity_item='none'):
    from module.resonance.preparation import ResonancePreparation

    task = ResonancePreparation.__new__(ResonancePreparation)
    task.device = Mock()
    task.config = Mock()
    task.config.ResonancePreparation_FightPurple = purple
    task.config.ResonancePreparation_FightRainbow = rainbow
    task.config.ResonancePreparation_FightWhite = white
    task.config.ResonancePreparation_FightRed = red
    task.config.ResonancePreparation_UseClarityItem = use_clarity_item
    task.interval_timer = {}
    task.ui_ensure = Mock()
    task.ui_goto_main = Mock()
    return task


class TestResonancePreparation(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def test_preparation_assets_match_real_screenshots(self):
        from module.resonance import assets
        from module.resonance.preparation import (
            find_weekly_milestone_buttons, has_weekly_reward_badge, is_setting_panel_open, is_tree_row_selected,
            read_clarity_insufficient, TREE_ROWS,
        )

        base = 'C:/Users/14494/Documents/MuMu共享文件夹/Screenshots/'
        files = {
            'main': base + 'MuMu-20261125-131410-838.png',
            'term': base + 'MuMu-20261126-000931-316.png',
            'prep': base + 'MuMu-20261126-000935-344.png',
            'reward': base + 'MuMu-20261126-000939-321.png',
            'survey': base + 'MuMu-20261126-000948-780.png',
            'off': base + 'MuMu-20261126-000951-988.png',
            'on': base + 'MuMu-20261126-000957-102.png',
            'stop': base + 'MuMu-20261126-004056-088.png',
        }
        if not all(os.path.exists(p) for p in files.values()):
            return

        imgs = {k: np.array(Image.open(p).convert('RGB')) for k, p in files.items()}
        self.assertTrue(assets.MAIN_TERMINAL.match(imgs['main'], offset=(5, 5)))
        self.assertTrue(assets.TERMINAL_CHECK.match(imgs['term'], offset=(5, 5)))
        self.assertTrue(assets.PREP_TAB.match(imgs['term'], offset=(5, 5)))
        self.assertTrue(assets.PREP_CHECK.match(imgs['prep'], offset=(5, 5)))
        self.assertTrue(assets.PREP_SURVEY_ENTRY.match(imgs['prep'], offset=(5, 5)))
        self.assertTrue(assets.PREP_WEEKLY_REWARD.match(imgs['prep'], offset=(5, 5)))
        self.assertTrue(has_weekly_reward_badge(imgs['prep']))

        masked = imgs['prep'].copy()
        masked[620:650, 588:618] = (210, 155, 10)
        self.assertFalse(has_weekly_reward_badge(masked))

        self.assertTrue(assets.PREP_REWARD_MODAL.match(imgs['reward'], offset=(5, 5)))
        self.assertEqual(len(find_weekly_milestone_buttons(imgs['reward'])), 4)

        for key in ('survey', 'off', 'on'):
            self.assertTrue(assets.SURVEY_CHECK.match(imgs[key], offset=(5, 5)))
            self.assertTrue(assets.SURVEY_AUTO_START.match(imgs[key], offset=(5, 5)))
            self.assertFalse(assets.SURVEY_AUTO_STOP.match(imgs[key], offset=(5, 5)))
            self.assertTrue(assets.SURVEY_SETTING.match(imgs[key], offset=(5, 5)))

        self.assertFalse(assets.SURVEY_AUTO_START.match(imgs['stop'], offset=(5, 5)))
        self.assertTrue(assets.SURVEY_AUTO_STOP.match(imgs['stop'], offset=(5, 5)))
        self.assertTrue(assets.SURVEY_BATTLE_START.match(imgs['stop'], offset=(5, 5)))
        self.assertTrue(assets.SURVEY_SETTING.match(imgs['stop'], offset=(5, 5)))
        self.assertTrue(read_clarity_insufficient(imgs['stop']))

        self.assertFalse(is_setting_panel_open(imgs['survey']))
        self.assertTrue(is_setting_panel_open(imgs['off']))
        self.assertTrue(is_setting_panel_open(imgs['on']))

        for _, box in TREE_ROWS:
            self.assertFalse(is_tree_row_selected(imgs['off'], box))
            self.assertTrue(is_tree_row_selected(imgs['on'], box))

    def test_preparation_page_graph_links(self):
        from module.resonance.assets import DAILY_HOME, MAIN_TERMINAL, OP_BACK, PREP_SURVEY_ENTRY, PREP_TAB
        from module.resonance.page import (
            page_main, page_resonance_prep, page_resonance_survey, page_resonance_terminal,
        )

        self.assertIs(page_main.links[page_resonance_terminal], MAIN_TERMINAL)
        self.assertIs(page_resonance_terminal.links[page_resonance_prep], PREP_TAB)
        self.assertIs(page_resonance_terminal.links[page_main], DAILY_HOME)
        self.assertIs(page_resonance_prep.links[page_resonance_survey], PREP_SURVEY_ENTRY)
        self.assertIs(page_resonance_prep.links[page_main], DAILY_HOME)
        self.assertIs(page_resonance_survey.links[page_resonance_prep], OP_BACK)
        self.assertIs(page_resonance_survey.links[page_main], DAILY_HOME)

    def test_configure_targets_toggles_only_mismatched_rows(self):
        from module.resonance import assets

        survey_closed = _blank_with(assets.SURVEY_CHECK, assets.SURVEY_AUTO_START, assets.SURVEY_SETTING)
        drawer_initial = _make_setting_drawer({'red', 'rainbow'})
        drawer_white_on = _make_setting_drawer({'red', 'white', 'rainbow'})
        drawer_done = _make_setting_drawer({'red', 'white'})

        task = _new_task(purple=False, rainbow=False, white=True, red=True)
        task.device.image = survey_closed

        # Sequence of screenshots: open drawer -> toggle white -> toggle rainbow -> close drawer
        frames = iter([
            drawer_initial,
            drawer_white_on,
            drawer_done,
            survey_closed,
        ])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 2.0)):
            task.configure_targets(task.desired_targets())

        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in task.device.click.call_args_list]
        self.assertEqual(
            clicked,
            ['SURVEY_SETTING', 'SURVEY_TREE_WHITE', 'SURVEY_TREE_RAINBOW', 'SURVEY_SETTING'],
        )

    def test_preparation_run_full_flow(self):
        from module.resonance import assets
        from module.resonance.page import page_resonance_prep, page_resonance_survey

        survey_closed = _blank_with(assets.SURVEY_CHECK, assets.SURVEY_AUTO_START, assets.SURVEY_SETTING)
        drawer_off = _make_setting_drawer(set())
        drawer_purple = _make_setting_drawer({'purple'})
        op_pause = _blank_with(assets.OP_PAUSE, assets.OP_AUTO_ON)
        op_win = _make_op_victory()
        reward_popup = _blank_with(assets.LOGIN_REWARD)
        prep_badge = _make_prep_screen(with_badge=True)
        reward_modal = _make_reward_modal()

        task = _new_task(purple=True, rainbow=False, white=False, red=False)
        task.device.image = survey_closed

        def fake_ui_ensure(page, skip_first_screenshot=False):
            if page is page_resonance_prep:
                task.device.image = prep_badge
            elif page is page_resonance_survey:
                task.device.image = survey_closed

        task.ui_ensure.side_effect = fake_ui_ensure

        frames = iter([
            # configure_targets: open drawer -> toggle purple -> close drawer
            drawer_off,
            drawer_purple,
            survey_closed,
            # run_auto_crusade: start -> battle -> victory -> reward -> settle (count=3 -> 4 frames)
            op_pause,
            op_win,
            reward_popup,
            survey_closed,
            survey_closed,
            survey_closed,
            survey_closed,
            # claim_weekly_rewards: click weekly reward -> modal -> milestone_0 -> reward -> drain -> close
            reward_modal,
            reward_popup,
            reward_modal,
            prep_badge,
        ])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 3.0)):
            task.run()

        self.assertEqual(
            task.ui_ensure.call_args_list,
            [
                call(page_resonance_survey, skip_first_screenshot=False),
                call(page_resonance_prep, skip_first_screenshot=False),
            ],
        )
        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in task.device.click.call_args_list]
        self.assertEqual(
            clicked,
            [
                'SURVEY_SETTING',
                'SURVEY_TREE_PURPLE',
                'SURVEY_SETTING',
                'SURVEY_AUTO_START',
                'OP_NEXT',
                'LOGIN_REWARD',
                'PREP_WEEKLY_REWARD',
                'PREP_MILESTONE_0',
                'LOGIN_REWARD',
                'PREP_REWARD_MODAL',
            ],
        )
        task.ui_goto_main.assert_called_once()
        task.config.task_delay.assert_called_once_with(server_update=True)

    def test_preparation_skips_crusade_and_badgeless_weekly_reward(self):
        from module.resonance.page import page_resonance_prep

        prep_clean = _make_prep_screen(with_badge=False)
        task = _new_task(purple=False, rainbow=False, white=False, red=False)
        task.device.image = prep_clean

        task.run()

        task.ui_ensure.assert_called_once_with(page_resonance_prep, skip_first_screenshot=False)
        task.device.click.assert_not_called()
        task.ui_goto_main.assert_called_once()
        task.config.task_delay.assert_called_once_with(server_update=True)

    def test_auto_crusade_exits_when_no_target_or_refill_cancelled(self):
        from module.resonance import assets

        survey_closed = _blank_with(assets.SURVEY_CHECK, assets.SURVEY_AUTO_START, assets.SURVEY_SETTING)
        # Case 1: stays on survey screen with no battle starting -> no_start (count=3 -> 4 frames)
        task = _new_task()
        task.device.image = survey_closed
        frames = iter([survey_closed, survey_closed, survey_closed, survey_closed])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 3.0)):
            self.assertEqual(task.run_auto_crusade(), 'no_target')
        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in task.device.click.call_args_list]
        self.assertEqual(clicked, ['SURVEY_AUTO_START'])

        # Case 2: refill prompt cancelled -> cancel_settle (count=2 -> 3 frames)
        refill_modal = _blank_with(assets.FATIGUE_CONFIRM_MODAL, assets.FATIGUE_CONFIRM_CANCEL)
        task2 = _new_task()
        task2.device.image = survey_closed
        frames2 = iter([refill_modal, survey_closed, survey_closed, survey_closed])
        task2.device.screenshot.side_effect = lambda: setattr(task2.device, 'image', next(frames2))
        with patch('module.base.timer.time', side_effect=count(100, 3.0)):
            self.assertEqual(task2.run_auto_crusade(), 'no_clarity')
        clicked2 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task2.device.click.call_args_list]
        self.assertEqual(clicked2, ['SURVEY_AUTO_START', 'FATIGUE_CONFIRM_CANCEL'])

    def test_out_of_clarity_switches_to_white_tree_and_restores(self):
        from module.resonance import assets
        from module.resonance.page import page_resonance_prep, page_resonance_survey

        survey_closed = _blank_with(assets.SURVEY_CHECK, assets.SURVEY_AUTO_START, assets.SURVEY_SETTING)
        survey_stop_panel = _blank_with(assets.SURVEY_AUTO_STOP, assets.SURVEY_BATTLE_START, assets.SURVEY_SETTING)
        drawer_off = _make_setting_drawer(set())
        drawer_red_only = _make_setting_drawer({'red'})
        drawer_red_white = _make_setting_drawer({'red', 'white'})
        drawer_white_only = _make_setting_drawer({'white'})
        op_win = _make_op_victory()
        prep_clean = _make_prep_screen(with_badge=False)

        task = _new_task(purple=False, rainbow=False, white=True, red=True)
        task.device.image = survey_closed

        def fake_ui_ensure(page, skip_first_screenshot=False):
            if page is page_resonance_prep:
                task.device.image = prep_clean
            elif page is page_resonance_survey:
                task.device.image = survey_closed

        task.ui_ensure.side_effect = fake_ui_ensure

        frames = iter([
            # Initial configure: red + white -> close
            drawer_off,
            drawer_red_only,
            drawer_red_white,
            survey_closed,
            # Crusade 1: starts -> hits out-of-clarity stop panel -> stops back to survey_closed
            survey_stop_panel,
            survey_closed,
            # Switch to white-only: open -> uncheck red -> close
            drawer_red_white,
            drawer_white_only,
            survey_closed,
            # Crusade 2 (white tree free): victory -> settles back on survey (4 frames)
            op_win,
            survey_closed,
            survey_closed,
            survey_closed,
            survey_closed,
            # Restore original red + white checkboxes: open -> re-check red -> close
            drawer_white_only,
            drawer_red_white,
            survey_closed,
        ])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))

        with patch('module.resonance.preparation.read_clarity_insufficient', return_value=True), \
             patch('module.base.timer.time', side_effect=count(100, 3.0)):
            task.run()

        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in task.device.click.call_args_list]
        self.assertEqual(
            clicked,
            [
                'SURVEY_SETTING', 'SURVEY_TREE_RED', 'SURVEY_TREE_WHITE', 'SURVEY_SETTING',
                'SURVEY_AUTO_START', 'SURVEY_AUTO_STOP',
                'SURVEY_SETTING', 'SURVEY_TREE_RED', 'SURVEY_SETTING',
                'SURVEY_AUTO_START', 'OP_NEXT',
                'SURVEY_SETTING', 'SURVEY_TREE_RED', 'SURVEY_SETTING',
            ],
        )
        task.ui_goto_main.assert_called_once()
        task.config.task_delay.assert_called_once_with(server_update=True)

    def test_auto_crusade_clarity_item_refill_and_prompt_cancel(self):
        from dev_tools.test_resonance_clarity import make_clarity_confirm_modal, make_clarity_recovery_screen
        from module.resonance import assets

        survey_closed = _blank_with(assets.SURVEY_CHECK, assets.SURVEY_AUTO_START, assets.SURVEY_SETTING)
        survey_stop_panel = _blank_with(assets.SURVEY_AUTO_STOP, assets.SURVEY_BATTLE_START, assets.SURVEY_SETTING)
        page_full = make_clarity_recovery_screen(has_lollipop=True, has_gum=True, has_cactus=False)
        confirm = make_clarity_confirm_modal()
        op_win = _make_op_victory()
        prompt = _blank_with(assets.CLARITY_PROMPT, assets.CLARITY_PROMPT_CANCEL, assets.CLARITY_PROMPT_CONFIRM)

        # Case 1: UseClarityItem='lollipop' -> clicks SURVEY_CLARITY_PLUS, uses lollipop, finishes crusade
        task1 = _new_task(use_clarity_item='lollipop')
        task1.device.image = survey_closed
        frames1 = iter([
            survey_stop_panel,
            page_full, confirm, page_full, survey_closed, survey_closed,
            op_win, survey_closed, survey_closed, survey_closed, survey_closed,
        ])
        task1.device.screenshot.side_effect = lambda: setattr(task1.device, 'image', next(frames1))
        with patch('module.resonance.preparation.read_clarity_insufficient', return_value=True), \
             patch('module.resonance.clarity.read_clarity_fraction', return_value=(17, 358)), \
             patch('module.resonance.clarity.CLARITY_CNT_OCR.ocr', side_effect=[['24'], ['40']]), \
             patch('module.resonance.clarity.FATIGUE_CONFIRM_QTY_OCR.ocr', return_value='1/10'), \
             patch('module.base.timer.time', side_effect=count(100, 3.0)):
            self.assertEqual(task1.run_auto_crusade(), 'done')
        clicked1 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task1.device.click.call_args_list]
        self.assertEqual(
            clicked1,
            [
                'SURVEY_AUTO_START', 'SURVEY_CLARITY_PLUS', 'CLARITY_ITEM_LOLLIPOP',
                'FATIGUE_CONFIRM_OK', 'OP_BACK', 'SURVEY_AUTO_START', 'OP_NEXT',
            ],
        )

        # Case 2: UseClarityItem='none' -> cancels CLARITY_PROMPT cleanly and returns 'no_clarity'
        task2 = _new_task(use_clarity_item='none')
        task2.device.image = survey_closed
        frames2 = iter([prompt, survey_closed, survey_closed, survey_closed, survey_closed])
        task2.device.screenshot.side_effect = lambda: setattr(task2.device, 'image', next(frames2))
        with patch('module.base.timer.time', side_effect=count(100, 3.0)):
            self.assertEqual(task2.run_auto_crusade(), 'no_clarity')
        clicked2 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task2.device.click.call_args_list]
        self.assertEqual(clicked2, ['SURVEY_AUTO_START', 'CLARITY_PROMPT_CANCEL'])
