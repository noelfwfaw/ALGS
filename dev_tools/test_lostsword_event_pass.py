"""Offline regressions for Lostsword event-pass popup detection and clicks."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from module.base.timer import Timer
from module.base.utils import load_image
from module.config import server

_IMPORT_SERVER = server.server
try:
    server.set_server('lostsword')
    from module.lostsword.assets import (
        EVENT_PASS_BLACK_FRIDAY_CLOSE,
        EVENT_PASS_BLACK_FRIDAY_POPUP,
        EVENT_PASS_CLOSE,
        EVENT_PASS_POPUP,
    )
    from module.lostsword.event_pass import EventPassPopup
finally:
    server.set_server(_IMPORT_SERVER)

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets/lostsword/lostsword'
BLACK_FRIDAY = ASSETS / 'EVENT_PASS_BLACK_FRIDAY_POPUP.png'
LOBBY = ASSETS / 'MAIN_BTN_BATTLE.png'
CONTROLS = (LOBBY, ASSETS / 'REWARD_POPUP_TITLE.png', ASSETS / 'OFFER_POPUP.png',
            ASSETS / 'SIGN_IN_TITLE.png', ASSETS / 'PASS_TITLE.png')


class LostswordEventPassTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('lostsword')
        self.buttons = (
            EVENT_PASS_POPUP,
            EVENT_PASS_CLOSE,
            EVENT_PASS_BLACK_FRIDAY_POPUP,
            EVENT_PASS_BLACK_FRIDAY_CLOSE,
        )
        for button in self.buttons:
            self.addCleanup(button.clear_offset)

    def _task(self, image):
        task = EventPassPopup.__new__(EventPassPopup)
        task.device = SimpleNamespace(image=image)
        task.tap_asset = Mock()
        task.EVENT_PASS_BACK = Timer(2)
        return task

    def _paste_close(self, image, button):
        x1, y1, x2, y2 = button.area
        template = load_image(button.file)
        image[y1:y2, x1:x2] = template[y1:y2, x1:x2]

    def _clear_close_search(self, image):
        image[91:171, 1101:1181] = 0

    def test_black_friday_clicks_only_the_detected_upper_right_x(self):
        task = self._task(load_image(BLACK_FRIDAY))

        self.assertTrue(task.event_pass_popup_appear())
        self.assertTrue(task.handle_event_pass())
        task.tap_asset.assert_called_once_with(EVENT_PASS_BLACK_FRIDAY_CLOSE)
        x1, y1, x2, y2 = task.tap_asset.call_args[0][0].button
        self.assertEqual(((x1 + x2) // 2, (y1 + y2) // 2), (1141, 131))

    def test_halloween_keeps_using_its_own_close(self):
        task = self._task(load_image(EVENT_PASS_POPUP.file))

        self.assertTrue(task.event_pass_popup_appear())
        self.assertTrue(task.handle_event_pass())
        task.tap_asset.assert_called_once_with(EVENT_PASS_CLOSE)
        x1, y1, x2, y2 = task.tap_asset.call_args[0][0].button
        self.assertEqual(((x1 + x2) // 2, (y1 + y2) // 2), (1136, 124))

    def test_lobby_reward_and_other_popups_do_not_click(self):
        for path in CONTROLS:
            with self.subTest(path=path.name):
                task = self._task(load_image(path))
                self.assertFalse(task.event_pass_popup_appear())
                self.assertFalse(task.handle_event_pass())
                task.tap_asset.assert_not_called()

    def test_title_or_x_alone_does_not_click(self):
        title_only = load_image(BLACK_FRIDAY)
        self._clear_close_search(title_only)
        x_only = load_image(LOBBY)
        self._paste_close(x_only, EVENT_PASS_BLACK_FRIDAY_CLOSE)

        for label, image in (('title_only', title_only), ('x_only', x_only)):
            with self.subTest(frame=label):
                task = self._task(image)
                self.assertFalse(task.event_pass_popup_appear())
                self.assertFalse(task.handle_event_pass())
                task.tap_asset.assert_not_called()

    def test_title_with_the_other_events_x_does_not_click(self):
        for title_path, wrong_close in (
            (BLACK_FRIDAY, EVENT_PASS_CLOSE),
            (EVENT_PASS_POPUP.file, EVENT_PASS_BLACK_FRIDAY_CLOSE),
        ):
            with self.subTest(title=Path(title_path).name):
                image = load_image(title_path)
                self._clear_close_search(image)
                self._paste_close(image, wrong_close)
                task = self._task(image)
                self.assertFalse(task.event_pass_popup_appear())
                self.assertFalse(task.handle_event_pass())
                task.tap_asset.assert_not_called()

    def test_consecutive_frames_keep_the_existing_cooldown(self):
        task = self._task(load_image(BLACK_FRIDAY))

        self.assertTrue(task.handle_event_pass())
        self.assertTrue(task.handle_event_pass())
        task.tap_asset.assert_called_once_with(EVENT_PASS_BLACK_FRIDAY_CLOSE)

    def test_boot_and_global_overlay_use_the_shared_handler(self):
        source = (ROOT / 'module/lostsword/lostsword_ui.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        methods = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        }
        for name in ('handle_app_boot', 'ui_additional'):
            with self.subTest(method=name):
                calls = [
                    node for node in ast.walk(methods[name])
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'handle_event_pass'
                ]
                self.assertEqual(len(calls), 1)

    def test_new_assets_are_full_screen_static_crops(self):
        popup = load_image(EVENT_PASS_BLACK_FRIDAY_POPUP.file)
        close = load_image(EVENT_PASS_BLACK_FRIDAY_CLOSE.file)
        x1, y1, x2, y2 = EVENT_PASS_BLACK_FRIDAY_CLOSE.area

        self.assertEqual(EVENT_PASS_BLACK_FRIDAY_POPUP.area, (0, 0, 1280, 720))
        self.assertEqual(EVENT_PASS_BLACK_FRIDAY_CLOSE.area, (1121, 111, 1161, 151))
        self.assertEqual(popup.shape, (720, 1280, 3))
        self.assertEqual(close.shape, (720, 1280, 3))
        self.assertTrue((close[y1:y2, x1:x2] == popup[y1:y2, x1:x2]).all())
        self.assertEqual(int(close[:y1].sum() + close[y2:].sum()), 0)
        self.assertEqual(int(close[y1:y2, :x1].sum() + close[y1:y2, x2:].sum()), 0)
        for path in (ASSETS / 'EVENT_PASS_BLACK_FRIDAY_POPUP.png',
                     ASSETS / 'EVENT_PASS_BLACK_FRIDAY_CLOSE.png'):
            self.assertTrue(path.is_file())

    def test_new_close_is_not_an_unrelated_page_template(self):
        for path in CONTROLS:
            with self.subTest(path=path.name):
                self.assertFalse(EVENT_PASS_BLACK_FRIDAY_CLOSE.match(load_image(path), offset=20))


if __name__ == '__main__':
    unittest.main()
