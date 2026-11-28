"""Offline frame-by-frame regressions for Promilia's loading boot flow."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.base.utils import load_image
from module.config import server
from module.exception import GameStuckError


_IMPORT_SERVER = server.server
try:
    server.set_server('promilia')

    from module.promilia.assets import LOGIN_START  # noqa: E402
    from module.promilia.login import LOGIN_START_TEXT  # noqa: E402
    from module.promilia.page import page_main  # noqa: E402
    from module.promilia.promilia_ui import PromiliaUI  # noqa: E402
finally:
    server.set_server(_IMPORT_SERVER)


ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / 'screenshots' / 'promilia'


class PromiliaLoginFramesTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('promilia')
        self.addCleanup(LOGIN_START.clear_offset)
        self.addCleanup(LOGIN_START_TEXT.clear_offset)
        self.login = load_image(str(SHOTS / 'promilia_login.png'))
        self.stuck = load_image(str(SHOTS / 'login_stuck_20261128_060647.png'))
        self.loading = load_image(str(SHOTS / 'promilia_loading.png'))
        self.main = load_image(str(SHOTS / 'promilia_main.png'))
        self.dialog = load_image(str(SHOTS / 'promilia_update_dialog.png'))
        self.download = load_image(str(SHOTS / 'promilia_resource_download.png'))
        self.activity = load_image(str(SHOTS / 'activity_daily_points.png'))

    def _make_ui(self, image, frames):
        ui = PromiliaUI.__new__(PromiliaUI)
        ui.config = SimpleNamespace(BUTTON_OFFSET=(20, 20))
        ui.interval_timer = {}
        ui.frame = None
        ui.device = SimpleNamespace(
            image=image,
            has_cached_image=True,
            click=Mock(),
            screenshot=Mock(),
            stuck_record_add=Mock(),
            stuck_record_clear=Mock(),
        )
        iterator = iter(frames)

        def screenshot():
            ui.frame = next(iterator)
            ui.device.image = ui.frame[1]

        ui.device.screenshot.side_effect = screenshot
        return ui

    def test_three_original_frames_clear_each_frame_and_only_login_clicks(self):
        loading_2 = np.clip(self.loading.astype(np.int16) + 5, 0, 255).astype(np.uint8)
        self.assertFalse(np.array_equal(self.loading, loading_2))
        frames = [
            ('login', self.login),
            ('loading_1', self.loading),
            ('loading_2', loading_2),
            ('main', self.main),
        ]
        ui = self._make_ui(self.login, frames[1:])
        ui.frame = frames[0]
        cleared = []
        clicked = []
        ui.device.stuck_record_clear.side_effect = lambda: cleared.append(ui.frame[0])
        ui.device.click.side_effect = lambda button: clicked.append((ui.frame[0], button))

        self.assertTrue(ui.handle_app_boot())

        self.assertEqual(
            cleared,
            ['login', 'loading_1', 'loading_1', 'loading_2', 'loading_2', 'main'],
        )
        self.assertEqual(clicked, [('login', LOGIN_START)])
        self.assertEqual(ui.device.screenshot.call_count, 3)
        self.assertIs(ui.ui_page_appear(page_main), True)

    def test_login_accepts_both_real_title_frames_and_clicks_safe_area(self):
        for name, frame in (('old', self.login), ('animated', self.stuck)):
            with self.subTest(frame=name):
                ui = self._make_ui(frame, [])

                self.assertTrue(ui.handle_login())

                ui.device.click.assert_called_once_with(LOGIN_START)
                self.assertIs(ui.device.click.call_args[0][0], LOGIN_START)
                self.assertEqual(LOGIN_START.button, (558, 522, 722, 582))

    def test_login_rejects_main_loading_update_download_and_activity(self):
        frames = (
            ('main', self.main),
            ('loading', self.loading),
            ('update', self.dialog),
            ('download', self.download),
            ('activity', self.activity),
        )
        for name, frame in frames:
            with self.subTest(frame=name):
                ui = self._make_ui(frame, [])

                self.assertFalse(ui.handle_login())

                ui.device.click.assert_not_called()

    def test_animated_login_throttles_repeat_then_converges_after_loading(self):
        ui = self._make_ui(
            self.stuck,
            [('login_repeat', self.stuck), ('loading', self.loading), ('main', self.main)],
        )
        ui.frame = ('login_animated', self.stuck)

        self.assertTrue(ui.handle_app_boot())

        clicked = [call[0][0] for call in ui.device.click.call_args_list]
        self.assertEqual(clicked, [LOGIN_START])
        self.assertEqual(ui.device.screenshot.call_count, 3)
        self.assertIs(ui.ui_page_appear(page_main), True)

    def test_boot_timeout_clears_each_frame_without_click(self):
        ui = self._make_ui(
            self.loading,
            [('loading_2', self.loading), ('loading_3', self.loading)],
        )
        ui.frame = ('loading_1', self.loading)
        cleared = []
        ui.device.stuck_record_clear.side_effect = lambda: cleared.append(ui.frame[0])

        class ThreeFrameTimer:
            def __init__(self, limit, count=0):
                self.frames = 0

            def start(self):
                return self

            def reset(self):
                self.frames = 0

            def reached(self):
                self.frames += 1
                return self.frames >= 3

        with patch('module.promilia.update.Timer', ThreeFrameTimer):
            with self.assertRaises(GameStuckError):
                ui.handle_app_boot()

        self.assertEqual(cleared, ['loading_1', 'loading_1', 'loading_2', 'loading_2', 'loading_3'])
        ui.device.click.assert_not_called()
        self.assertEqual(ui.device.screenshot.call_count, 2)


if __name__ == '__main__':
    unittest.main()
