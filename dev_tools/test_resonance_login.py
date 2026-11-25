import unittest
from unittest.mock import Mock, call

from module.base.utils import load_image
from module.config import server


class TestResonanceLogin(unittest.TestCase):
    def test_login_closes_each_popup_before_accepting_main_page(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')
        from module.resonance.assets import LOGIN_DAILY_CHECK_IN, LOGIN_ENTER, LOGIN_REWARD, LOGIN_START, MAIN_CHECK
        from module.resonance.resonance_ui import ResonanceUI

        with self.subTest('normal first login'):
            flow = (LOGIN_START, LOGIN_ENTER, LOGIN_REWARD, LOGIN_DAILY_CHECK_IN)
            self.check_flow(ResonanceUI, MAIN_CHECK, flow)
        with self.subTest('reward already dismissed'):
            self.check_flow(ResonanceUI, MAIN_CHECK, (LOGIN_DAILY_CHECK_IN,))
        with self.subTest('already at main page'):
            self.check_flow(ResonanceUI, MAIN_CHECK, ())

    def check_flow(self, ui_class, main_check, flow):
        ui = ui_class.__new__(ui_class)
        ui.device = Mock()
        ui.interval_timer = {}
        frames = iter(load_image(button.file) for button in (*flow, main_check))

        def screenshot():
            ui.device.image = next(frames)

        ui.device.screenshot.side_effect = screenshot
        ui.app_start()

        ui.device.app_start.assert_called_once_with()
        self.assertIs(ui.ui_current, ui.page_main)
        self.assertEqual(ui.device.click.call_args_list, [call(button) for button in flow])
