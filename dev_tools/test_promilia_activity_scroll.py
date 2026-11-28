"""Offline regressions for Promilia's bounded daily-list scrolling primitive."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.base.base import ModuleBase
from module.base.utils import load_image
from module.config import server


_IMPORT_SERVER = server.server
try:
    server.set_server('promilia')
    from module.promilia.activity_scroll import (  # noqa: E402
        ACTIVITY_SCROLL_MIN_LENGTH, ACTIVITY_SCROLL_TRACK,
        PromiliaActivityScroll)
    from module.promilia.assets import ACTIVITY_DAILY_ACTIVE  # noqa: E402
finally:
    server.set_server(_IMPORT_SERVER)


ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / 'screenshots' / 'promilia'


def _center_point(area, n=1):
    return (area[0] + area[2]) // 2, (area[1] + area[3]) // 2


class PromiliaActivityScrollTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('promilia')
        self.addCleanup(ACTIVITY_DAILY_ACTIVE.clear_offset)
        self.daily_points = load_image(str(SHOTS / 'activity_daily_points.png'))
        self.daily_boxes = load_image(str(SHOTS / 'activity_daily_boxes.png'))
        self.scroll_failed = load_image(str(SHOTS / 'activity_scroll_failed_20261128.png'))
        self.weekly = load_image(str(SHOTS / 'activity_weekly.png'))
        self.popup = load_image(str(SHOTS / 'activity_popup.png'))
        self.blank = np.zeros_like(self.daily_points)

    def _synthetic_position(self, image, position):
        result = image.copy()
        x1, y1, x2, y2 = ACTIVITY_SCROLL_TRACK
        thumb = image[y1:y1 + 139, x1:x2].copy()
        background = np.resize(image[y1 + 166:y1 + 305, x1:x2], (y2 - y1, x2 - x1, 3))
        result[y1:y2, x1:x2] = background
        start = int(round(position * ((y2 - y1) - thumb.shape[0])))
        result[y1 + start:y1 + start + thumb.shape[0], x1:x2] = thumb
        return result

    def _empty_thumb(self):
        image = self.daily_points.copy()
        x1, y1, x2, y2 = ACTIVITY_SCROLL_TRACK
        background = np.resize(image[y1 + 166:y1 + 305, x1:x2], (y2 - y1, x2 - x1, 3))
        image[y1:y2, x1:x2] = background
        return image

    def _make_main(self, frames):
        main = ModuleBase.__new__(ModuleBase)
        main.config = SimpleNamespace(BUTTON_OFFSET=(20, 20), Emulator_ControlMethod='ADB')
        main.interval_timer = {}
        main.device = SimpleNamespace(
            image=frames[0],
            has_cached_image=True,
            click=Mock(),
            swipe=Mock(),
            screenshot=Mock(),
            stuck_record_add=Mock(),
            stuck_record_clear=Mock(),
        )
        iterator = iter(frames)
        now = [1000.0]

        def screenshot():
            now[0] += 0.1
            try:
                main.device.image = next(iterator)
            except StopIteration:
                pass

        main.device.screenshot.side_effect = screenshot
        main._test_now = now
        return main

    def _run_with_clock(self, main, callback):
        with patch('module.base.timer.time', side_effect=lambda: main._test_now[0]):
            with patch('module.promilia.activity_scroll.random_rectangle_point', side_effect=_center_point):
                return callback()

    def test_original_daily_frames_are_at_top(self):
        for frame in (self.daily_points, self.daily_boxes, self.scroll_failed):
            main = self._make_main([frame])
            scroll = PromiliaActivityScroll(main)
            self.assertAlmostEqual(scroll.position(), 0.0, places=2)
            self.assertTrue(scroll.at_top())
            self.assertFalse(scroll.at_bottom())
            self.assertTrue(scroll.set_top())
            main.device.swipe.assert_not_called()
            main.device.click.assert_not_called()

    def test_set_top_waits_for_latest_valid_frame_without_swipe(self):
        main = self._make_main([self.blank, self.blank, self.scroll_failed])
        scroll = PromiliaActivityScroll(main)

        self.assertTrue(self._run_with_clock(main, lambda: scroll.set_top(timeout=1)))
        self.assertEqual(main.device.screenshot.call_count, 3)
        self.assertAlmostEqual(scroll.position(), 0.0, places=2)
        main.device.swipe.assert_not_called()
        main.device.click.assert_not_called()

    def test_next_page_waits_for_ready_frame_before_one_swipe(self):
        first = self._synthetic_position(self.daily_points, 0.3475)
        main = self._make_main([self.blank, self.scroll_failed, first, first, first])
        scroll = PromiliaActivityScroll(main)

        self.assertTrue(self._run_with_clock(main, lambda: scroll.next_page(timeout=1)))
        self.assertEqual(main.device.swipe.call_count, 1)
        self.assertAlmostEqual(scroll.position(), 0.3475, delta=0.01)
        main.device.click.assert_not_called()

    def test_synthetic_middle_and_bottom_positions(self):
        for expected in (0.5, 1.0):
            frame = self._synthetic_position(self.daily_points, expected)
            scroll = PromiliaActivityScroll(self._make_main([frame]))
            self.assertAlmostEqual(scroll.position(), expected, delta=0.01)
            self.assertFalse(scroll.at_top())
            self.assertEqual(scroll.at_bottom(), expected == 1.0)

    def test_weekly_popup_and_unknown_frames_fail_gate_without_swipe(self):
        for name, frame in (('weekly', self.weekly), ('popup', self.popup), ('blank', self.blank)):
            for action in ('set_top', 'next_page'):
                with self.subTest(frame=name, action=action):
                    main = self._make_main([frame])
                    scroll = PromiliaActivityScroll(main)
                    self.assertIsNone(scroll.position())
                    self.assertFalse(scroll.at_top())
                    self.assertFalse(scroll.at_bottom())
                    self.assertFalse(self._run_with_clock(
                        main, lambda: getattr(scroll, action)(timeout=0.25)))
                    self.assertGreater(main.device.screenshot.call_count, 0)
                    main.device.swipe.assert_not_called()
                    main.device.click.assert_not_called()

    def test_empty_full_or_split_thumb_is_unknown_not_top(self):
        empty = self._empty_thumb()
        full = self.daily_points.copy()
        x1, y1, x2, y2 = ACTIVITY_SCROLL_TRACK
        full[y1:y2, x1:x2] = 255
        split = self.daily_points.copy()
        split[y1 + 66:y1 + 86, x1:x2] = empty[y1 + 166:y1 + 186, x1:x2]
        for frame in (empty, full, split):
            main = self._make_main([frame])
            scroll = PromiliaActivityScroll(main)
            self.assertIsNone(scroll.position())
            self.assertFalse(scroll.at_top())
            self.assertFalse(scroll.at_bottom())
            self.assertFalse(self._run_with_clock(main, lambda: scroll.next_page(timeout=0.25)))
            main.device.swipe.assert_not_called()

    def test_readiness_and_navigation_share_one_timeout(self):
        first = self._synthetic_position(self.daily_points, 0.3475)
        main = self._make_main([self.blank, self.blank, self.blank, first, first, first])
        scroll = PromiliaActivityScroll(main)

        self.assertFalse(self._run_with_clock(main, lambda: scroll.next_page(timeout=0.25)))
        self.assertEqual(main.device.screenshot.call_count, 3)
        self.assertIsNone(scroll.position())
        main.device.swipe.assert_not_called()
        main.device.click.assert_not_called()

    def test_next_page_advances_twice_with_overlap_and_stops(self):
        first = self._synthetic_position(self.daily_points, 0.3475)
        second = self._synthetic_position(self.daily_points, 0.6925)
        main = self._make_main([self.daily_points, first, first, first, second, second, second])
        scroll = PromiliaActivityScroll(main)

        self.assertTrue(self._run_with_clock(main, lambda: scroll.next_page(timeout=1)))
        self.assertTrue(self._run_with_clock(main, lambda: scroll.next_page(timeout=1)))
        self.assertEqual(main.device.swipe.call_count, 2)
        main.device.click.assert_not_called()

        total = ACTIVITY_SCROLL_TRACK[3] - ACTIVITY_SCROLL_TRACK[1]
        length = 139
        travel = total - length
        for call in main.device.swipe.call_args_list:
            p1, p2 = call[0]
            self.assertEqual(p1[0], 1254)
            self.assertEqual(p2[0], 1254)
            self.assertTrue(ACTIVITY_SCROLL_TRACK[1] <= p1[1] <= p2[1] <= ACTIVITY_SCROLL_TRACK[3])
            current = (p1[1] - ACTIVITY_SCROLL_TRACK[1] - length / 2) / travel
            target = (p2[1] - ACTIVITY_SCROLL_TRACK[1] - length / 2) / travel
            viewport_fraction = (target - current) * travel / length
            self.assertGreater(viewport_fraction, 0)
            self.assertLessEqual(viewport_fraction, 0.76)

    def test_short_tail_edge_drags_exceed_device_threshold(self):
        cases = (
            ('top', 0.034, self.daily_points, lambda scroll: scroll.set_top(timeout=1)),
            ('bottom', 0.966, self._synthetic_position(self.daily_points, 1.0),
             lambda scroll: scroll.next_page(timeout=1)),
        )
        for edge, current, destination, action in cases:
            near = self._synthetic_position(self.daily_points, current)
            main = self._make_main([near, destination, destination, destination])
            scroll = PromiliaActivityScroll(main)
            with self.subTest(edge=edge):
                self.assertTrue(self._run_with_clock(main, lambda: action(scroll)))
                p1, p2 = main.device.swipe.call_args[0]
                self.assertGreaterEqual(float(np.linalg.norm(np.subtract(p2, p1))), 10)
                if edge == 'top':
                    self.assertLess(p2[1], ACTIVITY_SCROLL_TRACK[1])
                else:
                    self.assertGreater(p2[1], ACTIVITY_SCROLL_TRACK[3])

    def test_next_page_recalculates_after_thumb_reset(self):
        top = self.daily_points
        first = self._synthetic_position(top, 0.3475)
        main = self._make_main([top, first, first, first])
        scroll = PromiliaActivityScroll(main)
        self.assertTrue(self._run_with_clock(main, lambda: scroll.next_page(timeout=1)))
        main.device.image = top
        reset_frames = iter([top, first, first, first])

        def screenshot():
            main._test_now[0] += 0.1
            try:
                main.device.image = next(reset_frames)
            except StopIteration:
                pass

        main.device.screenshot.side_effect = screenshot
        self.assertTrue(self._run_with_clock(main, lambda: scroll.next_page(timeout=1)))
        first_swipe, second_swipe = main.device.swipe.call_args_list
        self.assertEqual(first_swipe[0], second_swipe[0])

    def test_set_top_drags_up_from_synthetic_bottom(self):
        bottom = self._synthetic_position(self.daily_points, 1.0)
        main = self._make_main([bottom, self.daily_points, self.daily_points])
        scroll = PromiliaActivityScroll(main)

        self.assertTrue(self._run_with_clock(main, lambda: scroll.set_top(timeout=1)))
        self.assertEqual(main.device.swipe.call_count, 1)
        p1, p2 = main.device.swipe.call_args[0]
        self.assertGreater(p1[1], p2[1])
        self.assertTrue(scroll.at_top())
        main.device.click.assert_not_called()

    def test_next_page_at_bottom_is_idempotent(self):
        bottom = self._synthetic_position(self.daily_points, 1.0)
        main = self._make_main([bottom])
        scroll = PromiliaActivityScroll(main)
        self.assertTrue(scroll.next_page())
        main.device.swipe.assert_not_called()

    def test_zero_timeout_does_not_swipe(self):
        main = self._make_main([self._synthetic_position(self.daily_points, 0.5)])
        scroll = PromiliaActivityScroll(main)

        self.assertFalse(scroll.next_page(timeout=0))
        main.device.screenshot.assert_not_called()
        main.device.swipe.assert_not_called()

    def test_swallowed_drag_times_out_without_false_success(self):
        main = self._make_main([self.daily_points])
        scroll = PromiliaActivityScroll(main)

        self.assertFalse(self._run_with_clock(main, lambda: scroll.next_page(timeout=0.25)))
        self.assertEqual(main.device.swipe.call_count, 1)
        self.assertTrue(scroll.at_top())
        self.assertFalse(scroll.at_bottom())
        main.device.click.assert_not_called()

    def test_transient_missing_frame_after_drag_recovers(self):
        first = self._synthetic_position(self.daily_points, 0.3475)
        main = self._make_main([self.daily_points, self.blank, first, first, first])
        scroll = PromiliaActivityScroll(main)

        self.assertTrue(self._run_with_clock(main, lambda: scroll.next_page(timeout=1)))
        self.assertEqual(main.device.swipe.call_count, 1)
        self.assertAlmostEqual(scroll.position(), 0.3475, delta=0.01)

    def test_thumb_lost_after_drag_times_out(self):
        main = self._make_main([self.daily_points, self._empty_thumb()])
        scroll = PromiliaActivityScroll(main)

        self.assertFalse(self._run_with_clock(main, lambda: scroll.next_page(timeout=0.25)))
        self.assertEqual(main.device.swipe.call_count, 1)
        self.assertIsNone(scroll.position())

    def test_page_lost_after_drag_does_not_trigger_more_swipes(self):
        main = self._make_main([self.daily_points, self.weekly])
        scroll = PromiliaActivityScroll(main)

        self.assertFalse(self._run_with_clock(main, lambda: scroll.next_page(timeout=0.25)))
        self.assertEqual(main.device.swipe.call_count, 1)
        self.assertIsNone(scroll.position())

    def test_each_instance_owns_an_independent_scroll(self):
        first = PromiliaActivityScroll(self._make_main([self.daily_points]))
        second = PromiliaActivityScroll(self._make_main([self.daily_points]))
        self.assertIsNot(first._scroll, second._scroll)
        self.assertAlmostEqual(first.position(), 0.0, places=2)
        self.assertGreaterEqual(first._scroll.length, ACTIVITY_SCROLL_MIN_LENGTH)


if __name__ == '__main__':
    unittest.main()
