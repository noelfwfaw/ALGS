import os
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from module.config.server import set_server

# Bind trickcal assets/config before importing module.trickcal.*
set_server('trickcal')

from module.trickcal.assets import (  # noqa: E402
    LEVEL_UP_POPUP,
    PVP_ARENA_ENTER,
    PVP_ARENA_TITLE,
    PVP_BUY_ATTEMPTS,
    PVP_BUY_CANCEL,
    PVP_CLAIM_REWARD,
    PVP_ENTRY,
    PVP_GO_WIN,
    PVP_HUB_TITLE,
    PVP_RESULT_EXIT,
)
from module.trickcal.page import page_pvp_arena, page_pvp_deck  # noqa: E402
from module.trickcal.pvp import (  # noqa: E402
    TrickcalPvp,
    pvp_claim_lit,
    read_pvp_attempts,
)


def _make_pvp_claim_images():
    PVP_CLAIM_REWARD.ensure_template()
    x1, y1, x2, y2 = PVP_CLAIM_REWARD.area
    img_blank = np.zeros((720, 1280, 3), dtype=np.uint8)
    img_lit = img_blank.copy()
    img_lit[y1:y2, x1:x2] = PVP_CLAIM_REWARD.image

    img_dim = img_blank.copy()
    img_dim[y1:y2, x1:x2] = np.clip(PVP_CLAIM_REWARD.image.astype(np.float32) * 0.4, 0, 255).astype(np.uint8)
    return img_blank, img_lit, img_dim


def _make_pvp_task():
    pvp = TrickcalPvp.__new__(TrickcalPvp)
    pvp.device = MagicMock()
    pvp.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
    pvp.device.click = MagicMock()
    pvp.device.click_record_clear = MagicMock()
    pvp.device.screenshot = MagicMock(side_effect=lambda: pvp.device.image)
    pvp.device.stuck_record_clear = MagicMock()
    pvp.loop = MagicMock(side_effect=lambda timeout=10: iter(range(20)))
    pvp.ui_ensure = MagicMock()
    pvp.ui_goto_main = MagicMock()
    pvp.ui_page_appear = MagicMock(return_value=False)
    pvp.appear = MagicMock(return_value=False)
    pvp.handle_reward_popup = MagicMock(return_value=False)
    pvp.config = MagicMock()
    pvp.config.TrickcalPvp_Opponent = 1
    return pvp


class TestTrickcalPvp(unittest.TestCase):
    def test_real_screenshots_and_claim_lit(self):
        img_blank, img_lit, img_dim = _make_pvp_claim_images()
        self.assertFalse(PVP_CLAIM_REWARD.match_luma(img_blank, offset=(20, 20)))
        self.assertTrue(PVP_CLAIM_REWARD.match_luma(img_lit, offset=(20, 20)))
        self.assertTrue(pvp_claim_lit(img_lit))
        self.assertTrue(PVP_CLAIM_REWARD.match_luma(img_dim, offset=(20, 20)))
        self.assertFalse(pvp_claim_lit(img_dim))

        u_dir = r'C:\Users\14494\.gemini\antigravity\brain\13f03cda-c1d1-419a-8ba6-f6233f3d96d8\.user_uploaded'
        paths = {
            'adv': os.path.join(u_dir, 'media_1795576723965_d73212fa.jpg'),
            'hub': os.path.join(u_dir, 'media_1795576729079_d981570e.jpg'),
            'arena': os.path.join(u_dir, 'media_1795576734530_a11bc9de.jpg'),
            'deck': os.path.join(u_dir, 'media_1795576737909_4218eb4d.jpg'),
            'res': os.path.join(u_dir, 'media_1795576744339_61381c48.jpg'),
        }
        if not all(os.path.exists(p) for p in paths.values()):
            return

        def load_rgb_1280(p):
            bgr = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
            if bgr.shape[:2] != (720, 1280):
                bgr = cv2.resize(bgr, (1280, 720), interpolation=cv2.INTER_CUBIC)
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        imgs = {k: load_rgb_1280(p) for k, p in paths.items()}
        expected = [
            (PVP_ENTRY, 'adv'),
            (PVP_HUB_TITLE, 'hub'),
            (PVP_ARENA_ENTER, 'hub'),
            (PVP_ARENA_TITLE, 'arena'),
            (PVP_GO_WIN, 'deck'),
            (PVP_RESULT_EXIT, 'res'),
        ]
        for btn, target_k in expected:
            for k, im in imgs.items():
                if k == target_k:
                    self.assertTrue(btn.match(im, offset=(20, 20)), f'{btn.name} on {k}')
                else:
                    self.assertFalse(btn.match(im, offset=(20, 20)), f'{btn.name} false positive on {k}')

        self.assertEqual(read_pvp_attempts(imgs['hub'], on_hub=True), 5)
        self.assertEqual(read_pvp_attempts(imgs['arena'], on_hub=False), 5)
        self.assertTrue(PVP_CLAIM_REWARD.match_luma(imgs['arena'], offset=(20, 20)))
        self.assertFalse(pvp_claim_lit(imgs['arena']))

        lit_path = os.path.join(u_dir, 'media_1795581748279_78e2af51.jpg')
        if os.path.exists(lit_path):
            lit = load_rgb_1280(lit_path)
            self.assertTrue(PVP_CLAIM_REWARD.match(lit, offset=(20, 20)))
            self.assertTrue(PVP_CLAIM_REWARD.match_luma(lit, offset=(20, 20)))
            self.assertTrue(pvp_claim_lit(lit))
            self.assertEqual(read_pvp_attempts(lit, on_hub=False), 0)
            for k in ('adv', 'hub', 'deck', 'res'):
                self.assertFalse(PVP_CLAIM_REWARD.match(imgs[k], offset=(20, 20)), k)

        pop_path = os.path.join(u_dir, 'media_1795577431014_83de8cc7.jpg')
        if os.path.exists(pop_path):
            pop = load_rgb_1280(pop_path)
            self.assertTrue(PVP_BUY_ATTEMPTS.match(pop, offset=(20, 20)))
            self.assertTrue(PVP_BUY_CANCEL.match(pop, offset=(20, 20)))
            for k in ('hub', 'arena', 'deck', 'res'):
                self.assertFalse(PVP_BUY_ATTEMPTS.match(imgs[k], offset=(20, 20)), k)
                self.assertFalse(PVP_BUY_CANCEL.match(imgs[k], offset=(20, 20)), k)

    def test_skip_when_attempts_zero_claims_lit_hourly_reward(self):
        pvp = _make_pvp_task()
        img_blank, img_lit, img_dim = _make_pvp_claim_images()
        state = {'blank_frames': 2, 'popup': False, 'claimed': False}
        pvp.device.image = img_blank

        def page_appear(p):
            if p is not page_pvp_arena:
                return False
            if not state['claimed'] and not state['popup']:
                if state['blank_frames'] > 0:
                    state['blank_frames'] -= 1
                    pvp.device.image = img_blank
                else:
                    pvp.device.image = img_lit
            return True

        pvp.ui_page_appear.side_effect = page_appear

        def handle_popup():
            if state['popup']:
                state['popup'] = False
                pvp.device.image = img_dim
                return True
            return False

        pvp.handle_reward_popup.side_effect = handle_popup

        def on_click(btn):
            if btn is PVP_CLAIM_REWARD:
                state['claimed'] = True
                state['popup'] = True

        pvp.device.click.side_effect = on_click

        with patch('module.trickcal.pvp.read_pvp_attempts', return_value=0), \
             patch('module.trickcal.pvp.Timer') as mock_timer:
            mock_timer.return_value.reached.return_value = True
            pvp.run()

        clicked_names = [c[0][0].name for c in pvp.device.click.call_args_list]
        self.assertEqual(clicked_names, ['PVP_CLAIM_REWARD'])
        self.assertGreaterEqual(pvp.handle_reward_popup.call_count, 1)
        pvp.ui_goto_main.assert_called_once()
        pvp.config.task_delay.assert_called_once_with(server_update=True)

    def test_full_match_opponent_1_with_level_up_and_exit(self):
        pvp = _make_pvp_task()
        _, _, img_dim = _make_pvp_claim_images()
        pvp.device.image = img_dim
        state = {'page': page_pvp_arena, 'rem': 1, 'phase': 'arena'}
        pvp.ui_page_appear.side_effect = lambda p: p is state['page']

        def appear_fn(btn, offset=None, interval=None):
            if btn == PVP_GO_WIN and state['phase'] == 'deck':
                return True
            if btn == PVP_RESULT_EXIT and state['phase'] == 'result':
                return True
            return False

        def reward_fn(interval=2):
            if state['phase'] == 'battle_lvl':
                pvp.device.click(LEVEL_UP_POPUP)
                state['phase'] = 'result'
                return LEVEL_UP_POPUP
            return None

        def click_fn(btn):
            if btn.name == 'PVP_OPPONENT_1':
                state['page'] = page_pvp_deck
                state['phase'] = 'deck'
            elif btn == PVP_GO_WIN:
                state['page'] = None
                state['phase'] = 'battle_lvl'
            elif btn == PVP_RESULT_EXIT:
                state['page'] = page_pvp_arena
                state['phase'] = 'arena'
                state['rem'] = 0

        pvp.appear.side_effect = appear_fn
        pvp.handle_reward_popup.side_effect = reward_fn
        pvp.device.click.side_effect = click_fn

        with patch('module.trickcal.pvp.read_pvp_attempts', side_effect=lambda im, on_hub=False: state['rem']), \
             patch('module.trickcal.pvp.Timer') as mock_timer:
            mock_timer.return_value.start.return_value = mock_timer.return_value
            mock_timer.return_value.reached.return_value = True
            pvp.run()

        clicked_names = [c[0][0].name for c in pvp.device.click.call_args_list]
        self.assertEqual(
            clicked_names,
            ['PVP_OPPONENT_1', 'PVP_GO_WIN', 'LEVEL_UP_POPUP', 'PVP_RESULT_EXIT'],
        )
        pvp.ui_goto_main.assert_called_once()
        pvp.config.task_delay.assert_called_once_with(server_update=True)

    def test_ui_additional_dismisses_leftover_result_exit(self):
        pvp = _make_pvp_task()
        pvp.appear.side_effect = lambda btn, offset=None, interval=None: btn is PVP_RESULT_EXIT
        self.assertTrue(pvp.ui_additional())
        pvp.device.click.assert_called_once_with(PVP_RESULT_EXIT)

    def test_buy_attempts_popup_cancels_without_buying(self):
        pvp = _make_pvp_task()
        buy_open = {'v': True}
        pvp.appear.side_effect = (
            lambda btn, offset=None, interval=None: btn in (PVP_BUY_ATTEMPTS, PVP_BUY_CANCEL) and buy_open['v']
        )
        pvp.device.click.side_effect = lambda btn: buy_open.__setitem__('v', False) if btn is PVP_BUY_CANCEL else None
        with patch('module.trickcal.pvp.Timer') as mock_timer:
            mock_timer.return_value.reached.return_value = True
            self.assertFalse(pvp._open_opponent_deck(1))
        pvp.device.click.assert_called_once_with(PVP_BUY_CANCEL)

        buy_open['v'] = True
        pvp.device.click.reset_mock()
        self.assertTrue(pvp.ui_additional())
        pvp.device.click.assert_called_once_with(PVP_BUY_CANCEL)


if __name__ == '__main__':
    unittest.main()
