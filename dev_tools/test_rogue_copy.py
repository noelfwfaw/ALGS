"""Regression coverage for configurable roguelike card copying."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.config.config_generated import GeneratedConfig
from module.config.server import set_server

set_server('chaoszero')

from module.chaoszero import rogue
from module.chaoszero.rogue import ChaoszeroRogue


ASSETS_DIR = Path(__file__).resolve().parent.parent / 'assets' / 'chaoszero' / 'chaoszero'
FIXTURES_DIR = Path(__file__).resolve().parent / 'fixtures' / 'chaoszero'


class RogueCopyTest(unittest.TestCase):
    def test_copy_sword_rain_and_layouts_detected(self):
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.config = GeneratedConfig()
        task.card_reader = None

        img3 = cv2.cvtColor(
            cv2.imread(str(FIXTURES_DIR / 'rogue_copy_sword_rain.png')),
            cv2.COLOR_BGR2RGB,
        )
        task.device = SimpleNamespace(image=img3)
        pts3 = task.rogue_copy_card_points()
        self.assertEqual(len(pts3), 3)
        self.assertEqual([p[2] for p in pts3], [176, 496, 818])
        task.config.ChaoszeroRogue_RogueCopyCard = '劍之雨'
        picked = task.rogue_copy_card_pick()
        self.assertIsNotNone(picked)
        self.assertEqual((picked[0], picked[1], picked[2]), (961, 382, '劍之雨'))
        self.assertGreaterEqual(picked[3], 0.85)

        img2 = cv2.cvtColor(
            cv2.imread(str(ASSETS_DIR / 'ROGUE_COPY_CARD_TITLE.png')),
            cv2.COLOR_BGR2RGB,
        )
        task.device = SimpleNamespace(image=img2)
        pts2 = task.rogue_copy_card_points()
        self.assertEqual([p[2] for p in pts2], [336, 658])

        img8 = cv2.cvtColor(
            cv2.imread(str(ASSETS_DIR / 'ROGUE_COPY_TITLE2.png')),
            cv2.COLOR_BGR2RGB,
        )
        task.device = SimpleNamespace(image=img8)
        pts8 = task.rogue_copy_card_points()
        self.assertEqual(len(pts8), 8)
        task.config.ChaoszeroRogue_RogueCopyCard = '決心墜飾'
        picked8 = task.rogue_copy_card_pick()
        self.assertIsNotNone(picked8)
        self.assertEqual(picked8[2], '決心墜飾')
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

    def test_copy_confirm_transition_does_not_click_primary_over_copy_card_skip(self):
        boss_copy_img = cv2.cvtColor(
            cv2.imread(str(FIXTURES_DIR / 'rogue_copy_sword_rain_boss.png')),
            cv2.COLOR_BGR2RGB,
        )
        blank_img = np.zeros_like(boss_copy_img)

        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.config = GeneratedConfig()
        task.config.data = {}
        task.config.ChaoszeroRogue_RogueCopyCard = '劍之雨'
        task.config.ChaoszeroRogue_RogueGodSparkFilter = ''
        task.config.ChaoszeroRogue_RogueEquipFilter = ''
        task.card_library = None
        task.card_reader = None
        task.device = SimpleNamespace(
            image=boss_copy_img,
            stuck_record_clear=Mock(),
            click_record_clear=Mock(),
        )
        task.tap_point = Mock()
        task.appear = lambda btn, offset=(20, 20), similarity=0.85: btn.match(
            task.device.image, offset=offset, similarity=similarity,
        )
        self.assertTrue(task.rogue_copy_card_appear())
        self.assertIsNone(task.rogue_primary_point())
        picked = task.rogue_copy_card_pick()
        self.assertEqual(picked[:3], (319, 382, '劍之雨'))
        self.assertGreaterEqual(picked[3], 0.95)

        # Simulate: member confirm -> transition frame with fading orange primary -> copy card -> boss loot -> outside.
        steps = [
            {'img': blank_img, 'copy': True, 'member_selected': True, 'primary': (1134, 670), 'outside': False},
            {'img': blank_img, 'copy': False, 'member_selected': False, 'primary': (1133, 663), 'outside': False},
            {'img': boss_copy_img, 'copy': False, 'member_selected': False, 'primary': None, 'outside': False},
            {'img': blank_img, 'copy': False, 'member_selected': False, 'primary': (1135, 660), 'outside': False},
            {'img': blank_img, 'copy': False, 'member_selected': False, 'primary': None, 'outside': True},
        ]
        state = {'idx': 0}

        def fake_loop(**kwargs):
            for idx, entry in enumerate(steps):
                state['idx'] = idx
                task.device.image = entry['img']
                yield idx

        class InstantTimer:
            def __init__(self, limit, count=0):
                self.limit = limit
                self._expired = (limit == 12)  # copy_pending stays False until explicitly checked below
                self.calls = 0

            def start(self):
                self.calls = 0
                return self

            def reset(self):
                self.calls = 0
                return self

            def clear(self):
                self.calls = 0
                return self

            def reached(self):
                if self.limit == 12:
                    return False
                if self.limit == 1.2:
                    return True
                return False

            def reached_and_reset(self):
                return False

        task.loop = fake_loop
        task.rogue_state_load = Mock(return_value=False)
        task.rogue_stuck_check = Mock(return_value=False)
        task.rogue_click_stuck = Mock(return_value=False)
        task.rogue_card_page_record = Mock()
        task.rogue_outside_appear = lambda: steps[state['idx']]['outside']
        task.rogue_copy_appear = lambda: steps[state['idx']]['copy']
        task.rogue_member_selected = lambda: steps[state['idx']]['member_selected']
        task.rogue_primary_point = lambda: steps[state['idx']]['primary']
        for name in (
            'rogue_checkpoint_appear', 'rogue_dialog_point', 'rogue_battle_appear',
            'rogue_god_appear', 'rogue_flash_appear', 'handle_rogue_memory_choose',
            'handle_rogue_card_reward', 'rogue_loot_appear', 'rogue_memory_end_appear',
            'rogue_purple_point', 'rogue_flash_card_appear', 'rogue_transform_appear',
            'handle_rogue_fate', 'rogue_story_appear', 'rogue_herald_appear',
            'rogue_choice_appear', 'rogue_remove_appear', 'rogue_meditate_appear',
            'rogue_item_appear', 'rogue_season_popup_appear', 'rogue_modal_appear',
            'rogue_detail_appear', 'rogue_deck_appear', 'rogue_shop_appear',
            'rogue_shop_sold_appear', 'rogue_rest_appear', 'rogue_prompt_appear',
            'rogue_map_appear', 'rogue_beacon_stage', 'rogue_dice_appear',
            'rogue_dice_result_appear', 'handle_rogue_event', 'rogue_treasure_card_stage',
            'rogue_treasure_slot', 'rogue_secondary_point',
        ):
            setattr(task, name, Mock(return_value=False))
        task.rogue_treasure_card_stage = Mock(return_value=0)
        task.rogue_beacon_stage = Mock(return_value=0)

        with patch.object(rogue, 'Timer', InstantTimer), \
             patch('module.chaoszero.rogue_equipment.Equipment.handle', return_value=False):
            task.rogue_run()

        self.assertEqual(
            [(c[0], c[1]['name']) for c in task.tap_point.call_args_list],
            [
                (rogue.MEMBER_OK_POINT, 'ROGUE_COPY_OK'),
                ((319, 382), 'ROGUE_COPY_CARD'),
                ((1135, 660), 'ROGUE_PRIMARY'),
            ],
        )

    def test_duplicate_copy_cards_and_grid_confirm(self):
        # Multiple copies of the same target card (both score >= match) must pick
        # the target instead of rejecting as ambiguous and falling back to slot 1.
        copy_img = FIXTURES_DIR.parents[2] / 'log' / 'rogue_card_pages' / 'copy' / '181515.png'
        if not copy_img.exists():
            self.skipTest('181515.png not present')
        im = cv2.cvtColor(cv2.imread(str(copy_img)), cv2.COLOR_BGR2RGB)
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.config = GeneratedConfig()
        task.config.ChaoszeroRogue_RogueCopyCard = '劍之雨'
        task.card_reader = None
        task.device = SimpleNamespace(image=im)
        task.appear = lambda btn, offset=(20, 20), similarity=0.85: btn.match(
            task.device.image, offset=offset, similarity=similarity,
        )
        task.tap_point = Mock()
        task.rogue_card_page_record = Mock()
        task.copy_target = None
        task.copy_miss = 0
        task.copy_pending = None
        task.copy_grid_picked = False

        picked = task.rogue_copy_card_pick()
        self.assertIsNotNone(picked)
        self.assertEqual(picked[2], '劍之雨')
        self.assertGreater(picked[0], 550)

        press = SimpleNamespace(reached=Mock(return_value=True), reset=Mock())
        task.rogue_handle_copy_card_pick(press, 'Copy-card page', record=False)
        self.assertTrue(task.copy_grid_picked)
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_COPY_CARD')

        task.rogue_handle_copy_card_pick(press, 'Copy-card page', record=False)
        self.assertFalse(task.copy_grid_picked)
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_COPY_CONFIRM')


if __name__ == '__main__':
    unittest.main()
