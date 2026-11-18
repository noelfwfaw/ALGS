# -*- coding: utf-8 -*-
"""Fate choice regressions using captured title and chooser-caption pixels."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.config.config_generated import GeneratedConfig
from module.config.server import set_server

set_server('chaoszero')

from module.chaoszero.rogue import FATE_OK_POINT, TAROT_POINTS, ChaoszeroRogue, rogue_fate


FIXTURES = Path(__file__).parent / 'fixtures' / 'chaoszero'


def make_task(screen, core_started=False, **settings):
    task = ChaoszeroRogue.__new__(ChaoszeroRogue)
    with Image.open(str(FIXTURES / ('rogue_fate_%s.png' % screen))) as image:
        task.device = SimpleNamespace(image=np.array(image.convert('RGB')), stuck_record_add=Mock())
    task.config = GeneratedConfig()
    task.config.data = {'ChaoszeroRogue': {'ChaoszeroRogue': settings}}
    task.core_started = core_started
    task.card_reader = Mock()
    task.card_reader.read_name.return_value = ''
    task.fate_tries = 0
    task.fate_index = None
    task.fate_wait = Mock()
    task.fate_wait.start.return_value = task.fate_wait
    task.fate_wait.current_time.return_value = 1
    task.tap_point = Mock()
    task.rogue_fate_record = Mock()
    return task


class FateTest(unittest.TestCase):
    def test_defaults_choose_recollection_before_maltreatment(self):
        task = make_task('main')
        self.assertTrue(task.handle_rogue_fate(Mock()))
        task.tap_point.assert_called_once_with(*TAROT_POINTS[1], name='ROGUE_CARD')
        task.rogue_fate_record.assert_not_called()

    def test_inspiration_and_sense_with_noisy_ocr_use_visible_glyphs(self):
        for screen, name in [('inspiration', '靈感'), ('sense', '感應')]:
            task = make_task(screen)
            self.assertEqual(rogue_fate.read_titles(task.device.image, task.card_reader)[2], name)
            task.handle_rogue_fate(Mock())
            task.tap_point.assert_called_once_with(*TAROT_POINTS[2], name='ROGUE_CARD')

    def test_core_pool_uses_its_own_priorities_even_with_stale_map_flag(self):
        task = make_task('core_mistagged', RogueFateCapture=True)
        task.handle_rogue_fate(Mock())
        task.tap_point.assert_called_once_with(*TAROT_POINTS[2], name='ROGUE_CARD')
        task.rogue_fate_record.assert_called_once_with(['熱情', '專注', '嫉妒'], 'core')
        self.assertFalse(task.core_started)

    def test_custom_order_accepts_simplified_titles_and_first_pool_hint(self):
        task = make_task('core', RogueFateCoreFilter='拥有\n共情')
        task.handle_rogue_fate(Mock())
        task.tap_point.assert_called_once_with(*TAROT_POINTS[1], name='ROGUE_CARD')
        self.assertEqual(rogue_fate.phase(['回想', '', '感應'], True), 'main')

    def test_arrow_priority_syntax_for_fate_filters(self):
        self.assertEqual(rogue_fate.pick(['熱情', '共情', '擁有'], '拥有 > 共情'), (3, True))
        self.assertEqual(rogue_fate.pick(['熱情', '專注', '嫉妒'], '開朗 > 共情 > 擁有 ＞ 嫉妒'), (3, True))

    def test_no_priority_match_rolls_once_then_confirms_and_retries_same_card(self):
        task = make_task('random')
        press = Mock()
        with patch.object(rogue_fate, 'choice', return_value=3) as roll:
            task.handle_rogue_fate(press)
            task.handle_rogue_fate(press)
            task.tap_point.assert_called_with(*FATE_OK_POINT, name='ROGUE_FATE_OK')
            task.handle_rogue_fate(press)
        roll.assert_called_once_with(range(1, 4))
        task.tap_point.assert_called_with(*TAROT_POINTS[2], name='ROGUE_CARD')
        task.device.image[649:] = 0
        self.assertFalse(task.handle_rogue_fate(press))
        self.assertIsNone(task.fate_index)

    def test_unrevealed_card_waits_without_clicking_or_collecting(self):
        task = make_task('main', RogueFateCapture=True)
        x1, y1, x2, y2 = rogue_fate.TITLE_AREAS[-1]
        task.device.image[y1:y2, x1:x2] = 255
        self.assertTrue(task.handle_rogue_fate(Mock()))
        task.tap_point.assert_not_called()
        task.rogue_fate_record.assert_not_called()


if __name__ == '__main__':
    unittest.main()
