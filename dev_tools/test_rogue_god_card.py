"""God-flash card picker priority tests. Run: toolkit/python.exe -m unittest dev_tools.test_rogue_god_card."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from PIL import Image

from module.config.server import set_server

set_server('chaoszero')

from module.chaoszero.rogue import ChaoszeroRogue


def make_task(image=None, copy_card='劍之雨', god_filter=''):
    task = ChaoszeroRogue.__new__(ChaoszeroRogue)
    task.device = SimpleNamespace(
        image=image if image is not None else np.zeros((720, 1280, 3), dtype=np.uint8)
    )
    task.card_reader = None
    task.card_library = None
    task.config = SimpleNamespace(
        ChaoszeroRogue_RogueCopyCard=copy_card,
        ChaoszeroRogue_RogueGodSparkFilter=god_filter,
        data={'ChaoszeroRogue': {'ChaoszeroRogue': {'RogueGodSparkFilter': god_filter}}},
    )
    return task


class GodCardPriorityTest(unittest.TestCase):
    def test_real_god_card_title_prefers_unflashed_cards(self):
        img = np.array(Image.open('assets/chaoszero/chaoszero/ROGUE_GOD_CARD_TITLE.png').convert('RGB'))
        task = make_task(img)
        task.card_reader = SimpleNamespace(read_name=Mock(side_effect=['一縷光芒', '展開極光', '萬人的英雄']))
        points = task.rogue_flash_card_points(opening=11)
        self.assertEqual(len(points), 8)
        tiers = [task.rogue_card_flash_tier(img, t, l, w, h) for _, _, t, l, w, h in points]
        self.assertEqual(tiers, [0, 1, 0, 0, 1, 1, 1, 1])
        picked = task.rogue_god_card_pick(points)
        self.assertEqual(picked[:2], points[0][:2])

    def test_real_copy_title2_skips_god_flashed_card_and_picks_normal(self):
        img = np.array(Image.open('assets/chaoszero/chaoszero/ROGUE_COPY_TITLE2.png').convert('RGB'))
        task = make_task(img)
        task.card_reader = SimpleNamespace(read_name=Mock(return_value='高速連射'))
        points = task.rogue_flash_card_points(opening=11)
        self.assertEqual(len(points), 8)
        tiers = [task.rogue_card_flash_tier(img, t, l, w, h) for _, _, t, l, w, h in points]
        self.assertEqual(tiers, [1, 2, 1, 1, 1, 1, 1, 1])
        picked = task.rogue_god_card_pick(points)
        self.assertEqual(picked[:2], points[0][:2])

    def test_tier_beats_god_card_name_and_name_breaks_ties(self):
        points = [
            (450, 220, 82, 360, 188, 280),
            (660, 220, 82, 570, 188, 280),
            (870, 220, 82, 780, 188, 280),
        ]
        # Tier 0 (unflashed) beats tier 1 (normal flash) even when tier 1 is 劍之雨
        task = make_task()
        task.rogue_card_flash_tier = Mock(side_effect=[1, 0, 2])
        task.card_reader = SimpleNamespace(read_name=Mock(return_value='劍之雨'))
        self.assertEqual(task.rogue_god_card_pick(points)[:2], (660, 220))
        task.card_reader.read_name.assert_not_called()

        # Tier 1 (normal flash, no god flash) beats tier 2 (already god-flashed)
        task = make_task()
        task.rogue_card_flash_tier = Mock(side_effect=[2, 1, 2])
        self.assertEqual(task.rogue_god_card_pick(points)[:2], (660, 220))

        # Within the same best tier, prefer 劍之雨
        task = make_task()
        task.rogue_card_flash_tier = Mock(side_effect=[0, 1, 0])
        task.card_reader = SimpleNamespace(read_name=Mock(side_effect=['展開極光', '劍之雨']))
        self.assertEqual(task.rogue_god_card_pick(points)[:2], (870, 220))

    def test_copy_card_with_god_rule_tier1_beats_ordinary_tier0(self):
        points = [
            (450, 220, 82, 360, 188, 280),
            (660, 220, 82, 570, 188, 280),
            (870, 220, 82, 780, 188, 280),
        ]
        task = make_task(copy_card='劍之雨', god_filter='劍之雨 = 獲得AP1')
        task.rogue_card_flash_tier = Mock(side_effect=[0, 1, 0])
        task.card_reader = SimpleNamespace(read_name=Mock(side_effect=['展開極光', '劍之雨', '致命射擊']))
        picked = task.rogue_god_card_pick(points)
        self.assertEqual(picked[:2], (660, 220))
        self.assertEqual(picked[2], '劍之雨')

        # Non-copy target card at tier 1 does not beat tier 0 ordinary card
        task_non_copy = make_task(copy_card='劍之雨', god_filter='萬人的英雄 = 獲得AP1')
        task_non_copy.rogue_card_flash_tier = Mock(side_effect=[0, 1, 0])
        task_non_copy.card_reader = SimpleNamespace(read_name=Mock(side_effect=['展開極光', '萬人的英雄', '致命射擊']))
        self.assertEqual(task_non_copy.rogue_god_card_pick(points)[:2], (450, 220))

    def test_real_copy_title2_skips_satisfied_tier2_copy_card_and_falls_back_when_all_tier2(self):
        img = np.array(Image.open('assets/chaoszero/chaoszero/ROGUE_COPY_TITLE2.png').convert('RGB'))
        # card1 is tier=2 萬人的英雄 carrying "將棄牌堆中的2張消滅卡牌移動至手牌"
        task = make_task(
            img,
            copy_card='萬人的英雄',
            god_filter='萬人的英雄 = 將棄牌堆中的2張消滅卡牌移動至手牌',
        )
        points = task.rogue_flash_card_points(opening=11)
        picked = task.rogue_god_card_pick(points)
        self.assertNotEqual(picked[:2], points[1][:2])

        # When every card is tier=2: unsatisfied copy target beats ordinary tier=2 & satisfied tier=2
        mock_points = [
            (450, 220, 82, 360, 188, 280),
            (660, 220, 82, 570, 188, 280),
            (870, 220, 82, 780, 188, 280),
        ]
        task_all_t2 = make_task(copy_card='萬人的英雄', god_filter='萬人的英雄 = 獲得AP1\n展開極光 = 常態弱點攻擊')
        task_all_t2.rogue_card_flash_tier = Mock(return_value=2)
        task_all_t2.card_reader = SimpleNamespace(
            read_name=Mock(side_effect=['致命射擊', '展開極光', '萬人的英雄']),
            read_block=Mock(side_effect=['常態弱點攻擊', '士氣1、決心1']),
        )
        picked_all_t2 = task_all_t2.rogue_god_card_pick(mock_points)
        self.assertEqual(picked_all_t2[:2], (870, 220))
        self.assertEqual(picked_all_t2[2], '萬人的英雄')
