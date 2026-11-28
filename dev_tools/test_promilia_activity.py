"""Offline regressions for Promilia's daily-activity reward flow."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.base.utils import load_image
from module.config import server
from module.exception import TaskFailed


_IMPORT_SERVER = server.server
try:
    server.set_server('promilia')

    from module.promilia.activity import (ACTIVITY_BOXES, ACTIVITY_OFFSET,  # noqa: E402
                                          PromiliaActivity)
    from module.promilia.activity_scroll import (ACTIVITY_SCROLL_TRACK,  # noqa: E402
                                                PromiliaActivityScroll)
    from module.promilia.assets import (ACTIVITY_BOX_100, ACTIVITY_BOX_20,  # noqa: E402
                                        ACTIVITY_BOX_40, ACTIVITY_BOX_60,
                                        ACTIVITY_BOX_80, ACTIVITY_CLOSE,
                                        ACTIVITY_DAILY_ACTIVE,
                                        ACTIVITY_DAILY_TAB,
                                        ACTIVITY_ENTRY,
                                        ACTIVITY_REWARD_CLOSE,
                                        ACTIVITY_REWARD_TITLE,
                                        ACTIVITY_TASK_CLAIM,
                                        ACTIVITY_TASK_ONGOING, ACTIVITY_TASK_UPDATED,
                                        ACTIVITY_WEEKLY_ACTIVE, MAIN_ICONS)
    from module.promilia.page import page_activity, page_main  # noqa: E402
    from module.promilia.promilia_ui import PromiliaUI  # noqa: E402
finally:
    server.set_server(_IMPORT_SERVER)


ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / 'screenshots' / 'promilia'
ASSETS = (ACTIVITY_BOX_100, ACTIVITY_BOX_20, ACTIVITY_BOX_40,
          ACTIVITY_BOX_60, ACTIVITY_BOX_80, ACTIVITY_CLOSE,
          ACTIVITY_DAILY_ACTIVE, ACTIVITY_DAILY_TAB, ACTIVITY_ENTRY,
          ACTIVITY_REWARD_CLOSE, ACTIVITY_REWARD_TITLE,
          ACTIVITY_TASK_CLAIM, ACTIVITY_TASK_ONGOING, ACTIVITY_TASK_UPDATED,
          ACTIVITY_WEEKLY_ACTIVE, MAIN_ICONS)


class PromiliaActivityTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('promilia')
        for asset in ASSETS:
            self.addCleanup(asset.clear_offset)
        self.daily_points = load_image(str(SHOTS / 'activity_daily_points.png'))
        self.daily_boxes = load_image(str(SHOTS / 'activity_daily_boxes.png'))
        self.weekly = load_image(str(SHOTS / 'activity_weekly.png'))
        self.popup_early = load_image(str(SHOTS / 'activity_popup_early.png'))
        self.popup = load_image(str(SHOTS / 'activity_popup.png'))
        self.world = load_image(str(SHOTS / 'activity_world.png'))
        self.main = load_image(str(SHOTS / 'promilia_main.png'))
        self.blank = np.zeros_like(self.daily_points)
        self.now = [1000.0]
        clock = patch('module.base.timer.time', side_effect=lambda: self.now[0])
        clock.start()
        self.addCleanup(clock.stop)

    def _make_ui(self, image, frames=None):
        ui = PromiliaActivity.__new__(PromiliaActivity)
        ui.config = SimpleNamespace(
            BUTTON_OFFSET=(20, 20),
            Emulator_ControlMethod='ADB',
            Emulator_ScreenshotMethod='ADB',
            task_delay=Mock(),
        )
        ui.interval_timer = {}
        ui.device = SimpleNamespace(
            image=image,
            has_cached_image=True,
            click=Mock(),
            screenshot=Mock(),
            swipe=Mock(),
            click_record_clear=Mock(),
            stuck_record_add=Mock(),
            stuck_record_clear=Mock(),
            app_is_running=Mock(return_value=True),
            get_orientation=Mock(),
        )
        iterator = iter(frames) if frames is not None else None

        def screenshot():
            self.now[0] += 0.1
            if iterator is not None:
                try:
                    ui.device.image = next(iterator)
                except StopIteration:
                    pass

        ui.device.screenshot.side_effect = screenshot
        return ui

    def _clicks(self, ui):
        return [call[0][0] for call in ui.device.click.call_args_list]

    def _matches(self, button, frames):
        return [self._make_ui(frame).appear(button, offset=ACTIVITY_OFFSET)
                for frame in frames]

    def _rows(self, *states):
        image = self.daily_points.copy()
        sources = {
            'claim': self.daily_points[160:202, 1115:1180],
            'goto': self.daily_boxes[160:202, 1115:1180],
            'ongoing': self.daily_points[386:428, 1115:1180],
        }
        for index, state in enumerate(states):
            y = 160 + index * 113
            image[y:y + 42, 1115:1180] = sources[state]
        return image

    def _scrolled(self, image, position, rows=None):
        """Synthetic later window with a measured thumb and chosen row states."""
        frame = image.copy()
        x1, y1, x2, y2 = ACTIVITY_SCROLL_TRACK
        thumb = self.daily_points[y1:y1 + 139, x1:x2]
        background = np.resize(self.daily_points[y1 + 166:y1 + 305, x1:x2],
                               (y2 - y1, x2 - x1, 3))
        frame[y1:y2, x1:x2] = background
        start = int(round(position * (y2 - y1 - 139)))
        frame[y1 + start:y1 + start + 139, x1:x2] = thumb
        if rows is not None:
            states = self._rows(*rows)
            for index in range(4):
                y = 160 + index * 113
                frame[y:y + 42, 1115:1180] = states[y:y + 42, 1115:1180]
        return frame

    def _offscreen_window(self, image, bottom_state):
        """Move the list up one row and bring a synthetic fifth card into view."""
        frame = image.copy()
        panel = frame[133:573, 500:1248].copy()
        frame[133:460, 500:1248] = panel[113:]
        frame[462:563, 500:1095] = image[133:234, 500:1095]
        source = self.daily_points if bottom_state == 'claim' else self.daily_boxes
        frame[499:541, 1115:1200] = source[160:202, 1115:1200]
        return frame

    def test_page_graph_registers_activity_and_both_links(self):
        self.assertIs(PromiliaActivity.page_main, page_main)
        self.assertEqual(PromiliaUI.pages, (page_main, page_activity))
        self.assertIs(PromiliaActivity.pages, PromiliaUI.pages)
        self.assertEqual(page_main.links[page_activity], ACTIVITY_ENTRY)
        self.assertEqual(page_activity.links[page_main], ACTIVITY_CLOSE)

    def test_static_assets_do_not_cross_hit(self):
        cases = (
            (ACTIVITY_DAILY_ACTIVE, (self.daily_points, self.daily_boxes,
                                     self.weekly, self.popup, self.world),
             (True, True, False, False, False)),
            (ACTIVITY_WEEKLY_ACTIVE, (self.daily_points, self.weekly,
                                      self.popup, self.world),
             (False, True, False, False)),
            (ACTIVITY_TASK_CLAIM, (self.daily_points, self.daily_boxes,
                                   self.weekly, self.popup),
             (True, False, False, False)),
            (ACTIVITY_TASK_UPDATED, (self.daily_points, self.daily_boxes,
                                     self.popup_early, self.popup),
             (False, True, False, False)),
            (ACTIVITY_REWARD_TITLE, (self.daily_boxes, self.popup_early,
                                     self.popup),
             (False, True, True)),
            (ACTIVITY_REWARD_CLOSE, (self.daily_boxes, self.popup_early,
                                     self.popup),
             (False, True, True)),
            (ACTIVITY_ENTRY, (self.world, self.main, self.daily_boxes),
             (True, True, False)),
        )
        for button, frames, expected in cases:
            self.assertEqual(tuple(self._matches(button, frames)), expected, button.name)

    def test_weekly_switches_to_daily_without_claiming(self):
        ui = self._make_ui(self.weekly, [self.daily_points])

        self.assertTrue(ui.activity_ensure_daily())
        self.assertEqual(self._clicks(ui), [ACTIVITY_DAILY_TAB])

    def test_daily_switch_waits_through_a_transient_missing_criterion(self):
        lost = self.daily_points.copy()
        lost[33:67, 430:585] = 0
        ui = self._make_ui(self.weekly, [lost, self.daily_points])

        self.assertTrue(ui.activity_ensure_daily())
        self.assertEqual(self._clicks(ui), [ACTIVITY_DAILY_TAB])

    def test_points_claim_waits_for_stable_list_after_update(self):
        ui = self._make_ui(self.daily_points,
                           [self.daily_points, self.daily_boxes,
                            self.daily_boxes, self.daily_boxes])

        self.assertTrue(ui.activity_claim_points())
        self.assertEqual(self._clicks(ui), [ACTIVITY_TASK_CLAIM])

    def test_task_state_scan_separates_all_daily_rows(self):
        cases = (
            (self.daily_points, ('claim', 'goto', 'ongoing', 'ongoing')),
            (self.daily_boxes, ('goto', 'ongoing', 'ongoing', 'ongoing')),
            (self.weekly, ()),
        )
        for image, expected in cases:
            ui = self._make_ui(image)
            self.assertEqual(tuple(state for _, state in ui.activity_task_states()), expected)

    def test_claim_scan_finds_second_and_third_rows_not_goto(self):
        ui = self._make_ui(self._rows('goto', 'claim', 'claim', 'ongoing'))

        self.assertEqual([area[1] for area in ui.activity_find_claims()], [273, 386])

    def test_points_wait_for_a_late_first_claim(self):
        late = self._rows('goto', 'ongoing', 'ongoing', 'ongoing')
        ui = self._make_ui(late, [late, late, self.daily_points, self.daily_boxes])

        self.assertTrue(ui.activity_claim_points())
        self.assertEqual(self._clicks(ui), [ACTIVITY_TASK_CLAIM])

    def test_points_claim_second_and_third_rows(self):
        initial = self._rows('goto', 'claim', 'claim', 'ongoing')
        after_first = self._rows('goto', 'goto', 'claim', 'ongoing')
        done = self._rows('goto', 'goto', 'goto', 'ongoing')
        ui = self._make_ui(initial, [initial, after_first, done])
        self.assertTrue(ui.activity_claim_points())
        self.assertEqual([click.button[1] for click in self._clicks(ui)], [273, 386])

    def test_points_claim_same_position_next_row(self):
        initial = self._rows('claim', 'claim', 'ongoing', 'ongoing')
        after_first = self._rows('claim', 'goto', 'ongoing', 'ongoing')
        after_first[160:202, 330:1095] = self.daily_points[273:315, 330:1095]
        done = self._rows('goto', 'goto', 'ongoing', 'ongoing')
        ui = self._make_ui(initial, [initial, after_first, done])
        self.assertTrue(ui.activity_claim_points())
        self.assertEqual([click.button[1] for click in self._clicks(ui)], [160, 160])

    def test_points_claim_accepts_same_position_replacement(self):
        initial = self._rows('claim', 'ongoing', 'ongoing', 'ongoing')
        replacement = initial.copy()
        replacement[160:202, 330:1095] = self.daily_points[273:315, 330:1095]
        done = self._rows('goto', 'ongoing', 'ongoing', 'ongoing')
        ui = self._make_ui(initial, [initial, replacement, done])

        self.assertTrue(ui.activity_claim_points())
        self.assertEqual([click.button[1] for click in self._clicks(ui)], [160, 160])

    def test_points_claim_accepts_ongoing_successor(self):
        initial = self._rows('claim', 'ongoing', 'ongoing', 'ongoing')
        done = self._rows('ongoing', 'ongoing', 'ongoing', 'ongoing')
        ui = self._make_ui(initial, [initial, done])

        self.assertTrue(ui.activity_claim_points())
        self.assertEqual(len(self._clicks(ui)), 1)

    def test_points_claim_retries_a_swallowed_click(self):
        initial = self._rows('claim', 'ongoing', 'ongoing', 'ongoing')
        done = self._rows('ongoing', 'ongoing', 'ongoing', 'ongoing')
        ui = self._make_ui(initial, [initial, initial, initial, done])
        timer = SimpleNamespace(reached=Mock(side_effect=[True, False, True, False]), reset=Mock())
        ui.get_interval_timer = Mock(return_value=timer)

        self.assertTrue(ui.activity_claim_points())
        self.assertEqual([click.button[1] for click in self._clicks(ui)], [160, 160])

    def test_single_frame_disappearance_is_not_a_claim_receipt(self):
        initial = self._rows('claim', 'ongoing', 'ongoing', 'ongoing')
        occluded = initial.copy()
        occluded[140:570, 300:1200] = 0
        ui = self._make_ui(initial, [initial, occluded])
        now = [0.0]

        def screenshot():
            ui.device.image = initial
            if ui.device.screenshot.call_count > 1:
                ui.device.image = occluded
            now[0] += 0.1

        ui.device.screenshot.side_effect = screenshot
        with patch('module.base.timer.time', side_effect=lambda: now[0]):
            with self.assertRaises(TaskFailed):
                ui.activity_claim_points(timeout=0.25)
        ui.config.task_delay.assert_called_once_with(success=False)

    def test_updated_row_without_claim_button_is_a_noop(self):
        ui = self._make_ui(self.daily_boxes)

        self.assertFalse(ui.activity_claim_points(claim_wait=0))
        ui.device.click.assert_not_called()

    def test_claim_loop_rechecks_readiness_after_initial_empty_window(self):
        occluded = self.daily_boxes.copy()
        occluded[140:570, 300:1200] = 0
        partial = self.daily_points.copy()
        partial[386:428, 1115:1180] = 0
        frames = ([self.daily_boxes] * 7 + [occluded, partial, self.daily_points]
                  + [self.daily_boxes] * 7)
        ui = self._make_ui(self.daily_boxes, frames)

        self.assertTrue(ui.activity_claim_points())
        self.assertEqual([click.button[1] for click in self._clicks(ui)], [160])

    def test_character_animation_is_not_a_claim_receipt(self):
        initial = self._rows('claim', 'ongoing', 'ongoing', 'ongoing')
        moving = initial.copy()
        moving[:, 330:500] = np.roll(moving[:, 330:500], 2, axis=1)
        ui = self._make_ui(initial, [moving] * 5)

        with self.assertRaises(TaskFailed):
            ui.activity_claim_points(timeout=0.35)
        self.assertEqual(len(self._clicks(ui)), 1)
        ui.config.task_delay.assert_called_once_with(success=False)

    def test_empty_readiness_needs_consecutive_frames_and_elapsed_time(self):
        for frames, timeout in (([self.daily_boxes] * 4, 0.3),
                                ([self.daily_boxes, self.blank] * 4, 0.8)):
            ui = self._make_ui(self.daily_boxes, frames)
            with self.subTest(timeout=timeout):
                with self.assertRaises(TaskFailed):
                    ui.activity_claim_points(timeout=timeout)
                ui.device.click.assert_not_called()
                ui.config.task_delay.assert_called_once_with(success=False)

    def test_box_badges_match_only_lit_daily_milestones(self):
        expected = {
            'activity_daily_points': (True, True, True, False, False),
            'activity_daily_boxes': (True, True, True, True, False),
            'activity_weekly': (False, False, False, False, False),
        }
        images = {
            'activity_daily_points': self.daily_points,
            'activity_daily_boxes': self.daily_boxes,
            'activity_weekly': self.weekly,
        }
        for name, image in images.items():
            ui = self._make_ui(image)
            actual = tuple(ui.activity_box_has_badge(badge)
                           for _, badge in ACTIVITY_BOXES)
            self.assertEqual(actual, expected[name], name)

    def test_no_lit_boxes_means_no_click(self):
        image = self.daily_boxes.copy()
        for _, badge in ACTIVITY_BOXES:
            x1, y1, x2, y2 = badge
            image[y1:y2, x1:x2] = 0
        ui = self._make_ui(image)

        self.assertFalse(ui.activity_claim_box())
        ui.device.click.assert_not_called()

    def test_box_waits_for_a_late_badge(self):
        unlit = self.daily_boxes.copy()
        for _, badge in ACTIVITY_BOXES:
            x1, y1, x2, y2 = badge
            unlit[y1:y2, x1:x2] = 0
        ui = self._make_ui(unlit,
                           [unlit, self.daily_boxes, self.popup_early,
                            self.popup, self.daily_boxes, self.daily_boxes])

        self.assertTrue(ui.activity_claim_box())
        self.assertEqual(self._clicks(ui), [ACTIVITY_BOX_20, ACTIVITY_REWARD_CLOSE])

    def test_badge_arriving_after_ready_window_is_not_clicked(self):
        unlit = self.daily_boxes.copy()
        for _, badge in ACTIVITY_BOXES:
            x1, y1, x2, y2 = badge
            unlit[y1:y2, x1:x2] = 0
        ui = self._make_ui(unlit, [unlit] * 7 + [self.daily_boxes])

        self.assertFalse(ui.activity_claim_box())
        ui.device.click.assert_not_called()

    def test_boxes_require_complete_scan_and_live_bottom(self):
        bottom = self._scrolled(self.daily_boxes, 1.0)
        unlit_bottom = bottom.copy()
        for _, badge in ACTIVITY_BOXES:
            x1, y1, x2, y2 = badge
            unlit_bottom[y1:y2, x1:x2] = 0
        top = self.daily_boxes
        for complete, image, frames in (
                (False, bottom, []), (True, top, []),
                (True, unlit_bottom, [top])):
            ui = self._make_ui(image, frames)
            ui._activity_points_complete = complete
            scroll = PromiliaActivityScroll(ui)
            with self.subTest(complete=complete, image=image.shape):
                with self.assertRaises(TaskFailed):
                    ui.activity_claim_box(scroll=scroll)
                ui.device.click.assert_not_called()
                ui.config.task_delay.assert_called_once_with(success=False)

    def test_only_100_badge_clicks_100_with_gray_box_art(self):
        # Synthetic lit state: only the same-layout 100 badge is present; the box art stays gray.
        image = self.daily_boxes.copy()
        for _, badge in ACTIVITY_BOXES:
            x1, y1, x2, y2 = badge
            image[y1:y2, x1:x2] = 0
        x1, y1, x2, y2 = ACTIVITY_BOXES[-1][1]
        image[y1:y2, x1:x2] = (255, 0, 0)
        ui = self._make_ui(image, [self.popup_early, self.popup, image, image])

        self.assertTrue(ui.activity_claim_box())
        self.assertEqual(self._clicks(ui), [ACTIVITY_BOX_100, ACTIVITY_REWARD_CLOSE])

    def test_red_artwork_outside_badges_does_not_click(self):
        image = self.daily_boxes.copy()
        for _, badge in ACTIVITY_BOXES:
            x1, y1, x2, y2 = badge
            image[y1:y2, x1:x2] = 0
        image[560:650, 100:300] = (255, 0, 0)
        ui = self._make_ui(image)

        self.assertFalse(ui.activity_claim_box())
        ui.device.click.assert_not_called()

    def test_weekly_cannot_claim_points_or_boxes_directly(self):
        ui = self._make_ui(self.weekly)
        with patch('module.promilia.activity.ACTIVITY_POINT_WAIT', 0):
            self.assertFalse(ui.activity_claim_points(claim_wait=0))
            self.assertFalse(ui.activity_claim_box())
        ui.device.click.assert_not_called()

    def test_lit_box_clicks_once_and_closes_delayed_popup(self):
        ui = self._make_ui(self.daily_boxes,
                           [self.daily_boxes, self.popup_early, self.popup,
                            self.popup, self.daily_boxes, self.daily_boxes])

        self.assertTrue(ui.activity_claim_box())
        self.assertEqual(self._clicks(ui), [ACTIVITY_BOX_20, ACTIVITY_REWARD_CLOSE])

    def test_reward_handler_never_clicks_twice_on_consecutive_frames(self):
        ui = self._make_ui(self.popup_early)

        self.assertTrue(ui.handle_activity_reward())
        ui.device.image = self.popup
        self.assertTrue(ui.handle_activity_reward())
        self.assertEqual(self._clicks(ui), [ACTIVITY_REWARD_CLOSE])
        ui.device.image = self.daily_boxes
        self.assertFalse(ui.handle_activity_reward())
        self.assertTrue(ui._activity_reward_closing)
        self.assertFalse(ui.handle_activity_reward())
        self.assertFalse(ui._activity_reward_closing)

    def test_reward_handler_survives_intermittent_frames_without_double_close(self):
        ui = self._make_ui(self.popup_early)

        self.assertTrue(ui.handle_activity_reward())
        for frame, expected in ((self.daily_boxes, False), (self.popup, True),
                                (self.blank, False), (self.daily_boxes, False),
                                (self.daily_boxes, False)):
            ui.device.image = frame
            self.assertEqual(ui.handle_activity_reward(), expected)
        self.assertEqual(self._clicks(ui), [ACTIVITY_REWARD_CLOSE])
        self.assertFalse(ui._activity_reward_closing)

    def test_reward_timeout_is_a_failed_attempt(self):
        ui = self._make_ui(self.daily_boxes)

        with self.assertRaises(TaskFailed):
            ui.activity_wait_reward(timeout=0)
        ui.config.task_delay.assert_called_once_with(success=False)
        ui.device.click.assert_not_called()

    def test_points_timeout_is_a_failed_attempt(self):
        ui = self._make_ui(self.daily_points)

        with self.assertRaises(TaskFailed):
            ui.activity_claim_points(timeout=0, claim_wait=0)
        ui.config.task_delay.assert_called_once_with(success=False)

    def test_ui_additional_closes_leftover_reward(self):
        ui = self._make_ui(self.popup)

        self.assertTrue(ui.ui_additional())
        self.assertEqual(self._clicks(ui), [ACTIVITY_REWARD_CLOSE])

    def test_scan_failure_paths_delay_failed_attempt(self):
        ui = self._make_ui(self.weekly)
        with self.assertRaises(TaskFailed):
            ui.activity_claim_all_points()
        ui.device.swipe.assert_not_called()
        ui.config.task_delay.assert_called_once_with(success=False)

        ui = self._make_ui(self.daily_points)
        with self.assertRaises(TaskFailed):
            ui.activity_claim_all_points(timeout=0)
        ui.config.task_delay.assert_called_once_with(success=False)

        ui = self._make_ui(self.daily_points)
        fake_scroll = Mock()
        fake_scroll.set_top.return_value = True
        fake_scroll.at_bottom.return_value = False
        fake_scroll.next_page.return_value = True
        ui.activity_claim_points = Mock(return_value=False)
        with patch('module.promilia.activity.PromiliaActivityScroll', return_value=fake_scroll):
            with patch('module.promilia.activity.ACTIVITY_SCROLL_WINDOWS', 1):
                with self.assertRaises(TaskFailed):
                    ui.activity_claim_all_points()
        ui.config.task_delay.assert_called_once_with(success=False)

    def test_each_scan_creates_an_owned_scroll(self):
        ui = self._make_ui(self.daily_points)
        first, second = Mock(), Mock()
        for scroll in (first, second):
            scroll.set_top.return_value = True
            scroll.at_bottom.return_value = True
        ui.activity_claim_points = Mock(return_value=False)
        with patch('module.promilia.activity.PromiliaActivityScroll', side_effect=[first, second]) as factory:
            ui.activity_claim_all_points()
            ui.activity_claim_all_points()
        self.assertEqual(factory.call_count, 2)
        self.assertTrue(all(call[0][0] is ui for call in factory.call_args_list))
        self.assertIs(ui._activity_scroll, second)

    def test_scan_recalculates_after_claim_resets_thumb(self):
        top_claim = self.daily_points
        top_done = self.daily_boxes
        middle_claim = self._scrolled(self._offscreen_window(top_done, 'claim'), 0.3475)
        middle_done = self._scrolled(self._offscreen_window(top_done, 'goto'), 0.3475)
        lower = self._scrolled(middle_done, 0.6925)
        bottom = self._scrolled(middle_done, 1.0)
        scenes = [top_claim, top_done, middle_claim, top_done,
                  middle_done, lower, bottom]
        state = {'scene': 0, 'swipes': 0}

        ui = self._make_ui(top_claim)

        def click(button):
            if button.name == ACTIVITY_TASK_CLAIM.name:
                state['scene'] = 1 if state['scene'] == 0 else 3
                ui.device.image = scenes[state['scene']]

        def swipe(*args, **kwargs):
            state['scene'] = [2, 4, 5, 6][state['swipes']]
            state['swipes'] += 1
            ui.device.image = scenes[state['scene']]

        ui.device.click.side_effect = click
        ui.device.swipe.side_effect = swipe
        with patch('module.promilia.activity_scroll.random_rectangle_point',
                   side_effect=lambda area, n: ((area[0] + area[2]) // 2,
                                                (area[1] + area[3]) // 2)):
            self.assertTrue(ui.activity_claim_all_points())

        self.assertTrue(ui._activity_points_complete)
        self.assertEqual([click.button[1] for click in self._clicks(ui)], [160, 499])
        self.assertEqual(ui.device.swipe.call_count, 4)
        swipes = ui.device.swipe.call_args_list
        self.assertEqual(swipes[0][0][0], swipes[1][0][0])
        self.assertNotEqual(swipes[0][0][0], swipes[2][0][0])

    def test_scrolled_window_accepts_clipped_edge_cards(self):
        shifted = self.daily_boxes.copy()
        panel = shifted[133:573, 500:1248].copy()
        shifted[133:573, 500:1248] = shifted[240, 500]
        shifted[133:517, 500:1248] = panel[56:]
        frame = self._scrolled(shifted, 0.5)
        ui = self._make_ui(frame)
        scroll = PromiliaActivityScroll(ui)

        state = ui.activity_window_state(scroll)

        self.assertIsNotNone(state)
        self.assertEqual(len(state[2][1]), 3)
        self.assertEqual(len(state[1]), 3)

    def test_full_run_claims_visible_then_offscreen_rows_before_box(self):
        late = self._rows('goto', 'ongoing', 'ongoing', 'ongoing')
        shifted = self._offscreen_window(self.daily_boxes, 'claim')
        shifted_done = self._offscreen_window(self.daily_boxes, 'goto')
        middle = self._scrolled(shifted, 0.3475)
        middle_done = self._scrolled(shifted_done, 0.3475)
        lower = self._scrolled(shifted_done, 0.6925)
        bottom = self._scrolled(shifted_done, 1.0)
        frames = ([late] * 8 + [self.daily_points] + [self.daily_boxes] * 7
                  + [middle] * 3 + [middle_done] * 7 + [lower] * 15 + [bottom] * 15
                  + [self.popup_early, self.popup, bottom, bottom, self.world, self.world])
        ui = self._make_ui(self.world, frames)

        ui.run()

        clicks = self._clicks(ui)
        self.assertEqual([click.name for click in clicks], [
            ACTIVITY_ENTRY.name, ACTIVITY_TASK_CLAIM.name, ACTIVITY_TASK_CLAIM.name,
            ACTIVITY_BOX_20.name, ACTIVITY_REWARD_CLOSE.name, ACTIVITY_CLOSE.name,
        ])
        self.assertEqual([click.button[1] for click in clicks
                          if click.name == ACTIVITY_TASK_CLAIM.name], [160, 499])
        self.assertEqual(ui.device.swipe.call_count, 3)
        self.assertEqual(ui.device.click_record_clear.call_count, 3)
        self.assertTrue(np.array_equal(ui.device.image, self.world))
        ui.config.task_delay.assert_called_once_with(server_update=True)

    def test_full_run_swallowed_scroll_fails_without_opening_box(self):
        frames = [self.daily_points, self.daily_points, self.daily_points] + [self.daily_boxes] * 40
        ui = self._make_ui(self.world, frames)

        with self.assertRaises(TaskFailed):
            ui.run()

        self.assertEqual([click.name for click in self._clicks(ui)],
                         [ACTIVITY_ENTRY.name, ACTIVITY_TASK_CLAIM.name])
        self.assertEqual(ui.device.swipe.call_count, 1)
        ui.config.task_delay.assert_called_once_with(success=False)

    def test_full_run_occluded_window_fails_without_opening_box(self):
        occluded = self.daily_points.copy()
        occluded[140:570, 300:1200] = 0
        ui = self._make_ui(self.world, [self.daily_points] * 3 + [occluded] * 160)

        with self.assertRaises(TaskFailed):
            ui.run()

        self.assertEqual([click.name for click in self._clicks(ui)],
                         [ACTIVITY_ENTRY.name, ACTIVITY_TASK_CLAIM.name])
        ui.device.swipe.assert_not_called()
        ui.config.task_delay.assert_called_once_with(success=False)

    @staticmethod
    def _jitter_cards(image, seed):
        """Simulate subtle live frosted-glass background jitter across task cards."""
        out = image.copy()
        patch = out[133:573, 500:1095].astype(np.int16)
        delta = np.where((np.arange(patch.size).reshape(patch.shape) + seed) % 3 == 0, 1, 0)
        out[133:573, 500:1095] = np.clip(patch + delta, 0, 255).astype(np.uint8)
        return out

    def test_wait_ready_and_settle_tolerate_live_background_jitter(self):
        unlit_box = self.daily_boxes.copy()
        for _, badge in ACTIVITY_BOXES:
            x1, y1, x2, y2 = badge
            unlit_box[y1:y2, x1:x2] = 0

        frames = [self._jitter_cards(self.daily_boxes, idx) for idx in range(12)]
        ui = self._make_ui(frames[0], frames[1:])
        self.assertFalse(ui.activity_claim_points(timeout=2))
        ui.device.click.assert_not_called()

        box_frames = [self._jitter_cards(unlit_box, idx) for idx in range(10)]
        ui_box = self._make_ui(box_frames[0], box_frames[1:])
        self.assertFalse(ui_box.activity_claim_box(timeout=2))
        ui_box.device.click.assert_not_called()

    def test_click_claim_throttles_same_row_under_live_background_jitter(self):
        frames = ([self._jitter_cards(self.daily_points, idx) for idx in range(4)]
                  + [self._jitter_cards(self.daily_boxes, idx + 10) for idx in range(8)])
        ui = self._make_ui(frames[0], frames[1:])

        self.assertTrue(ui.activity_claim_points(timeout=3))
        self.assertEqual(len(self._clicks(ui)), 1)
        self.assertEqual(self._clicks(ui)[0].name, ACTIVITY_TASK_CLAIM.name)

    def test_settle_rejects_real_content_change_between_cards(self):
        swapped = self.daily_boxes.copy()
        swapped[133:234, 500:1095] = self.daily_boxes[246:347, 500:1095]
        swapped[246:347, 500:1095] = self.daily_boxes[133:234, 500:1095]
        frames = [self.daily_boxes, swapped] * 5
        ui = self._make_ui(self.daily_boxes, frames)

        with self.assertRaises(TaskFailed):
            ui.activity_claim_points(timeout=0.8)
        ui.config.task_delay.assert_called_once_with(success=False)


if __name__ == '__main__':
    unittest.main()
