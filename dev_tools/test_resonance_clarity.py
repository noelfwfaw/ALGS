import os
import unittest
from itertools import count
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.base.utils import load_image
from module.config import server


def _paste_button(canvas, button):
    x1, y1, x2, y2 = button.area
    canvas[y1:y2, x1:x2] = load_image(button.file, button.area)


def _blank_with(*buttons):
    canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
    for btn in buttons:
        _paste_button(canvas, btn)
    return canvas


def make_clarity_recovery_screen(has_lollipop=True, has_gum=True, has_cactus=False):
    from module.resonance import assets
    from module.resonance.clarity import CLARITY_ITEMS

    frame = _blank_with(assets.CLARITY_RECOVERY_CHECK, assets.OP_BACK)
    flags = {'lollipop': has_lollipop, 'gum': has_gum, 'cactus': has_cactus}
    for key, _, (x1, _, _, _) in CLARITY_ITEMS:
        if flags[key]:
            frame[624:648, x1 + 8:x1 + 42] = (230, 185, 30)
        else:
            frame[565:598, x1 + 75:x1 + 210] = 240
    return frame


def make_clarity_confirm_modal():
    from module.resonance import assets

    return _blank_with(
        assets.CLARITY_CONFIRM_MODAL,
        assets.FATIGUE_CONFIRM_OK,
        assets.FATIGUE_CONFIRM_CANCEL,
        assets.FATIGUE_CONFIRM_PLUS,
        assets.FATIGUE_CONFIRM_MINUS,
        assets.FATIGUE_CONFIRM_MAX,
    )


def _new_ui():
    from module.resonance.resonance_ui import ResonanceUI

    ui = ResonanceUI.__new__(ResonanceUI)
    ui.device = Mock()
    ui.config = SimpleNamespace()
    ui.interval_timer = {}
    return ui


class TestResonanceClarity(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def test_clarity_assets_and_ocr_on_real_screenshots(self):
        from module.resonance import assets
        from module.resonance.clarity import CLARITY_ITEMS, parse_clarity_items, read_clarity_fraction
        from module.resonance.fatigue import FATIGUE_CONFIRM_QTY_OCR

        base = 'C:/Users/14494/Documents/MuMu共享文件夹/Screenshots/'
        files = {
            'prompt': base + 'MuMu-20261126-142401-794.png',
            'page': base + 'MuMu-20261126-142417-540.png',
            'confirm': base + 'MuMu-20261126-142750-243.png',
        }
        if not all(os.path.exists(p) for p in files.values()):
            return

        imgs = {k: np.array(Image.open(p).convert('RGB')) for k, p in files.items()}
        expected = [
            (assets.CLARITY_PROMPT, {'prompt'}),
            (assets.CLARITY_PROMPT_CANCEL, {'prompt'}),
            (assets.CLARITY_PROMPT_CONFIRM, {'prompt'}),
            (assets.CLARITY_RECOVERY_CHECK, {'page'}),
            (assets.CLARITY_CONFIRM_MODAL, {'confirm'}),
            (assets.FATIGUE_CONFIRM_OK, {'confirm'}),
            (assets.FATIGUE_CONFIRM_CANCEL, {'confirm'}),
        ]
        for btn, owners in expected:
            for key, img in imgs.items():
                self.assertEqual(btn.match(img, offset=(5, 5)), key in owners, f'{btn.name} on {key}')

        self.assertEqual(read_clarity_fraction(imgs['page']), (17, 358))
        items = parse_clarity_items(imgs['page'])
        self.assertEqual([i['key'] for i in items], [k for k, _, _ in CLARITY_ITEMS])
        self.assertEqual({i['key']: i['owned'] for i in items}, {'lollipop': 24, 'gum': 40, 'cactus': 0})
        self.assertEqual(FATIGUE_CONFIRM_QTY_OCR.ocr(imgs['confirm']), '1/10')

    def test_normalize_and_choose_plan_respects_tiers_and_excludes_birch(self):
        from module.resonance.clarity import CLARITY_ITEM_TIERS, choose_clarity_item_plan, normalize_clarity_item_mode

        self.assertEqual(normalize_clarity_item_mode('none'), 'none')
        self.assertEqual(normalize_clarity_item_mode('LOLLIPOP_GUM'), 'lollipop_gum')
        self.assertEqual(normalize_clarity_item_mode(True), 'all')
        self.assertEqual(normalize_clarity_item_mode(False), 'none')
        self.assertEqual(normalize_clarity_item_mode('unknown'), 'none')

        items = [
            {'key': 'lollipop', 'recover': 40, 'owned': 24},
            {'key': 'gum', 'recover': 60, 'owned': 40},
            {'key': 'cactus', 'recover': 180, 'owned': 2},
        ]
        self.assertIsNone(choose_clarity_item_plan(40, items, CLARITY_ITEM_TIERS['none']))
        self.assertEqual(choose_clarity_item_plan(40, items, CLARITY_ITEM_TIERS['lollipop']), ('lollipop', 1))
        self.assertEqual(choose_clarity_item_plan(90, items, CLARITY_ITEM_TIERS['lollipop']), ('lollipop', 3))

        no_lolli = [{'key': 'lollipop', 'recover': 40, 'owned': 0}, {'key': 'gum', 'recover': 60, 'owned': 5}]
        self.assertIsNone(choose_clarity_item_plan(40, no_lolli, CLARITY_ITEM_TIERS['lollipop']))
        self.assertEqual(choose_clarity_item_plan(40, no_lolli, CLARITY_ITEM_TIERS['lollipop_gum']), ('gum', 1))

    def test_handle_clarity_recovery_flows(self):
        from module.resonance import assets
        from module.resonance.clarity import handle_clarity_recovery

        detail = np.zeros((720, 1280, 3), dtype=np.uint8)
        prompt = _blank_with(assets.CLARITY_PROMPT, assets.CLARITY_PROMPT_CANCEL, assets.CLARITY_PROMPT_CONFIRM)
        page_full = make_clarity_recovery_screen(has_lollipop=True, has_gum=True, has_cactus=False)
        page_gum_only = make_clarity_recovery_screen(has_lollipop=False, has_gum=True, has_cactus=False)
        confirm = make_clarity_confirm_modal()

        # 1) mode='none': cancels prompt cleanly
        ui1 = _new_ui()
        ui1.device.image = prompt
        frames1 = iter([detail])
        ui1.device.screenshot.side_effect = lambda: setattr(ui1.device, 'image', next(frames1))
        with patch('module.base.timer.time', side_effect=count(100, 2.0)):
            self.assertFalse(handle_clarity_recovery(ui1, 'none'))
        clicked1 = [getattr(c[0][0], 'name', str(c[0][0])) for c in ui1.device.click.call_args_list]
        self.assertEqual(clicked1, ['CLARITY_PROMPT_CANCEL'])

        # 2) mode='lollipop': confirms prompt -> uses lollipop -> confirms -> backs out
        ui2 = _new_ui()
        ui2.device.image = prompt
        frames2 = iter([page_full, confirm, page_full, detail])
        ui2.device.screenshot.side_effect = lambda: setattr(ui2.device, 'image', next(frames2))
        with patch('module.resonance.clarity.read_clarity_fraction', return_value=(17, 358)), \
             patch('module.resonance.clarity.CLARITY_CNT_OCR.ocr', side_effect=[['24'], ['40']]), \
             patch('module.resonance.clarity.FATIGUE_CONFIRM_QTY_OCR.ocr', return_value='1/10'), \
             patch('module.base.timer.time', side_effect=count(100, 2.0)):
            self.assertTrue(handle_clarity_recovery(ui2, 'lollipop'))
        clicked2 = [getattr(c[0][0], 'name', str(c[0][0])) for c in ui2.device.click.call_args_list]
        self.assertEqual(
            clicked2,
            ['CLARITY_PROMPT_CONFIRM', 'CLARITY_ITEM_LOLLIPOP', 'FATIGUE_CONFIRM_OK', 'OP_BACK'],
        )

        # 3) mode='lollipop' when lollipop empty (gum owned): backs out without spending gum or birch
        ui3 = _new_ui()
        ui3.device.image = prompt
        frames3 = iter([page_gum_only, detail])
        ui3.device.screenshot.side_effect = lambda: setattr(ui3.device, 'image', next(frames3))
        with patch('module.resonance.clarity.read_clarity_fraction', return_value=(17, 358)), \
             patch('module.resonance.clarity.CLARITY_CNT_OCR.ocr', return_value=['40']), \
             patch('module.base.timer.time', side_effect=count(100, 2.0)):
            self.assertFalse(handle_clarity_recovery(ui3, 'lollipop'))
        clicked3 = [getattr(c[0][0], 'name', str(c[0][0])) for c in ui3.device.click.call_args_list]
        self.assertEqual(clicked3, ['CLARITY_PROMPT_CONFIRM', 'OP_BACK'])
