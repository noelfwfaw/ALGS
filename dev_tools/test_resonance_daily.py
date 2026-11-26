import unittest
from datetime import datetime, timedelta
from itertools import count
from unittest.mock import Mock, patch

from module.base.utils import load_image
from module.config import server
from module.config.utils import filepath_args, get_server_next_update, read_file


class TestResonanceDaily(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def test_daily_navigation_keeps_its_main_page_after_loading_another_game(self):
        from module.resonance.page import page_daily, page_main as resonance_main
        from module.ui.page import Page

        self.addCleanup(Page.clear_connection)
        with patch.dict(Page.all_pages):
            page_main = Page(None)
            Page.init_connection(page_daily)
            self.assertIs(resonance_main.parent, page_daily)
            self.assertIsNone(page_main.parent)

    def test_claim_offscreen_card_then_unlocked_milestones(self):
        from module.resonance.assets import DAILY_CHECK, LOGIN_REWARD, TEMPLATE_DAILY_CLAIM
        from module.resonance.daily import MILESTONES, ResonanceDaily

        left = load_image(DAILY_CHECK.file)
        right = left.copy()
        right[300:340, 200:290] = 255
        completed = right.copy()
        completed[602:638, 900:992] = TEMPLATE_DAILY_CLAIM.image
        milestone = right.copy()
        for gift, color in zip(MILESTONES.buttons, [(248, 179, 1), (63, 125, 251), (248, 179, 1)]):
            x1, y1, x2, y2 = gift.area
            milestone[y1:y2, x1:x2] = color
        last_milestone = milestone.copy()
        x1, y1, x2, y2 = MILESTONES.buttons[0].area
        last_milestone[y1:y2, x1:x2] = (81, 101, 140)
        popup = load_image(LOGIN_REWARD.file)
        frames = iter((completed, milestone, milestone, popup, popup,
                       last_milestone, popup, popup, right))

        task = ResonanceDaily.__new__(ResonanceDaily)
        task.device = Mock()
        task.device.image = left
        task.config = Mock()
        task.interval_timer = {}
        task.ui_ensure = Mock()
        task.ui_goto_main = Mock()
        task.wait_until_still = Mock(return_value=True)

        def screenshot():
            task.device.image = next(frames)

        task.device.screenshot.side_effect = screenshot
        with patch('module.base.timer.time', side_effect=count(100, 3)):
            task.run()

        clicked = [entry[0][0] for entry in task.device.click.call_args_list]
        self.assertEqual([button.name for button in clicked], [
            'TEMPLATE_DAILY_CLAIM', 'MILESTONES_0_0', 'LOGIN_REWARD',
            'MILESTONES_2_0', 'LOGIN_REWARD',
        ])
        self.assertEqual(clicked[0].button, (900, 602, 992, 638))
        self.assertEqual(task.device.swipe.call_count, 2)
        task.ui_goto_main.assert_called_once_with()
        task.config.task_delay.assert_called_once_with(server_update=True)

    def test_next_run_alternates_between_game_reset_and_evening(self):
        schedule = read_file(filepath_args())['ResonanceDaily']['Scheduler']['ServerUpdate']['value']
        cases = [
            (datetime(2026, 11, 25, 4, 59), datetime(2026, 11, 25, 5)),
            (datetime(2026, 11, 25, 5, 1), datetime(2026, 11, 25, 18)),
            (datetime(2026, 11, 25, 18, 1), datetime(2026, 11, 26, 5)),
        ]
        with patch('module.config.utils.server_time_offset', return_value=timedelta(0)):
            with patch('module.config.utils.datetime') as clock:
                for now, next_run in cases:
                    clock.now.return_value = now
                    self.assertEqual(get_server_next_update(schedule), next_run)

    def test_claim_milestones_accepts_shifted_reward_and_direct_claim(self):
        from module.resonance.assets import DAILY_CHECK, LOGIN_REWARD
        from module.resonance.daily import MILESTONES, ResonanceDaily

        base = load_image(DAILY_CHECK.file)
        m_yellow = base.copy()
        x1, y1, x2, y2 = MILESTONES.buttons[0].area
        m_yellow[y1:y2, x1:x2] = (248, 179, 1)
        m_claimed = base.copy()
        m_claimed[y1:y2, x1:x2] = (63, 85, 126)

        shifted_popup = base.copy()
        sx1, sy1, sx2, sy2 = LOGIN_REWARD.area
        shifted_popup[sy1 + 70:sy2 + 70, sx1:sx2] = load_image(LOGIN_REWARD.file, LOGIN_REWARD.area)

        # Case 1: Shifted LOGIN_REWARD popup (dy=+70) detected by claim_milestones and closed by handle_reward_popup
        task1 = ResonanceDaily.__new__(ResonanceDaily)
        task1.device = Mock()
        task1.device.image = m_yellow
        task1.interval_timer = {}
        frames1 = iter([shifted_popup, shifted_popup, m_claimed])
        task1.device.screenshot.side_effect = lambda: setattr(task1.device, 'image', next(frames1))
        with patch('module.base.timer.time', side_effect=count(100, 3)):
            task1.claim_milestones()
        clicked1 = [c[0][0].name for c in task1.device.click.call_args_list]
        self.assertEqual(clicked1, ['MILESTONES_0_0', 'LOGIN_REWARD'])

        # Case 2: Milestone turns claimed directly without popup -> exits cleanly without GameStuckError
        task2 = ResonanceDaily.__new__(ResonanceDaily)
        task2.device = Mock()
        task2.device.image = m_yellow
        task2.interval_timer = {}
        frames2 = iter([m_claimed, m_claimed])
        task2.device.screenshot.side_effect = lambda: setattr(task2.device, 'image', next(frames2))
        with patch('module.base.timer.time', side_effect=count(100, 3)):
            task2.claim_milestones()
        clicked2 = [c[0][0].name for c in task2.device.click.call_args_list]
        self.assertEqual(clicked2, ['MILESTONES_0_0'])
