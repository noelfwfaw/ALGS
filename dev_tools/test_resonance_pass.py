import unittest
from itertools import count
from unittest.mock import Mock, call, patch

from module.base.utils import load_image
from module.config import server


class TestResonancePass(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def make_task(self):
        from module.resonance.battle_pass import ResonancePass

        task = ResonancePass.__new__(ResonancePass)
        task.ui_ensure = Mock()
        task.ui_goto_main = Mock()
        task.config = Mock()
        task.book_available = Mock(return_value=True)
        return task

    def test_claim_tasks_before_level_rewards(self):
        from module.resonance import assets
        from module.resonance.battle_pass import ResonancePass

        task = ResonancePass.__new__(ResonancePass)
        task.select_view = Mock()
        task.claim_view = Mock()
        task.claim_book()
        self.assertEqual(task.select_view.call_args_list, [
            call(assets.PASS_TASKS_TAB, assets.PASS_TASKS_SELECTED),
            call(assets.PASS_DAILY_TAB, assets.PASS_DAILY_SELECTED),
            call(assets.PASS_WEEKLY_TAB, assets.PASS_WEEKLY_SELECTED),
            call(assets.PASS_REWARDS_TAB, assets.PASS_REWARDS_SELECTED),
        ])
        self.assertEqual(task.claim_view.call_args_list, [
            call(assets.PASS_DAILY_SELECTED),
            call(assets.PASS_WEEKLY_SELECTED),
            call(assets.PASS_REWARDS_SELECTED),
        ])

    def test_claim_view_dismisses_reward_and_skips_empty_view(self):
        from module.resonance import assets
        from module.resonance.battle_pass import ResonancePass

        task = ResonancePass.__new__(ResonancePass)
        task.interval_timer = {}
        task.device = Mock()
        daily = load_image(assets.PASS_DAILY_SELECTED.file)
        claimable = daily + load_image(assets.PASS_CLAIM_ALL.file)
        popup = load_image(assets.LOGIN_REWARD.file)
        task.device.image = claimable
        frames = iter([popup] + [daily] * 10)

        def screenshot():
            task.device.image = next(frames)

        task.device.screenshot.side_effect = screenshot
        with patch('module.base.timer.time', side_effect=count(100, 0.6)):
            task.claim_view(assets.PASS_DAILY_SELECTED)
        self.assertEqual(task.device.click.call_args_list, [
            call(assets.PASS_CLAIM_ALL), call(assets.LOGIN_REWARD),
        ])

        weekly = load_image(assets.PASS_WEEKLY_SELECTED.file)
        task.device.image = weekly
        frames = iter([weekly] * 10)
        task.device.click.reset_mock()
        with patch('module.base.timer.time', side_effect=count(200, 0.6)):
            task.claim_view(assets.PASS_WEEKLY_SELECTED)
        task.device.click.assert_not_called()

    def test_book_geometry_and_selection_from_original_screenshot(self):
        from module.resonance.battle_pass import BOOKS, ResonancePass

        task = ResonancePass.__new__(ResonancePass)
        task.device = Mock(image=load_image('screenshots/resonance/pass_second_unclaimed_20261128.png'))
        self.assertEqual([book.button for book in BOOKS], [
            (46, 126, 184, 182), (46, 202, 184, 257),
        ])
        bounds = ((22, 118, 200, 190), (22, 194, 200, 265))
        for book, (x1, y1, x2, y2) in zip(BOOKS, bounds):
            bx1, by1, bx2, by2 = book.button
            self.assertTrue(x1 <= bx1 < bx2 <= x2 and y1 <= by1 < by2 <= y2)
        self.assertEqual([task.book_available(0), task.book_available(1)], [True, True])
        self.assertEqual(task.selected_book(), 1)

    def test_single_book_run(self):
        task = self.make_task()
        task.book_available = Mock(side_effect=lambda index: index == 0)
        task.selected_book = Mock(return_value=0)
        task.open_book = Mock()
        task.claim_book = Mock()
        task.run()
        task.open_book.assert_not_called()
        task.claim_book.assert_called_once_with()
        task.config.task_delay.assert_called_once_with(server_update=True)

    def test_two_books_claim_current_first(self):
        task = self.make_task()
        task.selected_book = Mock(return_value=1)
        task.open_book = Mock(return_value=True)
        task.claim_book = Mock()
        events = Mock()
        events.attach_mock(task.open_book, 'open')
        events.attach_mock(task.claim_book, 'claim')
        task.run()
        self.assertEqual(events.mock_calls, [call.claim(), call.open(0), call.claim()])
        task.config.task_delay.assert_called_once_with(server_update=True)

    def test_open_book_requires_stable_selection_and_available_page(self):
        from module.resonance.battle_pass import BOOKS, ResonancePass

        task = ResonancePass.__new__(ResonancePass)
        task.device = Mock(image=load_image('screenshots/resonance/pass_second_unclaimed_20261128.png'))
        task.device.screenshot.side_effect = lambda: None
        task.appear = Mock(return_value=True)
        with patch('module.base.timer.time', side_effect=count(100, 1)):
            self.assertFalse(task.open_book(0))
        self.assertGreaterEqual(task.device.click.call_count, 2)
        for clicked in task.device.click.call_args_list:
            self.assertIs(clicked[0][0], BOOKS[0])

        task.device.click.reset_mock()
        task.selected_book = Mock(side_effect=[1, 1, 0, 0])
        with patch('module.base.timer.time', side_effect=count(200, 1)):
            self.assertTrue(task.open_book(0))
        task.device.click.assert_called_once_with(BOOKS[0])

        task.device.click.reset_mock()
        task.appear.return_value = False
        self.assertFalse(task.open_book(0))
        task.device.click.assert_not_called()

        task.device.image[:] = 0
        task.appear.return_value = True
        self.assertFalse(task.open_book(1))
        task.device.click.assert_not_called()

    def test_run_delays_on_failed_book_switch(self):
        from module.exception import TaskFailed

        task = self.make_task()
        task.selected_book = Mock(return_value=1)
        task.open_book = Mock(return_value=False)
        task.claim_book = Mock()
        with self.assertRaises(TaskFailed):
            task.run()
        task.config.task_delay.assert_called_once_with(success=False)
        task.claim_book.assert_called_once_with()
        task.ui_goto_main.assert_not_called()
