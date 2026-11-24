"""Offline regressions for LostswordAffection retry loops."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from module.config.server import set_server

set_server('lostsword')

from module.lostsword.affection import LostswordAffection


class LostswordAffectionTest(unittest.TestCase):
    def _make_task(self):
        task = LostswordAffection.__new__(LostswordAffection)
        task.device = SimpleNamespace(
            stuck_record_clear=Mock(),
            screenshot=Mock(),
        )
        task.tap_point = Mock()
        return task

    def test_open_card_retry_does_not_shadow_timeout(self):
        task = self._make_task()
        task.affection_detail_appear = Mock(side_effect=[False, True])

        self.assertTrue(task.affection_open_card(1133, 190, timeout=-1, tries=2))
        self.assertEqual(task.tap_point.call_count, 2)

        task.tap_point.reset_mock()
        task.affection_detail_appear = Mock(return_value=False)
        self.assertFalse(task.affection_open_card(1133, 190, timeout=-1, tries=3))
        self.assertEqual(task.tap_point.call_count, 3)

    def test_open_panel_retry_does_not_shadow_timeout(self):
        task = self._make_task()
        task.affection_detail_appear = Mock(return_value=True)
        task.affection_wait_panel = Mock(side_effect=[False, False, True])

        self.assertTrue(task.affection_open(timeout=-1))
        self.assertEqual(task.affection_wait_panel.call_count, 3)


if __name__ == '__main__':
    unittest.main()
