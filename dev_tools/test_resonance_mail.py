import os
import unittest
from itertools import count
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.base.utils import load_image
from module.config import server


def _paste_button(canvas, button, dx=0, dy=0):
    x1, y1, x2, y2 = button.area
    patch = load_image(button.file, button.area)
    canvas[y1 + dy:y2 + dy, x1 + dx:x2 + dx] = patch


def _blank_with(*buttons):
    canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
    for btn in buttons:
        _paste_button(canvas, btn)
    return canvas


class TestResonanceMail(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def test_mail_assets_match_real_screenshots_with_and_without_red_dot(self):
        from module.resonance import assets
        from module.resonance.mail import has_claimable_mail

        base = 'C:/Users/14494/Documents/MuMu共享文件夹/Screenshots/'
        f_drawer = base + 'MuMu-20261125-213613-646.png'
        f_mail = base + 'MuMu-20261125-213616-714.png'
        if not (os.path.exists(f_drawer) and os.path.exists(f_mail)):
            return

        drawer = np.array(Image.open(f_drawer).convert('RGB'))
        self.assertTrue(assets.MAIL_ENTRY.match(drawer, offset=(5, 5)))
        # Mask unread red dot with sidebar blue to confirm matching even with 0 unread mail
        no_dot = drawer.copy()
        no_dot[490:515, 48:68] = no_dot[480, 30]
        self.assertTrue(assets.MAIL_ENTRY.match(no_dot, offset=(5, 5)))

        mail = np.array(Image.open(f_mail).convert('RGB'))
        self.assertTrue(assets.MAIL_CHECK.match(mail, offset=(5, 5)))
        self.assertTrue(assets.MAIL_CLAIM_ALL.match(mail, offset=(5, 5)))
        self.assertTrue(has_claimable_mail(mail))

        # When all mails are already claimed ('已领取'), yellow '一键领取' remains visible
        no_blue = mail.copy()
        no_blue[70:620, 1065:1215] = (180, 180, 180)
        self.assertFalse(has_claimable_mail(no_blue))
        self.assertTrue(assets.MAIL_CLAIM_ALL.match(no_blue, offset=(5, 5)))

    def test_mail_page_exit_routes_via_daily_home_not_op_back(self):
        from module.resonance.assets import DAILY_HOME, OP_BACK
        from module.resonance.page import page_main, page_resonance_mail

        self.assertIn(page_main, page_resonance_mail.links)
        self.assertIs(page_resonance_mail.links[page_main], DAILY_HOME)
        self.assertNotIn(OP_BACK, page_resonance_mail.links.values())

    def test_reward_popup_matches_vertically_shifted_login_reward(self):
        from module.resonance import assets
        from module.resonance.mail import ResonanceMail

        for dy in (-80, 80):
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            _paste_button(frame, assets.LOGIN_REWARD, dy=dy)

            task = ResonanceMail.__new__(ResonanceMail)
            task.device = Mock()
            task.config = Mock()
            task.interval_timer = {}
            task.device.image = frame

            self.assertTrue(task.handle_reward_popup())
            clicked_btn = task.device.click.call_args[0][0]
            self.assertEqual(clicked_btn.name, 'LOGIN_REWARD')
            x1, y1, x2, y2 = clicked_btn.button
            self.assertTrue(0 <= x1 < x2 <= 1280 and 0 <= y1 < y2 <= 720)

    def test_mail_run_opens_claims_dismisses_reward_and_schedules(self):
        from module.resonance import assets
        from module.resonance.mail import ResonanceMail
        from module.resonance.page import page_main

        main_frame = _blank_with(assets.MAIN_CHECK)
        drawer_frame = _blank_with(assets.PROFILE_DRAWER_CHECK, assets.MAIL_ENTRY)
        mail_empty = _blank_with(assets.MAIL_CHECK, assets.MAIL_CLAIM_ALL)
        mail_claimable = mail_empty.copy()
        mail_claimable[150:210, 1075:1195] = (40, 140, 230)
        reward_shifted = np.zeros((720, 1280, 3), dtype=np.uint8)
        _paste_button(reward_shifted, assets.LOGIN_REWARD, dy=-80)

        task = ResonanceMail.__new__(ResonanceMail)
        task.device = Mock()
        task.config = Mock()
        task.interval_timer = {}
        task.ui_ensure = Mock()
        task.ui_goto_main = Mock()
        task.device.image = main_frame

        frames = iter([main_frame, drawer_frame, mail_claimable, reward_shifted, mail_empty])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 2.5)):
            task.run()

        task.ui_ensure.assert_called_once_with(page_main, skip_first_screenshot=True)
        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in task.device.click.call_args_list]
        self.assertEqual(clicked, ['MAIN_AVATAR', 'MAIL_ENTRY', 'MAIL_CLAIM_ALL', 'LOGIN_REWARD'])
        task.ui_goto_main.assert_called_once()
        task.config.task_delay.assert_called_once_with(server_update=True)

    def test_mail_run_starts_from_profile_drawer_and_skips_when_already_claimed(self):
        from module.resonance import assets
        from module.resonance.mail import ResonanceMail

        drawer_frame = _blank_with(assets.PROFILE_DRAWER_CHECK, assets.MAIL_ENTRY)
        mail_empty = _blank_with(assets.MAIL_CHECK, assets.MAIL_CLAIM_ALL)

        task = ResonanceMail.__new__(ResonanceMail)
        task.device = Mock()
        task.config = Mock()
        task.interval_timer = {}
        task.ui_ensure = Mock()
        task.ui_goto_main = Mock()
        task.device.image = drawer_frame

        frames = iter([drawer_frame, mail_empty, mail_empty])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 2.5)):
            task.run()

        task.ui_ensure.assert_not_called()
        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in task.device.click.call_args_list]
        self.assertEqual(clicked, ['MAIL_ENTRY'])
        task.ui_goto_main.assert_called_once()
        task.config.task_delay.assert_called_once_with(server_update=True)
