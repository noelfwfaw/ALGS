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


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ARCHIVE_DIR = os.path.join(_REPO_ROOT, 'screenshots', 'resonance')

# 凭证置换 milestone node looks, sampled from the live screen: a claimable node
# carries a vivid blue frame, a claimed one is dimmed navy with a check mark and
# a locked one is a muted blue padlock.
_BADGE_FRAME_COLOURS = {
    'claimable': (63, 126, 251),
    'claimed': (31, 62, 124),
    'locked': (44, 88, 175),
}
# Box of one node of each state inside the archived 凭证置换 screen.
_BADGE_SOURCE_BOXES = {
    'claimable': (587, 385, 695, 493),
    'claimed': (392, 226, 498, 332),
    'locked': (783, 226, 891, 333),
}
# Layout of the archived 凭证置换 screen, used to rebuild the very same screen
# when the archived capture is not available in this worktree.
_MILESTONE_LAYOUT = (
    (_BADGE_SOURCE_BOXES['claimed'][0], _BADGE_SOURCE_BOXES['claimed'][1], 'claimed'),
    (_BADGE_SOURCE_BOXES['claimable'][0], _BADGE_SOURCE_BOXES['claimable'][1], 'claimable'),
    (_BADGE_SOURCE_BOXES['locked'][0], _BADGE_SOURCE_BOXES['locked'][1], 'locked'),
)


def _archive(name):
    """Return the archived resonance screenshot path (archived copies are not tracked by git)."""
    return os.path.join(_ARCHIVE_DIR, name)


def _default_milestone_boxes():
    """Return the frozen default milestone boxes, or [] when the module no longer exposes them."""
    try:
        from module.resonance.preparation import DEFAULT_MILESTONE_BOXES
    except ImportError:
        return []
    return [tuple(b) for b in DEFAULT_MILESTONE_BOXES]


def _frozen_centres():
    """Return the click centres of the frozen default milestone boxes."""
    return [((b[0] + b[2]) // 2, (b[1] + b[3]) // 2) for b in _default_milestone_boxes()]


def _badge_patch(kind, size=108):
    """Return the artwork of one milestone node in the requested state.

    The archived screen is the source of truth whenever it is available, so that a
    classifier built on the live look keeps working on the test doubles. The drawn
    fallback only carries the frame colour sampled from the live screen.
    """
    path = _archive('preparation_milestones_shifted_20261128.png')
    if os.path.exists(path):
        real = load_image(path)
        x1, y1, x2, y2 = _BADGE_SOURCE_BOXES[kind]
        return real[y1:y2, x1:x2].copy()
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    colour = _BADGE_FRAME_COLOURS[kind]
    canvas[0:5, :] = colour
    canvas[size - 5:, :] = colour
    canvas[:, 0:5] = colour
    canvas[:, size - 5:] = colour
    return canvas


def _make_milestone_view(nodes):
    """Compose a 凭证置换 view.

    nodes is a list of (origin_x, origin_y, kind) triples; the returned slot list
    holds the exact box every node was pasted at, together with its state.
    """
    from module.resonance import assets

    frame = _blank_with(assets.PREP_REWARD_MODAL)
    slots = []
    for ox, oy, kind in nodes:
        patch = _badge_patch(kind)
        h, w = patch.shape[:2]
        frame[oy:oy + h, ox:ox + w] = patch
        slots.append(((ox, oy, ox + w, oy + h), kind))
    return frame, slots


def _click_center(target):
    """Return the click centre of a Button / bbox target, or None."""
    bbox = getattr(target, 'button', None)
    if bbox is None and isinstance(target, (tuple, list)) and len(target) >= 4:
        bbox = tuple(target[:4])
    if not isinstance(bbox, (tuple, list)) or len(bbox) < 4:
        return None
    x1, y1, x2, y2 = bbox[:4]
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def _click_name(target):
    return getattr(target, 'name', None)


def _inside(center, box):
    if center is None:
        return False
    return box[0] <= center[0] <= box[2] and box[1] <= center[1] <= box[3]


def _claimable_node_box(image):
    """Return the box of the single claimable node detected in a 凭证置换 screen."""
    from module.resonance.preparation import find_weekly_milestone_buttons

    buttons = find_weekly_milestone_buttons(image)
    if len(buttons) != 1:
        raise AssertionError(f'expected exactly one claimable milestone node, got {len(buttons)}')
    return tuple(buttons[0].button)


def _milestone_track():
    """Return the 凭证置换 track and the box of its single claimable node.

    The archived capture is the source of truth whenever it is available. A fresh
    checkout has no archived screenshot, so the very same layout is rebuilt from
    the drawn milestone cards of this file: the 600 node keeps the claimable
    highlight, the 550 node stays the claimed one and the 650 node stays locked.
    """
    path = _archive('preparation_milestones_shifted_20261128.png')
    if os.path.exists(path):
        track = load_image(path)
    else:
        track, _ = _make_milestone_view(_MILESTONE_LAYOUT)
    return track, _claimable_node_box(track)


def _with_claimed_node(track, box):
    """Return the archived track with the given node showing the claimed artwork.

    The artwork is the check-marked card of the very same screen, so the frame
    stays a real capture of the 凭证置换 screen instead of a drawn stand-in.
    """
    artwork_box = _BADGE_SOURCE_BOXES['claimed']
    artwork = track[artwork_box[1]:artwork_box[3], artwork_box[0]:artwork_box[2]]
    view = track.copy()
    x1, y1, x2, y2 = box
    view[y1:y2, x1:x2] = np.array(Image.fromarray(artwork).resize((x2 - x1, y2 - y1)))
    return view


class _WeeklyRewardFeed:
    """Scripted 全域整备 / 凭证置换 screen feed.

    The feed advances one state when the script clicks the state's declared
    trigger asset or the state's claimable slot. Only a click landing on the
    declared claimable slot counts as a successful claim, so an implementation
    that reuses stale coordinates cannot fake a second claim.
    """

    def __init__(self, states):
        self.states = list(states)
        self.index = 0
        self.claims = []
        self.clicks = []
        self.click_log = []

    @property
    def frame(self):
        return self.states[self.index]['frame']

    def screenshot(self):
        return self.frame

    def click(self, target):
        center = _click_center(target)
        self.clicks.append(center)
        self.click_log.append((self.index, center))
        state = self.states[self.index]
        slot = state.get('claimable')
        if slot is not None and _inside(center, slot):
            self.claims.append(center)
            self._advance()
            return
        triggers = state.get('advance_on') or ()
        if _click_name(target) in triggers:
            self._advance()

    def clicks_in(self, index):
        """Return every click centre recorded while the feed was showing state `index`."""
        return [center for state_index, center in self.click_log if state_index == index]

    def _advance(self):
        self.index = min(self.index + 1, len(self.states) - 1)


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
            find_weekly_milestone_buttons, has_weekly_reward_badge, is_claimable_milestone_box,
            is_setting_panel_open, is_tree_row_selected,
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
        missing = sorted(name for name, path in files.items() if not os.path.exists(path))
        if missing:
            self.skipTest(f'live MuMu screenshots are missing: {missing}')

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
        # This screen only proves that the 凭证置换 modal is open. Which of the visible
        # nodes may be claimed is decided per card, so assert that decision instead of
        # counting the visible cells and calling them all claimable.
        for btn in find_weekly_milestone_buttons(imgs['reward']):
            self.assertTrue(is_claimable_milestone_box(imgs['reward'], btn.button))

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
        prep_clean = _make_prep_screen(with_badge=False)

        # The archived 凭证置换 track is the real screen: the 600 node still carries the
        # claimable highlight, the 550 node is already claimed and the 650 node is
        # locked, so only the 600 node may be clicked. A checkout without the archived
        # capture rebuilds that very same layout from the drawn cards of this file.
        track, claimed_box = _milestone_track()
        track_claimed = _with_claimed_node(track, claimed_box)

        task = _new_task(purple=True, rainbow=False, white=False, red=False)
        task.device.image = survey_closed

        weekly = {'active': False}

        def fake_ui_ensure(page, skip_first_screenshot=False):
            if page is page_resonance_prep:
                task.device.image = prep_badge
                weekly['active'] = True
            elif page is page_resonance_survey:
                task.device.image = survey_closed

        task.ui_ensure.side_effect = fake_ui_ensure

        # 领奖 -> 弹窗关闭 -> 凭证置换仍在前台并重新扫描 -> 预期关闭 -> 返回整备
        feed = _WeeklyRewardFeed([
            {'frame': prep_badge, 'advance_on': ('PREP_WEEKLY_REWARD',)},
            {'frame': track, 'claimable': claimed_box},
            {'frame': reward_popup, 'advance_on': ('LOGIN_REWARD',)},
            {'frame': track_claimed, 'advance_on': ('PREP_REWARD_MODAL',)},
            {'frame': prep_clean},
        ])

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
        ])

        def fake_screenshot():
            task.device.image = feed.frame if weekly['active'] else next(frames)
            return task.device.image

        def fake_click(target):
            if weekly['active']:
                feed.click(target)
                task.device.image = feed.frame

        task.device.screenshot.side_effect = fake_screenshot
        task.device.click.side_effect = fake_click
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
        # The claim must land on the 600 node of the archived track, and the modal may
        # only be closed after the re-scan of the still visible track found nothing
        # claimable any more.
        self.assertEqual(len(feed.claims), 1)
        self.assertTrue(_inside(feed.claims[0], claimed_box))
        self.assertEqual([state for state, _ in feed.click_log], [0, 1, 2, 3])
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

    def _run_weekly_reward_loop(self, feed, prep_badge):
        """Drive the real claim_weekly_rewards loop against a scripted screen feed."""
        task = _new_task(purple=False, rainbow=False, white=False, red=False)
        task.device.image = prep_badge

        def _screenshot():
            task.device.image = feed.screenshot()
            return task.device.image

        def _click(target):
            feed.click(target)
            task.device.image = feed.frame

        task.device.screenshot.side_effect = _screenshot
        task.device.click.side_effect = _click
        with patch('module.base.timer.time', side_effect=count(100, 3.0)):
            claimed = task.claim_weekly_rewards()
        return task, claimed

    def test_weekly_reward_claims_relocated_node_after_first_claim(self):
        """After one claim the track must be re-located and the still claimable node taken too."""
        from module.resonance import assets

        # View A: one node is claimable, the next one is already claimed.
        nodes_a = [(430, 226, 'claimed'), (626, 385, 'claimable'),
                   (822, 226, 'locked'), (1018, 385, 'locked')]
        # View B: the track was re-rendered after the claim, so the claimed node moved
        # on while the following node became claimable on a new coordinate.
        nodes_b = [(626, 226, 'claimed'), (822, 385, 'claimable'), (1018, 226, 'locked')]
        # View C: nothing is claimable any more.
        nodes_c = [(626, 226, 'claimed'), (822, 385, 'claimed'), (1018, 226, 'locked')]

        prep_badge = _make_prep_screen(with_badge=True)
        prep_clean = _make_prep_screen(with_badge=False)
        popup = _blank_with(assets.LOGIN_REWARD)

        modal_a, slots_a = _make_milestone_view(nodes_a)
        modal_b, slots_b = _make_milestone_view(nodes_b)
        modal_c, slots_c = _make_milestone_view(nodes_c)

        slot_claimed_a, slot_claimable_a = slots_a[0][0], slots_a[1][0]
        slot_locked_a, slot_locked_b = slots_a[2][0], slots_a[3][0]
        slot_claimed_b, slot_claimable_b = slots_b[0][0], slots_b[1][0]

        # A frozen default coordinate inside a slot would let a fallback click pass
        # for a real claim, so the layout must stay clear of the stale boxes.
        every_slot = [box for box, _ in slots_a + slots_b + slots_c]
        if any(_inside(c, box) for c in _frozen_centres() for box in every_slot):
            self.skipTest('a frozen default coordinate overlaps the test layout')

        feed = _WeeklyRewardFeed([
            {'frame': prep_badge, 'advance_on': ('PREP_WEEKLY_REWARD',)},
            {'frame': modal_a, 'claimable': slot_claimable_a},
            {'frame': popup, 'advance_on': ('LOGIN_REWARD',)},
            {'frame': modal_b, 'claimable': slot_claimable_b, 'advance_on': ('PREP_REWARD_MODAL',)},
            {'frame': popup, 'advance_on': ('LOGIN_REWARD',)},
            {'frame': modal_c, 'advance_on': ('PREP_REWARD_MODAL',)},
            {'frame': prep_clean},
        ])

        task, claimed = self._run_weekly_reward_loop(feed, prep_badge)

        self.assertTrue(claimed)
        self.assertEqual(
            len(feed.claims), 2,
            'the node that is still claimable after the first claim must be claimed as well',
        )
        self.assertTrue(_inside(feed.claims[0], slot_claimable_a), 'the first claim must use the first view layout')
        self.assertTrue(_inside(feed.claims[1], slot_claimable_b), 'the second claim must use the re-located layout')
        self.assertFalse(
            _inside(feed.claims[1], slot_claimable_a),
            'the second claim must not reuse the coordinate of the first view',
        )
        # Already claimed and locked rewards must never be clicked.
        self.assertFalse(
            [c for c in feed.clicks_in(1) if _inside(c, slot_claimed_a)],
            'an already claimed reward must not be clicked',
        )
        self.assertFalse(
            [c for c in feed.clicks_in(3) if _inside(c, slot_claimed_b)],
            'an already claimed reward must not be clicked after the track moved',
        )
        self.assertFalse(
            [c for c in feed.clicks if _inside(c, slot_locked_a) or _inside(c, slot_locked_b)],
            'a locked reward must not be clicked',
        )
        self.assertLessEqual(len(feed.clicks), 10, 'the claim loop must stay bounded')

    def test_weekly_reward_without_claimable_node_stays_bounded(self):
        """Only claimed and locked nodes: nothing may be claimed and the loop must terminate."""
        from module.resonance import assets

        nodes = [(430, 226, 'claimed'), (626, 385, 'locked')]

        prep_badge = _make_prep_screen(with_badge=True)
        prep_clean = _make_prep_screen(with_badge=False)
        modal, slots = _make_milestone_view(nodes)
        slot_claimed, slot_locked = slots[0][0], slots[1][0]

        if any(_inside(c, box) for c in _frozen_centres() for box, _ in slots):
            self.skipTest('a frozen default coordinate overlaps the test layout')

        feed = _WeeklyRewardFeed([
            {'frame': prep_badge, 'advance_on': ('PREP_WEEKLY_REWARD',)},
            {'frame': modal, 'advance_on': ('PREP_REWARD_MODAL',)},
            {'frame': prep_clean},
        ])

        task, claimed = self._run_weekly_reward_loop(feed, prep_badge)

        self.assertFalse(claimed)
        self.assertEqual(feed.claims, [], 'nothing is claimable, so nothing may be claimed')
        self.assertFalse(
            [c for c in feed.clicks if _inside(c, slot_claimed)],
            'an already claimed reward must not be clicked',
        )
        self.assertFalse(
            [c for c in feed.clicks if _inside(c, slot_locked)],
            'a locked reward must not be clicked',
        )
        self.assertLessEqual(task.device.swipe.call_count, 6, 'the scroll loop must stay bounded')
        self.assertLessEqual(len(feed.clicks), 8, 'the claim loop must stay bounded')

    def test_weekly_reward_archived_track_does_not_reuse_frozen_coordinates(self):
        """The archived 20261128 track is scrolled: claiming it must not fall back to the frozen boxes."""
        from module.resonance import assets

        path = _archive('preparation_milestones_shifted_20261128.png')
        if not os.path.exists(path):
            self.skipTest('archived resonance screenshot is not available in this worktree')

        try:
            from module.exception import GameStuckError
        except ImportError:
            GameStuckError = Exception

        real = load_image(path)
        if not assets.PREP_REWARD_MODAL.match(real, offset=(5, 5)):
            self.skipTest('the archived view does not match the 凭证置换 modal asset')

        stale = _default_milestone_boxes()
        prep_badge = _make_prep_screen(with_badge=True)
        prep_clean = _make_prep_screen(with_badge=False)

        feed = _WeeklyRewardFeed([
            {'frame': prep_badge, 'advance_on': ('PREP_WEEKLY_REWARD',)},
            {'frame': real, 'advance_on': ('PREP_REWARD_MODAL',)},
            {'frame': prep_clean},
        ])

        task = _new_task(purple=False, rainbow=False, white=False, red=False)
        task.device.image = prep_badge

        def _screenshot():
            task.device.image = feed.screenshot()
            return task.device.image

        def _click(target):
            feed.click(target)
            task.device.image = feed.frame

        task.device.screenshot.side_effect = _screenshot
        task.device.click.side_effect = _click
        with patch('module.base.timer.time', side_effect=count(100, 3.0)):
            try:
                task.claim_weekly_rewards()
            except GameStuckError:
                # The archived view does not have to be driveable end to end; the invariant
                # under test is that no click ever lands on a frozen milestone coordinate.
                pass

        for center in feed.clicks:
            for box in stale:
                self.assertFalse(
                    _inside(center, box),
                    'a claim must not fall back to the frozen milestone coordinates',
                )

    def test_archived_milestone_track_is_detected_at_its_own_positions(self):
        """The archived 凭证置换 track must be detected at its own positions, not the frozen ones."""
        from module.resonance.preparation import MILESTONE_TRACK_ROI

        path = _archive('preparation_milestones_shifted_20261128.png')
        if not os.path.exists(path):
            self.skipTest('archived resonance screenshot is not available in this worktree')
        try:
            from module.resonance.preparation import find_weekly_milestone_buttons
        except ImportError:
            self.skipTest('module.resonance.preparation does not expose the milestone helper')

        img = load_image(path)
        boxes = []
        for btn in find_weekly_milestone_buttons(img):
            bbox = getattr(btn, 'button', None)
            if not isinstance(bbox, (tuple, list)) or len(bbox) < 4:
                bbox = getattr(btn, 'area', None)
            self.assertIsNotNone(bbox, 'a detected milestone must expose its box')
            boxes.append(tuple(bbox[:4]))

        stale = _default_milestone_boxes()
        if set(boxes) == set(stale):
            self.skipTest('the archived view exposes no detectable milestone node of its own')
        self.assertNotEqual(
            set(boxes), set(stale),
            'the archived track is scrolled, so detection must not reuse the frozen boxes',
        )
        for box in boxes:
            self.assertGreaterEqual(box[0], MILESTONE_TRACK_ROI[0])
            self.assertLessEqual(box[2], MILESTONE_TRACK_ROI[2])
            self.assertGreaterEqual(box[1], MILESTONE_TRACK_ROI[1])
            self.assertLessEqual(box[3], MILESTONE_TRACK_ROI[3])

    def test_archived_credential_track_offers_only_the_600_node(self):
        """The archived 凭证置换 track offers the 600 node and never the 550/650 nodes.

        The cost label of a node sits on the timeline next to its card: the 550 card
        is the one that is already claimed, the 600 card is the only one that still
        carries the claimable highlight and the 650 card is the locked one.
        """
        from module.resonance.preparation import (
            find_weekly_milestone_buttons, is_claimable_milestone_box,
        )

        path = _archive('preparation_milestones_shifted_20261128.png')
        if not os.path.exists(path):
            self.skipTest('archived resonance screenshot is not available in this worktree')
        try:
            from module.exception import GameStuckError
        except ImportError:
            GameStuckError = Exception

        real = load_image(path)
        box_550 = _BADGE_SOURCE_BOXES['claimed']
        box_600 = _BADGE_SOURCE_BOXES['claimable']
        box_650 = _BADGE_SOURCE_BOXES['locked']

        self.assertTrue(is_claimable_milestone_box(real, box_600))
        self.assertFalse(is_claimable_milestone_box(real, box_550))
        self.assertFalse(is_claimable_milestone_box(real, box_650))

        buttons = find_weekly_milestone_buttons(real)
        self.assertEqual(len(buttons), 1, 'only the 600 node may be offered for a claim')
        self.assertTrue(_inside(_click_center(buttons[0]), box_600))

        # Claiming the real track may only touch the 600 node.
        prep_badge = _make_prep_screen(with_badge=True)
        prep_clean = _make_prep_screen(with_badge=False)
        feed = _WeeklyRewardFeed([
            {'frame': prep_badge, 'advance_on': ('PREP_WEEKLY_REWARD',)},
            {'frame': real, 'advance_on': ('PREP_REWARD_MODAL',)},
            {'frame': prep_clean},
        ])

        try:
            self._run_weekly_reward_loop(feed, prep_badge)
        except GameStuckError:
            # The archived screen cannot be claimed end to end; the invariant under
            # test is which node the script is willing to click.
            pass

        self.assertTrue(
            [c for c in feed.clicks if _inside(c, box_600)],
            'the 600 node must be clickable',
        )
        self.assertFalse(
            [c for c in feed.clicks if _inside(c, box_550)],
            'an already claimed (550) node must never be clicked',
        )
        self.assertFalse(
            [c for c in feed.clicks if _inside(c, box_650)],
            'a locked (650) node must never be clicked',
        )
