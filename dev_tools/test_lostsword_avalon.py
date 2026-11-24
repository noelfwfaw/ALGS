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

    def _make_run_task(self, city1='埃塞尔城', city2='爱尔亚城'):
        task = LostswordAvalon.__new__(LostswordAvalon)
        task.config = SimpleNamespace(
            LostswordAvalon_City=city1,
            LostswordAvalon_City2=city2,
        )
        task.ui_ensure = Mock()
        task.ui_goto_main = Mock()
        task.battle_goto_guild = Mock(return_value=True)
        task.avalon_enter = Mock(return_value=True)
        task.avalon_schedule = Mock()
        task.appear = Mock(return_value=True)
        task.avalon_start_sortie = Mock(return_value=True)
        task.avalon_wait_battle = Mock()
        return task

    def test_avalon_cities_dedup_and_fallback(self):
        task = self._make_run_task(city1='卡美洛城', city2='默西亚城')
        self.assertEqual(task.avalon_cities(), ['卡美洛城', '默西亚城'])

        same = self._make_run_task(city1='卡美洛城', city2='卡美洛城')
        self.assertEqual(same.avalon_cities(), ['卡美洛城'])

        bad = self._make_run_task(city1='未知城', city2='未知城')
        self.assertEqual(bad.avalon_cities(), ['埃塞尔城', '爱尔亚城'])

    def test_run_challenges_two_cities_three_times_each(self):
        task = self._make_run_task(city1='埃塞尔城', city2='爱尔亚城')
        opened = []
        tries = iter([6, 5, 4, 3, 2, 1])

        def open_city(city):
            opened.append(city)
            return True

        task.avalon_open_city = Mock(side_effect=open_city)
        task.avalon_read_tries = Mock(side_effect=lambda: next(tries))

        task.run()

        self.assertEqual(opened, ['埃塞尔城', '埃塞尔城', '埃塞尔城',
                                  '爱尔亚城', '爱尔亚城', '爱尔亚城'])
        self.assertEqual(task.avalon_wait_battle.call_count, 6)
        task.ui_goto_main.assert_called_once()
        task.avalon_schedule.assert_called_once()

    def test_run_moves_to_city2_when_city1_capped_early(self):
        task = self._make_run_task(city1='埃塞尔城', city2='爱尔亚城')
        opened = []
        tries_by_call = iter([4, 0, 3, 2, 1])

        def open_city(city):
            opened.append(city)
            return True

        task.avalon_open_city = Mock(side_effect=open_city)
        task.avalon_read_tries = Mock(side_effect=lambda: next(tries_by_call))

        task.run()

        self.assertEqual(opened, ['埃塞尔城', '埃塞尔城', '爱尔亚城', '爱尔亚城', '爱尔亚城'])
        self.assertEqual(task.avalon_wait_battle.call_count, 4)
        self.assertEqual(task.ui_ensure.call_count, 2)


if __name__ == '__main__':
    unittest.main()
