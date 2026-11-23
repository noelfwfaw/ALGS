"""Offline regressions for Lostsword Avalon city-summary/countdown popup."""

import datetime
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2

from module.config.server import set_server

set_server('lostsword')

from module.lostsword.assets import AVALON_CITY_CONFIRM
from module.lostsword.avalon import LostswordAvalon


FIXTURE = Path(__file__).parent / 'fixtures' / 'lostsword' / 'avalon_city_summary.png'


class AvalonTest(unittest.TestCase):
    def test_city_summary_popup_reads_countdown_and_dismisses(self):
        im = cv2.cvtColor(cv2.imread(str(FIXTURE)), cv2.COLOR_BGR2RGB)
        task = LostswordAvalon.__new__(LostswordAvalon)
        task.config = SimpleNamespace(LostswordAvalon_City='埃塞尔城', task_delay=Mock())
        task.device = SimpleNamespace(image=im, click=Mock())
        task.appear = lambda btn, **kwargs: btn.match(task.device.image, **kwargs)
        task.wait_overlay_gone = Mock(return_value=True)
        task.avalon_next_reset = None

        self.assertEqual(task.avalon_read_next_time(), 552808)
        self.assertTrue(task._dismiss_notice())
        task.device.click.assert_called_once_with(AVALON_CITY_CONFIRM)
        task.wait_overlay_gone.assert_called_once()
        self.assertIsInstance(task.avalon_next_reset, datetime.datetime)

        remaining = (task.avalon_next_reset - datetime.datetime.now()).total_seconds()
        self.assertTrue(552800 <= remaining <= 552900)

        target = task.avalon_schedule()
        self.assertEqual(target, task.avalon_next_reset)
        task.config.task_delay.assert_called_once_with(target=target)


if __name__ == '__main__':
    unittest.main()
