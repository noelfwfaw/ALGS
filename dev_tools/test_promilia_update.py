"""Offline regressions for Promilia's resource-update boot flow."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.base.utils import load_image
from module.config import server
from module.exception import GameStuckError
from module.ui.ui import UI


_IMPORT_SERVER = server.server
try:
    server.set_server('promilia')

    from module.promilia.assets import (LOADING_LOGO, LOGIN_START, MAIN_ICONS,  # noqa: E402
                                        UPDATE_BACKGROUND_DOWNLOAD,
                                        UPDATE_DOWNLOADING,
                                        UPDATE_NOTICE_CONFIRM,
                                        UPDATE_NOTICE_EXIT,
                                        UPDATE_NOTICE_TITLE,
                                        UPDATE_RESOURCE_CHECK)
    from module.promilia.update import (UPDATE_DOWNLOAD_PROGRESS_AREA,  # noqa: E402
                                        UPDATE_DOWNLOAD_STALL)
    from module.promilia.promilia_ui import PromiliaUI  # noqa: E402
finally:
    server.set_server(_IMPORT_SERVER)


ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / 'screenshots' / 'promilia'
ASSETS = (UPDATE_NOTICE_TITLE, UPDATE_NOTICE_EXIT, UPDATE_NOTICE_CONFIRM,
          UPDATE_RESOURCE_CHECK, UPDATE_DOWNLOADING, UPDATE_BACKGROUND_DOWNLOAD,
          LOGIN_START, LOADING_LOGO, MAIN_ICONS)


class _ImmediateStallTimer:
    def __init__(self, limit, count=0):
        self.limit = limit

    def start(self):
        return self

    def reset(self):
        pass

    def reached(self):
        return self.limit == UPDATE_DOWNLOAD_STALL

    def reached_and_reset(self):
        return False


class PromiliaUpdateTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('promilia')
        for asset in ASSETS:
            self.addCleanup(asset.clear_offset)
        self.dialog = load_image(str(SHOTS / 'promilia_update_dialog.png'))
        self.download = load_image(str(SHOTS / 'promilia_resource_download.png'))
        self.login = load_image(str(SHOTS / 'promilia_login.png'))
        self.loading = load_image(str(SHOTS / 'promilia_loading.png'))
        self.main = load_image(str(SHOTS / 'promilia_main.png'))
        self.blank = np.zeros_like(self.dialog)

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

    def test_update_notice_clicks_only_confirm(self):
        ui = self._make_ui(self.dialog)

        self.assertTrue(ui.handle_update_notice())
        ui.device.click.assert_called_once_with(UPDATE_NOTICE_CONFIRM)
        self.assertNotIn(UPDATE_NOTICE_EXIT, [call[0][0] for call in ui.device.click.call_args_list])

    def test_cancel_without_confirm_is_not_clicked(self):
        cancel_only = self.dialog.copy()
        x1, y1, x2, y2 = UPDATE_NOTICE_CONFIRM.area
        cancel_only[y1:y2, x1:x2] = self.dialog[500:500 + y2 - y1, 1000:1000 + x2 - x1]
        ui = self._make_ui(cancel_only)

        self.assertTrue(ui.appear(UPDATE_NOTICE_EXIT, offset=(20, 20)))
        # The broad dark-button template can still match nearby background;
        # the static green check is the required second factor.
        self.assertTrue(ui.appear(UPDATE_NOTICE_CONFIRM, offset=(20, 20)))
        self.assertFalse(ui._update_confirm_has_check())
        self.assertFalse(ui.handle_update_notice())
        ui.device.click.assert_not_called()

    def test_download_clears_watchdog_without_click_and_exits(self):
        ui = self._make_ui(self.download, [self.download, self.blank])

        self.assertTrue(ui.handle_update_downloading())
        ui.device.click.assert_not_called()
        self.assertGreaterEqual(ui.device.stuck_record_clear.call_count, 3)
        self.assertEqual(ui.device.screenshot.call_count, 2)

    def test_changed_progress_bar_resets_stall_timer(self):
        changed = self.download.copy()
        x1, y1, x2, y2 = UPDATE_DOWNLOAD_PROGRESS_AREA
        changed[y1:y2, x1:x1 + 6] = 255
        ui = self._make_ui(self.download, [changed, self.blank])
        timers = []

        class RecordingTimer:
            def __init__(self, limit, count=0):
                self.limit = limit
                self.resets = 0
                timers.append(self)

            def start(self):
                return self

            def reset(self):
                self.resets += 1

            def reached(self):
                return False

            def reached_and_reset(self):
                return False

        with patch('module.promilia.update.Timer', RecordingTimer):
            self.assertTrue(ui.handle_update_downloading())

        self.assertEqual(timers[1].resets, 1)
        ui.device.click.assert_not_called()

    def test_stalled_download_raises_game_stuck(self):
        ui = self._make_ui(self.download)

        with patch('module.promilia.update.Timer', _ImmediateStallTimer):
            with self.assertRaises(GameStuckError):
                ui.handle_update_downloading()
        ui.device.click.assert_not_called()

    def test_boot_handles_update_then_finishes_at_main(self):
        ui = self._make_ui(self.dialog, [self.download, self.login, self.loading, self.main])

        self.assertTrue(ui.handle_app_boot())
        ui.device.click.assert_called_once_with(UPDATE_NOTICE_CONFIRM)
        self.assertNotIn(UPDATE_NOTICE_EXIT, [call[0][0] for call in ui.device.click.call_args_list])

    def test_boot_without_update_waits_for_main_after_resource_check(self):
        resource_only = self.dialog.copy()
        resource_only[250:520, 220:1060] = self.dialog[520, 1000]
        ui = self._make_ui(resource_only, [self.login, self.loading, self.main])

        self.assertTrue(ui.handle_app_boot())
        ui.device.click.assert_called_once_with(LOGIN_START)

    def test_ui_additional_handles_notice_before_other_states(self):
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

    def test_app_start_launches_then_runs_boot(self):
        ui = self._make_ui(self.blank)
        ui.handle_app_boot = Mock()

        with patch.object(UI, 'app_start') as launch:
            ui.app_start()

        launch.assert_called_once_with()
        ui.handle_app_boot.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
