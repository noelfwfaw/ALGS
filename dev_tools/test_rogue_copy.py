"""Regression coverage for configurable roguelike card copying."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from module.config.config_generated import GeneratedConfig
from module.config.server import set_server

set_server('chaoszero')

from module.chaoszero.rogue import ChaoszeroRogue


ASSETS_DIR = Path(__file__).resolve().parent.parent / 'assets' / 'chaoszero' / 'chaoszero'


class RogueCopyTest(unittest.TestCase):
    def test_copy_header_does_not_match_transform_or_remove_pages(self):
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        for name, expected_copy, expected_transform in (
            ('ROGUE_COPY_CARD_TITLE.png', True, False),
            ('ROGUE_COPY_TITLE2.png', True, False),
            ('ROGUE_TRANSFORM.png', False, True),
            ('ROGUE_REMOVE.png', False, False),
        ):
            with self.subTest(name=name):
                img = cv2.imread(str(ASSETS_DIR / name))
                task.device = SimpleNamespace(
                    image=cv2.cvtColor(img, cv2.COLOR_BGR2RGB),
                    stuck_record_add=Mock(),
                )
                self.assertEqual(task.rogue_copy_card_appear(), expected_copy)
                self.assertEqual(task.rogue_transform_appear(), expected_transform)
    def test_target_config_selects_the_matching_card(self):
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.config = GeneratedConfig()
        task.device = SimpleNamespace(image=None)
        task.rogue_copy_card_points = Mock(return_value=[
            (470, 380, 350, 170, 240, 420),
            (790, 380, 670, 170, 240, 420),
        ])
        task.card_reader = Mock()

        def pick(name1, name2):
            task.card_reader.read_name.side_effect = [name1, name2]
            return task.rogue_copy_card_pick()

        self.assertEqual(pick('劍之雨', '喘氣'), (470, 380, '劍之雨', 1.0))
        task.config.ChaoszeroRogue_RogueCopyCard = ' 喘氣 '
        self.assertEqual(pick('劍之雨', '喘氣'), (790, 380, '喘氣', 1.0))
        self.assertIsNone(pick('劍之雨', '探險'))

    def test_copy_source_can_override_the_flash_slot(self):
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.config = GeneratedConfig()
        task.config.ChaoszeroRogue_RogueMember = 2
        task.image_crop = Mock(return_value=np.array([0, 255]))
        self.assertEqual(task.rogue_member_index(), 2)
        self.assertEqual(task.rogue_member_index(3), 3)
        task.image_crop.side_effect = [np.array([0, 255]), np.array([0, 255]), np.zeros(2)]
        self.assertEqual(task.rogue_member_index(3), 1)

        # Copy page: strict configured slot, never overridden by the contrast heuristic
        task.image_crop.side_effect = [np.array([0, 255]), np.array([0, 255]), np.zeros(2)]
        self.assertEqual(task.rogue_member_index(3, dim_check=False), 3)

if __name__ == '__main__':
    unittest.main()
