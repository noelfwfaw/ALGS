import os
import unittest
from itertools import count
from unittest.mock import Mock, call, patch

import numpy as np
from PIL import Image

from module.base.utils import load_image
from module.config import server


def _paste_button(canvas, button, dx=0, dy=0):
    x1, y1, x2, y2 = button.area
    canvas[y1 + dy:y2 + dy, x1 + dx:x2 + dx] = load_image(button.file, button.area)


def _blank_with(*buttons):
    canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
    for btn in buttons:
        _paste_button(canvas, btn)
    return canvas


def _make_dispatch_screen(cards_state=None, selected_dur='4h', send_ready=False, recall=False, card_order=None):
    from module.resonance import assets
    from module.resonance.dispatch import CARD_XRANGES, DISPATCH_TASK_KEYS, DURATION_BOXES

    frame = _blank_with(assets.DISPATCH_CHECK)
    if cards_state is None:
        cards_state = ['idle'] * 5
    if card_order is None:
        card_order = DISPATCH_TASK_KEYS
    for idx, state in enumerate(cards_state):
        cx1, cx2 = CARD_XRANGES[idx]
        if state == 'idle':
            frame[86:103, cx1 + 20:cx2 - 20] = (89, 142, 251)
        elif state == 'active':
            frame[86:103, cx1 + 20:cx2 - 20] = (253, 193, 34)
        else:
            frame[86:103, cx1 + 20:cx2 - 20] = (140, 140, 140)
        task_key = card_order[idx]
        if task_key:
            tpl = load_image(getattr(assets, f'TEMPLATE_DISPATCH_{task_key.upper()}').file)
            th, tw = tpl.shape[:2]
            frame[128:128 + th, cx1 + 55:cx1 + 55 + tw] = tpl

    if selected_dur in DURATION_BOXES:
        for dur, (x1, y1, x2, y2) in DURATION_BOXES.items():
            if dur == selected_dur:
                frame[y1:y2, x1:x2] = (215, 158, 7)
            else:
                frame[y1:y2, x1:x2] = (85, 136, 235)

    if send_ready:
        _paste_button(frame, assets.DISPATCH_SEND_READY)
        frame[618:658, 925:1055] = np.maximum(frame[618:658, 925:1055], np.array([170, 130, 10], dtype=np.uint8))
    if recall:
        _paste_button(frame, assets.DISPATCH_RECALL)
        frame[605:665, 930:1220] = np.maximum(frame[605:665, 930:1220], np.array([180, 35, 35], dtype=np.uint8))
    return frame


def _make_crew_drawer(selected_indices=()):
    from module.resonance import assets
    from module.resonance.dispatch import CREW_SLOTS

    frame = _blank_with(assets.DISPATCH_CHECK, assets.DISPATCH_CREW_DRAWER)
    for idx, (_, _, _, (nx1, ny1, nx2, ny2)) in enumerate(CREW_SLOTS):
        if idx in selected_indices:
            frame[ny1:ny2, nx1:nx2] = (110, 155, 226)
        else:
            frame[ny1:ny2, nx1:nx2] = (110, 105, 104)
    return frame


def _new_dispatch_task(task1='patrol', task2='drill', duration='12h'):
    from module.resonance.dispatch import ResonanceDispatch

    task = ResonanceDispatch.__new__(ResonanceDispatch)
    task.device = Mock()
    task.config = Mock()
    task.config.ResonanceDispatch_Task1 = task1
    task.config.ResonanceDispatch_Task2 = task2
    task.config.ResonanceDispatch_Duration = duration
    task.interval_timer = {}
    task.ui_ensure = Mock()
    task.ui_goto_main = Mock()
    return task


class TestResonanceDispatch(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def test_dispatch_assets_and_helpers_on_real_screenshots(self):
        from module.resonance import assets
        from module.resonance.dispatch import (
            CREW_SLOTS, classify_card_state, is_duration_selected, is_portrait_selected, is_recall_red_visible,
            is_send_yellow_visible, parse_card_remaining_minutes, parse_team_count,
        )

        base = 'C:/Users/14494/Documents/MuMu共享文件夹/Screenshots/'
        files = {
            'term': base + 'MuMu-20261126-000931-316.png',
            'disp0': base + 'MuMu-20261125-233828-187.png',
            'crew0': base + 'MuMu-20261125-233855-221.png',
            'crew5': base + 'MuMu-20261126-004148-796.png',
            'ready5': base + 'MuMu-20261126-004156-542.png',
            'run1': base + 'MuMu-20261126-004234-814.png',
        }
        if not all(os.path.exists(p) for p in files.values()):
            return

        imgs = {k: np.array(Image.open(p).convert('RGB')) for k, p in files.items()}
        self.assertTrue(assets.TERMINAL_DISPATCH_ENTRY.match(imgs['term'], offset=(5, 5)))
        for k in ('disp0', 'crew0', 'crew5', 'ready5', 'run1'):
            self.assertTrue(assets.DISPATCH_CHECK.match(imgs[k], offset=(5, 5)))

        self.assertTrue(assets.DISPATCH_CREW_DRAWER.match(imgs['crew0'], offset=(5, 5)))
        self.assertTrue(assets.DISPATCH_CREW_DRAWER.match(imgs['crew5'], offset=(5, 5)))
        self.assertFalse(assets.DISPATCH_CREW_DRAWER.match(imgs['ready5'], offset=(5, 5)))

        self.assertFalse(is_send_yellow_visible(imgs['disp0']))
        self.assertTrue(is_send_yellow_visible(imgs['ready5']))
        self.assertTrue(assets.DISPATCH_SEND_READY.match(imgs['ready5'], offset=(5, 5)))

        self.assertTrue(assets.DISPATCH_RECALL.match(imgs['run1'], offset=(5, 5)))
        self.assertTrue(is_recall_red_visible(imgs['run1']))
        self.assertFalse(is_recall_red_visible(imgs['ready5']))

        for idx in range(5):
            self.assertEqual(classify_card_state(imgs['disp0'], idx), 'idle')
        self.assertEqual(classify_card_state(imgs['run1'], 0), 'active')
        self.assertEqual(classify_card_state(imgs['run1'], 1), 'idle')

        self.assertTrue(is_duration_selected(imgs['disp0'], '4h'))
        self.assertFalse(is_duration_selected(imgs['disp0'], '12h'))

        for idx in range(5):
            self.assertTrue(is_portrait_selected(imgs['crew5'], CREW_SLOTS[idx][3]))
            self.assertFalse(is_portrait_selected(imgs['crew5'], CREW_SLOTS[idx + 5][3]))

        self.assertEqual(parse_team_count(imgs['disp0']), (0, 2))
        self.assertEqual(parse_team_count(imgs['run1']), (1, 2))
        self.assertIn(parse_card_remaining_minutes(imgs['run1'], 0), (239, 240))
        report_path = base + 'MuMu-20261126-141011-186.png'
        if os.path.exists(report_path):
            report_img = np.array(Image.open(report_path).convert('RGB'))
            self.assertTrue(assets.DISPATCH_REPORT.match(report_img, offset=(5, 5)))
            self.assertFalse(assets.DISPATCH_CHECK.match(report_img, offset=(5, 5)))
        for k, img in imgs.items():
            self.assertFalse(assets.DISPATCH_REPORT.match(img, offset=(5, 5)), k)

    def test_dispatch_page_graph_links(self):
        from module.resonance.assets import DAILY_HOME, MAIN_TERMINAL, OP_BACK, TERMINAL_DISPATCH_ENTRY
        from module.resonance.page import page_main, page_resonance_dispatch, page_resonance_terminal

        self.assertIs(page_main.links[page_resonance_terminal], MAIN_TERMINAL)
        self.assertIs(page_resonance_terminal.links[page_resonance_dispatch], TERMINAL_DISPATCH_ENTRY)
        self.assertIs(page_resonance_dispatch.links[page_main], DAILY_HOME)
        self.assertIs(page_resonance_dispatch.links[page_resonance_terminal], OP_BACK)

    def test_dispatch_run_sends_two_squads_and_skips_busy_portraits(self):
        from module.resonance.page import page_resonance_dispatch

        disp_idle_4h = _make_dispatch_screen(['idle'] * 5, selected_dur='4h')
        disp_idle_12h = _make_dispatch_screen(['idle'] * 5, selected_dur='12h')
        drawer_open = _make_crew_drawer(())
        drawer_row0_done = _make_crew_drawer(set(range(5)))
        disp_ready_1 = _make_dispatch_screen(['idle'] * 5, selected_dur='12h', send_ready=True)
        disp_after_1 = _make_dispatch_screen(['active', 'idle', 'idle', 'idle', 'idle'], selected_dur='4h')
        disp_after_1_12h = _make_dispatch_screen(['active', 'idle', 'idle', 'idle', 'idle'], selected_dur='12h')
        # Team 2: Row 0 members are busy (stay unselected), so fallback picks Row 1 (indices 5..9)
        drawer_row1_done = _make_crew_drawer(set(range(5, 10)))
        disp_ready_2 = _make_dispatch_screen(
            ['active', 'idle', 'idle', 'idle', 'idle'], selected_dur='12h', send_ready=True
        )
        disp_after_2 = _make_dispatch_screen(['active', 'active', 'idle', 'idle', 'idle'], selected_dur='4h')

        task = _new_dispatch_task(task1='patrol', task2='drill', duration='12h')
        task.device.image = disp_idle_4h

        frames = iter([
            # Team 1 (patrol): select card 0 -> 12h -> open drawer -> click Row 0 -> 1 screenshot -> close -> send
            disp_idle_4h,
            disp_idle_12h,
            drawer_open,
            drawer_row0_done,
            disp_ready_1,
            disp_after_1,
            # Team 2 (drill): select card 1 -> 12h -> open drawer -> Row 0 stays 0 -> click Row 1 -> close -> send
            disp_after_1,
            disp_after_1_12h,
            drawer_open,
            drawer_open,
            drawer_row1_done,
            disp_ready_2,
            disp_after_2,
        ])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))

        with patch('module.resonance.dispatch.parse_team_count', return_value=(0, 2)), \
             patch('module.base.timer.time', side_effect=count(100, 3.0)):
            task.run()

        task.ui_ensure.assert_called_once_with(page_resonance_dispatch, skip_first_screenshot=False)
        task.device.swipe.assert_not_called()
        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in task.device.click.call_args_list]
        self.assertEqual(
            clicked,
            [
                'DISPATCH_CARD_0', 'DISPATCH_DUR_12h', 'DISPATCH_PLUS_0',
                'DISPATCH_CREW_0_0', 'DISPATCH_CREW_0_1', 'DISPATCH_CREW_0_2', 'DISPATCH_CREW_0_3', 'DISPATCH_CREW_0_4',
                'DISPATCH_CREW_DRAWER', 'DISPATCH_SEND_READY',
                'DISPATCH_CARD_1', 'DISPATCH_DUR_12h', 'DISPATCH_PLUS_0',
                'DISPATCH_CREW_0_0', 'DISPATCH_CREW_0_1', 'DISPATCH_CREW_0_2', 'DISPATCH_CREW_0_3', 'DISPATCH_CREW_0_4',
                'DISPATCH_CREW_1_0', 'DISPATCH_CREW_1_1', 'DISPATCH_CREW_1_2', 'DISPATCH_CREW_1_3', 'DISPATCH_CREW_1_4',
                'DISPATCH_CREW_DRAWER', 'DISPATCH_SEND_READY',
            ],
        )
        task.ui_goto_main.assert_called_once()
        task.config.task_delay.assert_called_once_with(minute=721)

    def test_dispatch_claims_completed_and_tracks_running_without_recall(self):
        disp_running = _make_dispatch_screen(['active', 'other', 'idle', 'idle', 'idle'], selected_dur=None, recall=False)
        disp_card0_running = _make_dispatch_screen(['active', 'other', 'idle', 'idle', 'idle'], selected_dur=None, recall=True)
        disp_card1_done = _make_dispatch_screen(['active', 'other', 'idle', 'idle', 'idle'], selected_dur=None, recall=False)
        reward_popup = _blank_with(__import__('module.resonance.assets', fromlist=['LOGIN_REWARD']).LOGIN_REWARD)
        disp_after_claim = _make_dispatch_screen(['active', 'idle', 'idle', 'idle', 'idle'], selected_dur='4h', recall=False)
        disp_card0_after_claim = _make_dispatch_screen(
            ['active', 'idle', 'idle', 'idle', 'idle'], selected_dur=None, recall=True
        )

        task = _new_dispatch_task(task1='patrol', task2='none', duration='12h')
        task.device.image = disp_running

        frames = iter([
            # Inspect card 0 (running) -> click card 0 -> sees recall
            disp_card0_running,
            # Inspect card 1 (completed, no recall, no duration highlight) -> click card 1 -> click claim -> reward -> back
            disp_card1_done,
            reward_popup,
            disp_after_claim,
            # Rescan remaining running card 0 after card order settles
            disp_card0_after_claim,
        ])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))

        with patch('module.resonance.dispatch.parse_card_remaining_minutes', return_value=145), \
             patch('module.resonance.dispatch.parse_team_count', return_value=(1, 1)), \
             patch('module.base.timer.time', side_effect=count(100, 3.0)):
            task.run()

        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in task.device.click.call_args_list]
        self.assertEqual(
            clicked,
            ['DISPATCH_CARD_0', 'DISPATCH_CARD_1', 'DISPATCH_CLAIM', 'LOGIN_REWARD', 'DISPATCH_CARD_0'],
        )
        self.assertNotIn('DISPATCH_RECALL', clicked)
        task.ui_goto_main.assert_called_once()
        task.config.task_delay.assert_called_once_with(minute=146)

    def test_dispatch_enable_checkbox_visible_in_webui_and_args(self):
        import json

        with open('assets/gui/css/alas.css', encoding='utf-8') as f:
            css = f.read()
        self.assertNotIn('[id*="ch_S"]', css)
        with open('module/config/argument/args.json', encoding='utf-8') as f:
            args = json.load(f)
        self.assertEqual(args['ResonanceDispatch']['Scheduler']['Enable']['type'], 'checkbox')

    def test_shifted_cards_find_idle_task_slot_on_real_screenshot(self):
        from module.resonance.dispatch import count_active_cards, find_idle_task_slot

        shot = (
            'C:/Users/14494/.gemini/antigravity/brain/'
            'd55a543a-0e07-40cd-8969-2f09462460b5/.user_uploaded/media_1795626695383_c6049b53.jpg'
        )
        if not os.path.exists(shot):
            return
        im = np.array(Image.open(shot).convert('RGB').resize((1280, 720), Image.BILINEAR))
        self.assertEqual(count_active_cards(im), 1)
        self.assertIsNone(find_idle_task_slot(im, 'enhance'))
        self.assertEqual(find_idle_task_slot(im, 'patrol'), 1)
        self.assertEqual(find_idle_task_slot(im, 'drill'), 2)
        self.assertEqual(find_idle_task_slot(im, 'collect'), 3)
        self.assertEqual(find_idle_task_slot(im, 'materialize'), 4)

    def test_dispatch_handles_card_reordering_between_two_squads(self):
        from module.resonance.page import page_resonance_dispatch

        order_initial = ('patrol', 'drill', 'collect', 'materialize', 'enhance')
        # After dispatching enhance (originally slot 4), enhance jumps to slot 0 and drill shifts to slot 2
        order_shifted = ('enhance', 'patrol', 'drill', 'collect', 'materialize')

        disp_init_4h = _make_dispatch_screen(['idle'] * 5, selected_dur='4h', card_order=order_initial)
        disp_init_20h = _make_dispatch_screen(['idle'] * 5, selected_dur='20h', card_order=order_initial)
        drawer_open = _make_crew_drawer(())
        drawer_row0 = _make_crew_drawer(set(range(5)))
        disp_ready_1 = _make_dispatch_screen(['idle'] * 5, selected_dur='20h', send_ready=True, card_order=order_initial)

        disp_after_1 = _make_dispatch_screen(
            ['active', 'idle', 'idle', 'idle', 'idle'], selected_dur='4h', card_order=order_shifted
        )
        disp_after_1_20h = _make_dispatch_screen(
            ['active', 'idle', 'idle', 'idle', 'idle'], selected_dur='20h', card_order=order_shifted
        )
        drawer_row1 = _make_crew_drawer(set(range(5, 10)))
        disp_ready_2 = _make_dispatch_screen(
            ['active', 'idle', 'idle', 'idle', 'idle'], selected_dur='20h', send_ready=True, card_order=order_shifted
        )
        disp_after_2 = _make_dispatch_screen(
            ['active', 'idle', 'active', 'idle', 'idle'], selected_dur='4h',
            card_order=('enhance', 'patrol', 'drill', 'collect', 'materialize'),
        )

        task = _new_dispatch_task(task1='enhance', task2='drill', duration='20h')
        task.device.image = disp_init_4h

        frames = iter([
            # Team 1 (enhance -> slot 4): select card 4 -> 20h -> crew -> send
            disp_init_4h,
            disp_init_20h,
            drawer_open,
            drawer_row0,
            disp_ready_1,
            disp_after_1,
            # Team 2 (drill shifted to slot 2): select card 2 -> 20h -> crew -> send
            disp_after_1,
            disp_after_1_20h,
            drawer_open,
            drawer_open,
            drawer_row1,
            disp_ready_2,
            disp_after_2,
        ])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))

        with patch('module.resonance.dispatch.parse_team_count', return_value=(0, 2)), \
             patch('module.base.timer.time', side_effect=count(100, 3.0)):
            task.run()

        task.ui_ensure.assert_called_once_with(page_resonance_dispatch, skip_first_screenshot=False)
        clicked = [getattr(c[0][0], 'name', str(c[0][0])) for c in task.device.click.call_args_list]
        self.assertIn('DISPATCH_CARD_4', clicked)
        self.assertIn('DISPATCH_CARD_2', clicked)
        self.assertNotIn('DISPATCH_CARD_1', clicked)
        task.ui_goto_main.assert_called_once()
        task.config.task_delay.assert_called_once_with(minute=1201)

    def test_dispatch_report_modal_dismissed_in_ui_additional_and_claim(self):
        from module.resonance import assets

        report_popup = _blank_with(assets.DISPATCH_REPORT)
        task1 = _new_dispatch_task()
        task1.device.image = report_popup
        self.assertTrue(task1.ui_additional())
        clicked1 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task1.device.click.call_args_list]
        self.assertEqual(clicked1, ['DISPATCH_REPORT'])

        disp_running = _make_dispatch_screen(['active', 'other', 'idle', 'idle', 'idle'], selected_dur=None, recall=False)
        disp_card1_done = _make_dispatch_screen(['active', 'other', 'idle', 'idle', 'idle'], selected_dur=None, recall=False)
        disp_after_claim = _make_dispatch_screen(['active', 'idle', 'idle', 'idle', 'idle'], selected_dur='4h', recall=False)
        task2 = _new_dispatch_task()
        task2.device.image = disp_running
        frames = iter([disp_card1_done, report_popup, disp_after_claim])
        task2.device.screenshot.side_effect = lambda: setattr(task2.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 3.0)):
            status, mins = task2._inspect_and_claim_card(1)
        self.assertEqual((status, mins), ('claimed', None))
        clicked2 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task2.device.click.call_args_list]
        self.assertEqual(clicked2, ['DISPATCH_CARD_1', 'DISPATCH_CLAIM', 'DISPATCH_REPORT'])
