import os
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from module.config.server import set_server

# Bind trickcal assets/config before importing module.trickcal.*
set_server('trickcal')

from module.trickcal.assets import (  # noqa: E402
    DOLL_ENTRY,
    DOLL_HUB_TITLE,
    DOLL_STAGE_CHECK,
    DOLL_SWEEP_BTN,
    DOLL_TICKET_CANCEL,
    DOLL_TICKET_EMPTY,
    DUNGEON_CLONE_EMPTY,
    DUNGEON_SWEEP_CONFIRM,
    DUNGEON_SWEEP_TITLE,
    EVENT_STAMINA_BUY,
    EVENT_SWEEP_CLEAR,
    EVENT_SWEEP_MAX,
    LEVEL_UP_POPUP,
)
from module.trickcal.doll import (  # noqa: E402
    DOLL_RACE_AREAS,
    TrickcalDoll,
    doll_sweep_lit,
    read_doll_stamina,
    read_doll_tickets,
)
from module.trickcal.page import page_doll, page_doll_stage  # noqa: E402
from module.trickcal.reward import RewardPopup  # noqa: E402


def _make_doll_task():
    doll = TrickcalDoll.__new__(TrickcalDoll)
    doll.device = MagicMock()
    doll.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
    doll.device.click = MagicMock()
    doll.device.click_record_clear = MagicMock()
    doll.device.screenshot = MagicMock(side_effect=lambda: doll.device.image)
    doll.device.stuck_record_clear = MagicMock()
    doll.loop = MagicMock(side_effect=lambda timeout=10: iter(range(20)))
    doll.ui_ensure = MagicMock()
    doll.ui_goto_main = MagicMock()
    doll.ui_page_appear = MagicMock(return_value=False)
    doll.appear = MagicMock(return_value=False)
    doll.handle_reward_popup = MagicMock(return_value=False)
    doll.config = MagicMock()
    doll.config.TrickcalDoll_Race = 'witch'
    return doll


class TestTrickcalDoll(unittest.TestCase):
    def test_race_areas_and_sweep_lit(self):
        # All 8 races present with distinct non-overlapping tap boxes.
        expected = {'dragon', 'elf', 'ghost', 'fairy', 'witch', 'elemental', 'mystic', 'beast'}
        self.assertEqual(set(DOLL_RACE_AREAS.keys()), expected)
        boxes = list(DOLL_RACE_AREAS.values())
        for i, a in enumerate(boxes):
            self.assertLess(a[0], a[2])
            self.assertLess(a[1], a[3])
            for b in boxes[i + 1:]:
                overlap = a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
                self.assertFalse(overlap)

        DOLL_SWEEP_BTN.ensure_template()
        x1, y1, x2, y2 = DOLL_SWEEP_BTN.area
        img_lit = np.zeros((720, 1280, 3), dtype=np.uint8)
        img_lit[y1:y2, x1:x2] = DOLL_SWEEP_BTN.image
        self.assertTrue(doll_sweep_lit(img_lit))

        img_dim = np.zeros((720, 1280, 3), dtype=np.uint8)
        img_dim[y1:y2, x1:x2] = (150, 150, 150)
        self.assertFalse(doll_sweep_lit(img_dim))

        # Every RewardPopup entry must tap the bottom 「请点击屏幕继续」 region (y >= 540), never the header.
        for btn in RewardPopup.reward_popups:
            self.assertGreaterEqual(btn.button[1], 540, btn.name)

    def test_real_screenshots_when_present(self):
        u_dir = r'C:\Users\14494\.gemini\antigravity\brain\13f03cda-c1d1-419a-8ba6-f6233f3d96d8\.user_uploaded'
        adv_path = r'C:\Users\14494\.gemini\antigravity\brain\13f03cda-c1d1-419a-8ba6-f6233f3d96d8\scratch\dungeon_imgs\MuMu-20261124-223932-361.png'
        hub_path = os.path.join(u_dir, 'media_1795535223483_c5d06a65.jpg')
        stg_path = os.path.join(u_dir, 'media_1795535226736_2eb77287.jpg')
        if not (os.path.exists(adv_path) and os.path.exists(hub_path) and os.path.exists(stg_path)):
            return

        def load_rgb_1280(p):
            bgr = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
            if bgr.shape[:2] != (720, 1280):
                bgr = cv2.resize(bgr, (1280, 720), interpolation=cv2.INTER_CUBIC)
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        adv, hub, stg = load_rgb_1280(adv_path), load_rgb_1280(hub_path), load_rgb_1280(stg_path)
        self.assertTrue(DOLL_ENTRY.appear_on(adv))
        self.assertFalse(DOLL_ENTRY.appear_on(hub))
        self.assertTrue(DOLL_HUB_TITLE.appear_on(hub))
        self.assertFalse(DOLL_HUB_TITLE.appear_on(stg))
        self.assertTrue(DOLL_STAGE_CHECK.appear_on(stg))
        self.assertFalse(DOLL_STAGE_CHECK.appear_on(hub))
        self.assertTrue(doll_sweep_lit(stg))
        self.assertEqual(read_doll_tickets(hub, on_hub=True), 4)
        self.assertEqual(read_doll_tickets(stg, on_hub=False), 3)
        self.assertEqual(read_doll_stamina(stg), 338)

        pop_path = os.path.join(u_dir, 'media_1795536112458_9e27ad03.jpg')
        if os.path.exists(pop_path):
            pop = load_rgb_1280(pop_path)
            self.assertTrue(DOLL_TICKET_EMPTY.appear_on(pop))
            self.assertTrue(DOLL_TICKET_CANCEL.appear_on(pop))
            self.assertFalse(DOLL_TICKET_EMPTY.appear_on(hub))
            self.assertFalse(DOLL_TICKET_EMPTY.appear_on(stg))
            self.assertFalse(DOLL_TICKET_CANCEL.appear_on(hub))
            self.assertFalse(DOLL_TICKET_CANCEL.appear_on(stg))

        lvl_path = os.path.join(u_dir, 'media_1795576095512_eff18e9b.jpg')
        if os.path.exists(lvl_path):
            lvl = load_rgb_1280(lvl_path)
            self.assertTrue(LEVEL_UP_POPUP.appear_on(lvl))
            for other in (adv, hub, stg):
                self.assertFalse(LEVEL_UP_POPUP.appear_on(other))
            if os.path.exists(pop_path):
                self.assertFalse(LEVEL_UP_POPUP.appear_on(pop))
            ui_probe = _make_doll_task()
            ui_probe.device.image = lvl
            ui_probe.appear = lambda btn, offset=(20, 20), interval=0: btn.match(ui_probe.device.image, offset=offset)
            self.assertIs(TrickcalDoll.handle_reward_popup(ui_probe), LEVEL_UP_POPUP)
            ui_probe.device.click.assert_called_once_with(LEVEL_UP_POPUP)

    def test_skip_when_tickets_zero_or_stamina_low(self):
        # Case A: 0/4 daily tickets -> return to lobby cleanly.
        doll = _make_doll_task()
        with patch('module.trickcal.doll.read_doll_tickets', return_value=0), \
             patch('module.trickcal.doll.read_doll_stamina', return_value=200):
            doll.run()
        doll.device.click.assert_not_called()
        doll.ui_goto_main.assert_called_once()
        doll.config.task_delay.assert_called_once_with(server_update=True)

        # Case B: red-candy stamina < 10 -> return to lobby cleanly without clicking race.
        doll2 = _make_doll_task()
        with patch('module.trickcal.doll.read_doll_tickets', return_value=4), \
             patch('module.trickcal.doll.read_doll_stamina', return_value=9):
            doll2.run()
        doll2.device.click.assert_not_called()
        doll2.ui_goto_main.assert_called_once()
        doll2.config.task_delay.assert_called_once_with(server_update=True)

    def test_full_run_witch_and_sweep(self):
        doll = _make_doll_task()
        doll.config.TrickcalDoll_Race = 'witch'
        state = {'page': page_doll, 'tickets': 4, 'stamina': 120, 'in_sweep': False, 'step': 0}
        doll.ui_page_appear.side_effect = lambda p: p == state['page']

        def appear_fn(btn, offset=None, interval=None):
            if not state['in_sweep']:
                return False
            step = state['step']
            if btn == DUNGEON_SWEEP_TITLE and step in (1, 2, 3):
                return True
            if btn == DUNGEON_SWEEP_CONFIRM and step == 2:
                return True
            if btn == EVENT_SWEEP_CLEAR and step == 3:
                return True
            return False

        def click_fn(btn):
            if btn.name == 'DOLL_RACE_WITCH':
                state['page'] = page_doll_stage
            elif btn == DOLL_SWEEP_BTN:
                state['in_sweep'] = True
                state['step'] = 1
            elif btn == EVENT_SWEEP_MAX:
                state['step'] = 2
            elif btn == DUNGEON_SWEEP_CONFIRM:
                state['step'] = 3
            elif btn == EVENT_SWEEP_CLEAR:
                state['in_sweep'] = False
                state['step'] = 4
                state['tickets'] = 0
                state['stamina'] = 80

        doll.appear.side_effect = appear_fn
        doll.device.click.side_effect = click_fn

        with patch('module.trickcal.doll.read_doll_tickets', side_effect=lambda im, on_hub=True: state['tickets']), \
             patch('module.trickcal.doll.read_doll_stamina', side_effect=lambda im: state['stamina']), \
             patch('module.trickcal.doll.doll_sweep_lit', return_value=True), \
             patch('module.trickcal.doll.Timer') as mock_timer:
            mock_timer.return_value.start.return_value = mock_timer.return_value
            mock_timer.return_value.reached.return_value = True
            doll.run()

        clicked_names = [c[0][0].name for c in doll.device.click.call_args_list]
        self.assertEqual(
            clicked_names,
            ['DOLL_RACE_WITCH', 'DOLL_SWEEP_BTN', 'EVENT_SWEEP_MAX', 'DUNGEON_SWEEP_CONFIRM', 'EVENT_SWEEP_CLEAR'],
        )
        doll.ui_goto_main.assert_called_once()
        doll.config.task_delay.assert_called_once_with(server_update=True)

    def test_dim_sweep_stamina_buy_and_empty_toast_guards(self):
        # 1. Dim 速战 aborts without clicking or force-battling.
        doll = _make_doll_task()
        doll.ui_page_appear.side_effect = lambda p: p == page_doll_stage
        with patch('module.trickcal.doll.read_doll_tickets', return_value=4), \
             patch('module.trickcal.doll.read_doll_stamina', return_value=100), \
             patch('module.trickcal.doll.doll_sweep_lit', return_value=False):
            doll.run()
        doll.device.click.assert_not_called()

        # 2. Stamina buy modal cancels safely via 取消.
        doll2 = _make_doll_task()
        buy_open = {'v': True}
        doll2.appear.side_effect = lambda btn, offset=None, interval=None: btn is EVENT_STAMINA_BUY and buy_open['v']
        doll2.device.click.side_effect = lambda btn: buy_open.__setitem__('v', False) if btn is EVENT_STAMINA_BUY else None
        with patch('module.trickcal.doll.Timer') as mock_timer:
            mock_timer.return_value.reached.return_value = True
            self.assertFalse(doll2._open_sweep_dialog())
        doll2.device.click.assert_called_once_with(EVENT_STAMINA_BUY)

        # 3. Exhausted daily entries toast stops sweep loop cleanly.
        doll3 = _make_doll_task()
        doll3.appear.side_effect = lambda btn, offset=None, interval=None: btn is DUNGEON_CLONE_EMPTY
        with patch('module.trickcal.doll.Timer') as mock_timer:
            mock_timer.return_value.reached.return_value = True
            self.assertFalse(doll3._open_sweep_dialog())
        doll3.device.click.assert_not_called()

        # 4. 「入场券不足」 modal cancels safely via 取消 both in _open_sweep_dialog and ui_additional.
        doll4 = _make_doll_task()
        empty_open = {'v': True}
        doll4.appear.side_effect = (
            lambda btn, offset=None, interval=None: btn in (DOLL_TICKET_EMPTY, DOLL_TICKET_CANCEL) and empty_open['v']
        )
        doll4.device.click.side_effect = lambda btn: empty_open.__setitem__('v', False) if btn is DOLL_TICKET_CANCEL else None
        with patch('module.trickcal.doll.Timer') as mock_timer:
            mock_timer.return_value.reached.return_value = True
            self.assertFalse(doll4._open_sweep_dialog())
        doll4.device.click.assert_called_once_with(DOLL_TICKET_CANCEL)

        empty_open['v'] = True
        doll4.device.click.reset_mock()
        self.assertTrue(doll4.ui_additional())
        doll4.device.click.assert_called_once_with(DOLL_TICKET_CANCEL)

    def test_mid_sweep_level_up_dismissed_before_clear(self):
        doll = _make_doll_task()
        state = {'page': page_doll, 'tickets': 4, 'stamina': 120, 'in_sweep': False, 'step': 0}
        doll.ui_page_appear.side_effect = lambda p: p == state['page']

        def appear_fn(btn, offset=None, interval=None):
            if not state['in_sweep']:
                return False
            step = state['step']
            if btn == DUNGEON_SWEEP_TITLE and step in (1, 2):
                return True
            if btn == DUNGEON_SWEEP_CONFIRM and step == 2:
                return True
            if btn == LEVEL_UP_POPUP and step == 3:
                return True
            if btn == EVENT_SWEEP_CLEAR and step == 4:
                return True
            return False

        def handle_reward_fn(interval=2):
            if state['in_sweep'] and state['step'] == 3:
                doll.device.click(LEVEL_UP_POPUP)
                state['step'] = 4
                return LEVEL_UP_POPUP
            return None

        def click_fn(btn):
            if btn.name == 'DOLL_RACE_WITCH':
                state['page'] = page_doll_stage
            elif btn == DOLL_SWEEP_BTN:
                state['in_sweep'] = True
                state['step'] = 1
            elif btn == EVENT_SWEEP_MAX:
                state['step'] = 2
            elif btn == DUNGEON_SWEEP_CONFIRM:
                state['step'] = 3
            elif btn == EVENT_SWEEP_CLEAR:
                state['in_sweep'] = False
                state['step'] = 5
                state['tickets'] = 0

        doll.appear.side_effect = appear_fn
        doll.handle_reward_popup.side_effect = handle_reward_fn
        doll.device.click.side_effect = click_fn

        with patch('module.trickcal.doll.read_doll_tickets', side_effect=lambda im, on_hub=True: state['tickets']), \
             patch('module.trickcal.doll.read_doll_stamina', side_effect=lambda im: state['stamina']), \
             patch('module.trickcal.doll.doll_sweep_lit', return_value=True), \
             patch('module.trickcal.doll.Timer') as mock_timer:
            mock_timer.return_value.start.return_value = mock_timer.return_value
            mock_timer.return_value.reached.return_value = True
            doll.run()

        clicked_names = [c[0][0].name for c in doll.device.click.call_args_list]
        self.assertEqual(
            clicked_names,
            ['DOLL_RACE_WITCH', 'DOLL_SWEEP_BTN', 'EVENT_SWEEP_MAX', 'DUNGEON_SWEEP_CONFIRM', 'LEVEL_UP_POPUP', 'EVENT_SWEEP_CLEAR'],
        )


if __name__ == '__main__':
    unittest.main()
