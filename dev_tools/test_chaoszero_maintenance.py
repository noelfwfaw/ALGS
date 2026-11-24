"""Offline regressions for Chaoszero maintenance vs network confirm popups."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.config.server import set_server

set_server('chaoszero')

from module.chaoszero.assets import BOOT_DOWNLOAD_CONFIRM
from module.chaoszero.chaoszero_ui import ChaoszeroUI
from module.chaoszero.maintenance import (
    CHAOSZERO_MAINT_BANNER,
    CHAOSZERO_MAINT_BUTTON,
    Maintenance,
)
from module.config.config import TaskEnd


DOWNLOAD_FIXTURE = Path(__file__).parent / 'fixtures' / 'chaoszero' / 'boot_download_confirm.png'


def _make_banner_frame():
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    x1, y1, x2, y2 = CHAOSZERO_MAINT_BANNER
    img[y1:y2, x1:x2] = (245, 245, 245)
    bx1, by1, bx2, by2 = CHAOSZERO_MAINT_BUTTON
    img[by1:by2, bx1:bx2] = (235, 100, 40)
    return img


class _DummyUI(Maintenance):
    def image_crop(self, area):
        x1, y1, x2, y2 = area
        return self.device.image[y1:y2, x1:x2]


class ChaoszeroMaintenanceTest(unittest.TestCase):
    def _make_ui(self):
        ui = _DummyUI()
        ui.device = SimpleNamespace(
            image=_make_banner_frame(),
            click_record_clear=Mock(),
        )
        ui.tap_point = Mock()
        ui.config = SimpleNamespace(
            SCHEDULER_PRIORITY='ChaoszeroArk > ChaoszeroRogue',
            cross_get=Mock(return_value='2026-11-23 05:00:00'),
            task_delay=Mock(),
            task_stop=Mock(side_effect=TaskEnd('maintenance')),
        )
        return ui

    def test_network_confirm_popup_clicks_reload_without_delaying_tasks(self):
        ui = self._make_ui()
        with patch('module.chaoszero.maintenance.MAINTENANCE_BUTTON.ocr', return_value='確認'), \
             patch('module.chaoszero.maintenance.MAINTENANCE_TIMER.ocr', return_value='M'), \
             patch.object(ui, '_save_boot_popup') as save_mock:
            handled = ui.handle_maintenance()

        self.assertTrue(handled)
        save_mock.assert_called_once_with('確認')
        ui.tap_point.assert_called_once_with(639, 499, name='CHAOSZERO_BOOT_CONFIRM')
        ui.config.task_delay.assert_not_called()
        ui.config.task_stop.assert_not_called()

    def test_unknown_white_popup_is_ignored_without_delaying_tasks(self):
        ui = self._make_ui()
        with patch('module.chaoszero.maintenance.MAINTENANCE_BUTTON.ocr', return_value=''), \
             patch('module.chaoszero.maintenance.MAINTENANCE_TIMER.ocr', return_value='M'), \
             patch.object(ui, '_save_boot_popup') as save_mock:
            handled = ui.handle_maintenance()

        self.assertFalse(handled)
        save_mock.assert_called_once_with('')
        ui.tap_point.assert_not_called()
        ui.config.task_delay.assert_not_called()
        ui.config.task_stop.assert_not_called()

    def test_true_maintenance_with_countdown_delays_all_tasks(self):
        ui = self._make_ui()
        with patch('module.chaoszero.maintenance.MAINTENANCE_BUTTON.ocr', return_value='公告'), \
             patch('module.chaoszero.maintenance.MAINTENANCE_TIMER.ocr', return_value='03:50:32'):
            with self.assertRaises(TaskEnd):
                ui.handle_maintenance()

        self.assertEqual(ui.config.task_delay.call_count, 2)
        ui.tap_point.assert_not_called()

    def test_true_maintenance_announcement_button_without_timer_still_delays(self):
        ui = self._make_ui()
        with patch('module.chaoszero.maintenance.MAINTENANCE_BUTTON.ocr', return_value='公告'), \
             patch('module.chaoszero.maintenance.MAINTENANCE_TIMER.ocr', return_value=''):
            with self.assertRaises(TaskEnd):
                ui.handle_maintenance()

        self.assertEqual(ui.config.task_delay.call_count, 2)
        ui.tap_point.assert_not_called()

    def test_download_patch_fixture_skips_maintenance_and_clicks_confirm(self):
        frame = cv2.cvtColor(cv2.imread(str(DOWNLOAD_FIXTURE)), cv2.COLOR_BGR2RGB)
        ui = ChaoszeroUI.__new__(ChaoszeroUI)
        ui.device = SimpleNamespace(image=frame, click=Mock())
        ui.appear = lambda btn, offset=(20, 20), **kwargs: btn.match(ui.device.image, offset=offset)
        ui.wait_until_disappear = Mock(return_value=True)

        self.assertFalse(ui.maintenance_appear())
        self.assertTrue(ui.handle_download_confirm())
        ui.device.click.assert_called_once_with(BOOT_DOWNLOAD_CONFIRM)
        ui.wait_until_disappear.assert_called_once()


if __name__ == '__main__':
    unittest.main()
