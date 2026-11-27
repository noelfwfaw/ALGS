"""Offline regressions for Brown Dust II World Boss team page recovery and auto battle."""

import os
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.config import server

_IMPORT_SERVER = server.server
try:
    server.set_server('browndust')

    from module.browndust.assets import (WB_BATTLE_START, WB_EDIT_TEAM,  # noqa: E402
                                     WB_RECOMMEND, WB_RECOMMEND_TITLE,
                                     WB_RESULT_BACK, WB_TEAM_HEADER)
    from module.browndust.browndust_ui import (BrowndustUI, page_event,  # noqa: E402
                                           page_world_boss,
                                           page_world_boss_team)
    from module.browndust.world_boss import (AUTO_BATTLE, AUTO_GLOW,  # noqa: E402
                                         EventWorldBoss, TEAM_TAB_EDIT,
                                         TEAM_TAB_FORMATION, TEAM_TAB_GEAR,
                                         _auto_glow_ratio)
finally:
    server.set_server(_IMPORT_SERVER)


class DummyWorldBoss(EventWorldBoss, BrowndustUI):
    pass


class BrowndustWorldBossTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('browndust')
        self.task = DummyWorldBoss.__new__(DummyWorldBoss)
        self.task.device = Mock()
        self.task.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        for btn in (WB_EDIT_TEAM, WB_RECOMMEND, WB_RECOMMEND_TITLE, WB_TEAM_HEADER):
            self.addCleanup(btn.clear_offset)

    def test_team_header_matches_template_and_links_to_world_boss(self):
        WB_TEAM_HEADER.ensure_template()
        x1, y1, x2, y2 = WB_TEAM_HEADER.area
        self.task.device.image[y1:y2, x1:x2] = WB_TEAM_HEADER.image

        self.assertTrue(WB_TEAM_HEADER.match(self.task.device.image, offset=(20, 20)))
        self.assertIn(page_world_boss_team, BrowndustUI.pages)
        self.assertIn(page_world_boss, page_world_boss_team.links)
        self.assertIn(page_event, page_world_boss.links)

    def test_ensure_team_switches_left_tab_to_reveal_recommend(self):
        state = {'recommend_visible': False}
        clicks = []

        def fake_click(button):
            clicks.append(button)
            if button is TEAM_TAB_FORMATION:
                state['recommend_visible'] = True

        def fake_appear(button, **kwargs):
            if button is WB_TEAM_HEADER:
                return True
            if button is WB_RECOMMEND:
                return state['recommend_visible']
            return False

        def fake_wait(button, **kwargs):
            if button is WB_EDIT_TEAM:
                return True
            if button is WB_RECOMMEND:
                return state['recommend_visible']
            if button is WB_RECOMMEND_TITLE:
                return True
            return False

        self.task.device.click = Mock(side_effect=fake_click)
        self.task.appear = Mock(side_effect=fake_appear)
        self.task.wait_until_appear = Mock(side_effect=fake_wait)
        self.task.wait_until_disappear = Mock(return_value=True)
        self.task.wait_until_still = Mock(return_value=True)
        self.task.recommend_use_top = Mock(return_value=True)
        self.task.team_back = Mock(return_value=True)
        self.task.loop = lambda **kwargs: iter(range(1))

        self.assertTrue(self.task.ensure_team())
        self.assertIn(TEAM_TAB_FORMATION, clicks)
        self.assertIn(WB_RECOMMEND, clicks)
        self.task.recommend_use_top.assert_called_once()
        self.task.team_back.assert_called_once()

    def test_ensure_team_backs_out_when_recommend_never_appears(self):
        clicks = []
        self.task.device.click = Mock(side_effect=lambda b: clicks.append(b))
        self.task.appear = Mock(side_effect=lambda b, **kw: b is WB_TEAM_HEADER)
        self.task.wait_until_appear = Mock(side_effect=lambda b, **kw: b is WB_EDIT_TEAM)
        self.task.team_back = Mock(return_value=True)
        self.task.loop = lambda **kwargs: iter(range(1))

        self.assertFalse(self.task.ensure_team())
        self.assertEqual(
            clicks,
            [WB_EDIT_TEAM, TEAM_TAB_FORMATION, TEAM_TAB_GEAR, TEAM_TAB_FORMATION, TEAM_TAB_EDIT],
        )
        self.task.team_back.assert_called_once()

    def test_real_auto_battle_running_rejects_blue_tent(self):
        shot = os.environ.get('BROWNDUST_WORLD_BOSS_IMAGE')
        if not shot or not os.path.isfile(shot):
            self.skipTest('Set BROWNDUST_WORLD_BOSS_IMAGE to an auto-battle screenshot')
        bgr = cv2.imdecode(np.fromfile(shot, dtype=np.uint8), cv2.IMREAD_COLOR)
        bgr = cv2.resize(bgr, (1280, 720), interpolation=cv2.INTER_CUBIC)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        self.assertTrue(WB_BATTLE_START.match(rgb, offset=(20, 20)))
        self.assertLess(_auto_glow_ratio(rgb), 0.38)
        self.task.device.image = rgb
        self.assertFalse(self.task.auto_battle_running(stable=True))

    def test_auto_battle_running_accepts_synthetic_glow(self):
        # Synthetic AUTO ON frame with 55% vivid cyan-blue glow inside AUTO_GLOW
        glow_img = np.zeros((720, 1280, 3), dtype=np.uint8)
        x0, y0, x1, y1 = AUTO_GLOW
        rows = max(1, int((y1 - y0) * 0.56))
        glow_img[y0:y0 + rows, x0:x1] = (80, 175, 245)
        self.task.device.image = glow_img
        self.assertTrue(self.task.auto_battle_running(stable=True))

    def test_wait_battle_ready_ignores_black_loading_frames(self):
        WB_BATTLE_START.ensure_template()
        x1, y1, x2, y2 = WB_BATTLE_START.area
        black = np.zeros((720, 1280, 3), dtype=np.uint8)
        ready = black.copy()
        ready[y1:y2, x1:x2] = WB_BATTLE_START.image
        frames = [black, black, ready]

        def step_frames(timeout=30):
            for im in frames:
                self.task.device.image = im
                yield im

        self.task.device.stuck_record_clear = Mock()
        self.task.loop = step_frames
        self.assertTrue(self.task._wait_battle_ready(timeout=5))

    def test_wb_wait_end_starts_timer_and_recovers_battle_stall(self):
        state = {'frame': 0, 'stalled': True}

        def fake_appear(btn, **kwargs):
            if btn is WB_RESULT_BACK:
                return not state['stalled']
            if btn is WB_BATTLE_START:
                return state['stalled']
            return False

        def fake_click(btn):
            if btn is AUTO_BATTLE:
                state['stalled'] = False

        self.task.device.click = Mock(side_effect=fake_click)
        self.task.device.stuck_record_clear = Mock()
        self.task.handle_payment_error = Mock(return_value=False)
        self.task.appear = Mock(side_effect=fake_appear)
        self.task.auto_battle_running = Mock(return_value=True)
        self.task.auto_battle_on = Mock()
        self.task.loop = lambda timeout=900: iter(range(10))

        timer_inst = Mock()
        timer_inst.start.return_value = timer_inst
        # Frame 0 must NOT trigger timer immediately; checks 1 and 2 are both stalled -> force-tap AUTO_BATTLE
        timer_inst.reached.side_effect = [False, True, True, False]

        with patch('module.browndust.world_boss.Timer', return_value=timer_inst):
            self.assertTrue(self.task.wb_wait_end())

        timer_inst.start.assert_called_once()
        self.task.auto_battle_on.assert_not_called()
        self.task.device.click.assert_called_once_with(AUTO_BATTLE)


if __name__ == '__main__':
    unittest.main()
