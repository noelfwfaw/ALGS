import unittest
from itertools import count
from unittest.mock import Mock, call, patch

from module.base.utils import load_image
from module.config import server


class TestResonancePass(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

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
