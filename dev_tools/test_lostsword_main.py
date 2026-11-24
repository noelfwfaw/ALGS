"""Offline regressions for LostswordMain battle wait and timeout handling."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from module.config.server import set_server

set_server('lostsword')

from module.exception import GameStuckError
from module.lostsword.main_story import MAIN_FIGHT_TIMEOUT, LostswordMain


class LostswordMainTest(unittest.TestCase):
    def _make_task(self):
        task = LostswordMain.__new__(LostswordMain)
        task.device = SimpleNamespace(
            image=np.zeros((720, 1280, 3), dtype=np.uint8),
            stuck_record_clear=Mock(),
        )
        task.loop = lambda: iter([0])
        return task

    def test_timeout_raises_stuck_instead_of_faking_defeat(self):
        self.assertGreaterEqual(MAIN_FIGHT_TIMEOUT, 3600)
        task = self._make_task()

        with self.assertRaises(GameStuckError):
            task.main_wait_fight_end(timeout=0)

        task.device.stuck_record_clear.assert_called_once()

    def test_defeat_leaves_and_returns_false(self):
        task = self._make_task()
        task.on_stage_page = Mock(return_value=False)
        task.main_defeat_appear = Mock(return_value=True)
        task.main_defeat_leave = Mock(return_value=True)

        self.assertFalse(task.main_wait_fight_end(timeout=10))
        task.main_defeat_leave.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
