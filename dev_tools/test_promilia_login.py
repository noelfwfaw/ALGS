"""Offline regressions for Promilia's login-to-main boot flow."""

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

    from module.promilia.assets import (ACTIVITY_CLOSE, ACTIVITY_DAILY_ACTIVE,  # noqa: E402
                                        ACTIVITY_ENTRY, LOADING_LOGO, LOGIN_START,
                                        UPDATE_BACKGROUND_DOWNLOAD,
                                        UPDATE_DOWNLOADING,
                                        UPDATE_NOTICE_CONFIRM,
                                        UPDATE_NOTICE_EXIT,
                                        UPDATE_NOTICE_TITLE,
                                        UPDATE_RESOURCE_CHECK)
    from module.promilia.page import (MAIN_HUD_ICON, page_activity,  # noqa: E402
                                      page_main)
    from module.promilia.promilia_ui import PromiliaUI  # noqa: E402
finally:
    server.set_server(_IMPORT_SERVER)


ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / 'screenshots' / 'promilia'
ASSETS = (UPDATE_NOTICE_TITLE, UPDATE_NOTICE_EXIT, UPDATE_NOTICE_CONFIRM,
          UPDATE_RESOURCE_CHECK, UPDATE_DOWNLOADING, UPDATE_BACKGROUND_DOWNLOAD,
          ACTIVITY_ENTRY, ACTIVITY_CLOSE, ACTIVITY_DAILY_ACTIVE,
          LOGIN_START, LOADING_LOGO, MAIN_HUD_ICON)


class PromiliaLoginTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('promilia')
        for asset in ASSETS:
            self.addCleanup(asset.clear_offset)
        self.dialog = load_image(str(SHOTS / 'promilia_update_dialog.png'))
        self.download = load_image(str(SHOTS / 'promilia_resource_download.png'))
        self.login = load_image(str(SHOTS / 'promilia_login.png'))
        self.login_animated = load_image(str(SHOTS / 'login_stuck_20261128_060647.png'))
        self.loading = load_image(str(SHOTS / 'promilia_loading.png'))
        self.main = load_image(str(SHOTS / 'promilia_main.png'))
        self.activity = load_image(str(SHOTS / 'activity_daily_points.png'))
        self.reward_early = load_image(str(SHOTS / 'activity_popup_early.png'))
        self.reward = load_image(str(SHOTS / 'activity_popup.png'))
        self.world = load_image(str(SHOTS / 'activity_world.png'))
        self.boot_hud = load_image(str(SHOTS / 'boot_hud_20261128_065105.png'))
        self.blank = np.zeros_like(self.login)

    def _make_ui(self, image, frames=None):
        ui = PromiliaUI.__new__(PromiliaUI)
        ui.config = SimpleNamespace(BUTTON_OFFSET=(20, 20))
        ui.interval_timer = {}
        ui.device = SimpleNamespace(
            image=image,
            has_cached_image=True,
            click=Mock(),
            screenshot=Mock(),
            stuck_record_add=Mock(),
            stuck_record_clear=Mock(),
        )
        if frames is not None:
            iterator = iter(frames)

            def screenshot():
                ui.device.image = next(iterator)

            ui.device.screenshot.side_effect = screenshot
        return ui

    def test_page_main_is_registered_and_used_by_ui_goto_main(self):
        self.assertEqual(page_main.check_button, [MAIN_HUD_ICON])
        self.assertEqual(MAIN_HUD_ICON.area, (1130, 35, 1170, 85))
        self.assertEqual(MAIN_HUD_ICON.button, (1130, 35, 1170, 85))
        self.assertTrue(MAIN_HUD_ICON.file)
        self.assertIs(PromiliaUI.page_main, page_main)
        self.assertEqual(PromiliaUI.pages, (page_main, page_activity))
        ui = self._make_ui(self.blank)
        ui.ui_ensure = Mock(return_value=False)

        self.assertFalse(ui.ui_goto_main())
        ui.ui_ensure.assert_called_once_with(destination=page_main)

    def test_plain_ui_recognizes_activity_and_returns_to_main(self):
        ui = self._make_ui(self.activity)

        self.assertIs(ui.ui_get_current_page(), page_activity)

        ui = self._make_ui(self.activity, [self.world, self.world])
        self.assertTrue(ui.ui_goto_main())
        self.assertEqual([call[0][0] for call in ui.device.click.call_args_list],
                         [ACTIVITY_CLOSE])
        self.assertIs(ui.ui_get_current_page(), page_main)

    def test_login_clicks_only_start_journey(self):
        ui = self._make_ui(self.login)

        self.assertTrue(ui.handle_login())
        ui.device.click.assert_called_once_with(LOGIN_START)

    def test_loading_returns_true_without_click_and_clears_watchdog(self):
        ui = self._make_ui(self.loading)

        self.assertTrue(ui.handle_loading())
        ui.device.click.assert_not_called()
        ui.device.stuck_record_clear.assert_called_once_with()

    def test_main_page_finishes_boot_without_click(self):
        for frame in (self.main, self.world, self.boot_hud):
            with self.subTest(frame=frame.shape):
                MAIN_HUD_ICON.clear_offset()
                ui = self._make_ui(frame)

                self.assertTrue(ui.handle_app_boot())
                ui.device.screenshot.assert_not_called()
                ui.device.click.assert_not_called()
                ui.device.stuck_record_clear.assert_called_once_with()

    def test_boot_replays_update_login_loading_main(self):
        ui = self._make_ui(self.dialog, [self.login, self.loading, self.main])

        self.assertTrue(ui.handle_app_boot())
        clicks = [call[0][0] for call in ui.device.click.call_args_list]
        self.assertEqual(clicks, [UPDATE_NOTICE_CONFIRM, LOGIN_START])
        self.assertNotIn(UPDATE_NOTICE_EXIT, clicks)
        self.assertEqual(ui.device.screenshot.call_count, 3)
        self.assertGreaterEqual(ui.device.stuck_record_clear.call_count, 4)

    def test_three_frames_do_not_cross_hit(self):
        frames = (self.login, self.loading, self.main)
        cases = (
            (LOGIN_START, [True, False, False]),
            (LOADING_LOGO, [False, True, False]),
            (MAIN_HUD_ICON, [False, False, True]),
        )
        for asset, expected in cases:
            actual = []
            for frame in frames:
                asset.clear_offset()
                ui = self._make_ui(frame)
                actual.append(ui.appear(asset, offset=(20, 20)))
            self.assertEqual(actual, expected, asset.name if hasattr(asset, 'name') else str(asset))

    def test_main_hud_recognizes_only_world_frames(self):
        cases = (
            ('old_main', self.main, True),
            ('activity_world', self.world, True),
            ('boot_hud', self.boot_hud, True),
            ('login', self.login, False),
            ('animated_login', self.login_animated, False),
            ('loading', self.loading, False),
            ('update', self.dialog, False),
            ('download', self.download, False),
            ('activity', self.activity, False),
            ('reward_early', self.reward_early, False),
            ('reward', self.reward, False),
        )
        for name, frame, expected in cases:
            with self.subTest(frame=name):
                MAIN_HUD_ICON.clear_offset()
                ui = self._make_ui(frame)

                self.assertIs(ui.ui_page_appear(page_main), expected)
                ui.device.click.assert_not_called()

    def test_update_notice_keeps_first_priority_in_ui_additional(self):
        ui = self._make_ui(self.blank)
        ui.handle_update_notice = Mock(return_value=True)
        ui.handle_update_downloading = Mock(return_value=False)
        ui.handle_login = Mock(return_value=False)
        ui.handle_loading = Mock(return_value=False)

        self.assertTrue(ui.ui_additional())
        ui.handle_update_notice.assert_called_once_with()
        ui.handle_update_downloading.assert_not_called()
        ui.handle_login.assert_not_called()
        ui.handle_loading.assert_not_called()

    def test_repeated_loading_frames_clear_watchdog_without_click(self):
        ui = self._make_ui(self.loading, [self.loading, self.main])

        self.assertTrue(ui.handle_app_boot())
        ui.device.click.assert_not_called()
        self.assertGreaterEqual(ui.device.stuck_record_clear.call_count, 3)
        self.assertEqual(ui.device.screenshot.call_count, 2)

    def test_boot_timeout_raises_game_stuck(self):
        ui = self._make_ui(self.blank)

        class ImmediateTimer:
            def __init__(self, limit, count=0):
                pass

            def start(self):
                return self

            def reset(self):
                pass

            def reached(self):
                return True

        with patch('module.promilia.update.Timer', ImmediateTimer):
            with self.assertRaises(GameStuckError):
                ui.handle_app_boot()
        ui.device.click.assert_not_called()
        ui.device.stuck_record_clear.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
