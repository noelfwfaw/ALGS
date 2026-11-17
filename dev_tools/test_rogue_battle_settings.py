"""Battle toggle regressions calibrated from the user's off/on screenshots."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from PIL import Image

from module.config.server import set_server

set_server('chaoszero')

from module.chaoszero.rogue import BATTLE_SETTINGS, BATTLE_SETTING_TRIES, ChaoszeroRogue
from module.exception import TaskFailed


FIXTURES = Path(__file__).parent / 'fixtures' / 'chaoszero'


def frame(state):
    return np.array(Image.open(str(FIXTURES / ('rogue_battle_%s.png' % state))).convert('RGB'))


def make_task(state='off'):
    task = ChaoszeroRogue.__new__(ChaoszeroRogue)
    task.device = SimpleNamespace(image=frame(state), stuck_record_add=Mock())
    task.battle_setting_tries = {}
    task.tap_point = Mock()
    task.rogue_dump_unknown = Mock()
    return task


class BattleSettingsTest(unittest.TestCase):
    def test_both_reference_frames_are_battle_pages(self):
        for state in ('off', 'on'):
            self.assertTrue(make_task(state).rogue_battle_appear(), state)

    def test_reference_colors_distinguish_off_and_on(self):
        for state, golds, whites in [('off', (0, 0), (200, 262)),
                                     ('on', (129, 111), (0, 0))]:
            task = make_task(state)
            for (_, button, _), gold, white in zip(BATTLE_SETTINGS, golds, whites):
                area = button.area
                self.assertEqual(task.ui_gold_count(area), gold)
                self.assertEqual(task.rogue_count(area, 'white', threshold=210), white)

    def test_enable_speed_then_auto_and_verify_without_toggling_back_off(self):
        task = make_task()
        press = Mock()
        self.assertTrue(task.handle_rogue_battle_settings(press))
        task.tap_point.assert_called_once_with(1148, 38, name='ROGUE_BATTLE_SPEED_ON')
        area = BATTLE_SETTINGS[0][1].area
        x1, y1, x2, y2 = area
        task.device.image[y1:y2, x1:x2] = frame('on')[y1:y2, x1:x2]
        self.assertTrue(task.handle_rogue_battle_settings(press))
        task.tap_point.assert_called_with(1064, 38, name='ROGUE_BATTLE_AUTO_ON')
        self.assertNotIn('speed', task.battle_setting_tries)
        task.device.image = frame('on')
        for _ in range(10):
            self.assertFalse(task.handle_rogue_battle_settings(press))
        self.assertEqual(task.tap_point.call_count, 2)
        self.assertEqual(task.battle_setting_tries, {})

    def test_already_enabled_settings_are_never_clicked(self):
        task = make_task('on')
        self.assertFalse(task.handle_rogue_battle_settings(Mock()))
        task.tap_point.assert_not_called()

    def test_only_speed_off_leaves_auto_enabled(self):
        task = make_task('on')
        x1, y1, x2, y2 = BATTLE_SETTINGS[0][1].area
        task.device.image[y1:y2, x1:x2] = frame('off')[y1:y2, x1:x2]
        self.assertTrue(task.handle_rogue_battle_settings(Mock()))
        task.tap_point.assert_called_once_with(1148, 38, name='ROGUE_BATTLE_SPEED_ON')

    def test_missing_turn_marker_prevents_clicks(self):
        task = make_task()
        task.device.image[500:] = 0
        self.assertFalse(task.handle_rogue_battle_settings(Mock()))
        task.tap_point.assert_not_called()

    def test_dimmed_or_missing_controls_are_not_assumed_off(self):
        for brightness in (0, 0.5):
            task = make_task()
            task.device.image[:80] = (task.device.image[:80] * brightness).astype(np.uint8)
            self.assertFalse(task.handle_rogue_battle_settings(Mock()))
            task.tap_point.assert_not_called()

    def test_dialogue_covering_controls_does_not_trigger_a_click(self):
        task = make_task('obscured')
        self.assertTrue(task.rogue_battle_appear())
        self.assertFalse(task.handle_rogue_battle_settings(Mock()))
        task.tap_point.assert_not_called()

    def test_other_battle_layout_is_not_clicked_at_rogue_positions(self):
        task = make_task('other_layout')
        self.assertTrue(task.rogue_battle_appear())
        self.assertFalse(task.handle_rogue_battle_settings(Mock()))
        task.tap_point.assert_not_called()

    def test_click_cooldown_is_respected(self):
        task = make_task()
        press = Mock()
        press.reached.return_value = False
        self.assertTrue(task.handle_rogue_battle_settings(press))
        task.tap_point.assert_not_called()
        press.reset.assert_not_called()

    def test_failed_clicks_are_bounded_and_stop_without_retreat(self):
        task = make_task()
        press = Mock()
        for _ in range(BATTLE_SETTING_TRIES):
            self.assertTrue(task.handle_rogue_battle_settings(press))
        with self.assertRaises(TaskFailed):
            task.handle_rogue_battle_settings(press)
        self.assertEqual(task.tap_point.call_count, BATTLE_SETTING_TRIES)
        task.rogue_dump_unknown.assert_called_once()


if __name__ == '__main__':
    unittest.main()
