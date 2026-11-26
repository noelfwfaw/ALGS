"""Offline regressions for Lost Sword battle carousel navigation."""

import unittest
from unittest.mock import Mock

import numpy as np

from module.config.server import set_server

set_server('lostsword')

from module.exception import GameStuckError
from module.lostsword.assets import (ARENA_CARD, BOSS_CARD, DUNGEON_CARD,
                                     MAZE_CARD, STAR_CARD)
from module.lostsword.boss import LostswordBoss
from module.lostsword.maze import LostswordMaze
from module.lostsword.page import page_battle, page_boss

CARDS = (BOSS_CARD, ARENA_CARD, DUNGEON_CARD, STAR_CARD, MAZE_CARD)


def make_carousel_frames():
    """Build synthetic start and end carousel frames in the updated 6-card layout."""
    for card in CARDS:
        card.ensure_template()

    start = np.zeros((720, 1280, 3), dtype=np.uint8)
    start[552:588, 134:249] = BOSS_CARD.image
    start[556:584, 832:897] = ARENA_CARD.image
    start[552:588, 1157:1251] = STAR_CARD.image

    end = np.zeros((720, 1280, 3), dtype=np.uint8)
    end[556:584, 47:112] = ARENA_CARD.image
    end[552:588, 371:465] = STAR_CARD.image
    end[557:588, 700:811] = DUNGEON_CARD.image
    end[553:588, 1049:1136] = MAZE_CARD.image
    return start, end


class LostswordBossTest(unittest.TestCase):
    def setUp(self):
        self.task = LostswordBoss.__new__(LostswordBoss)
        self.task.device = Mock()
        self.task.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        for card in CARDS:
            self.addCleanup(card.clear_offset)

    def prepare_battle_page(self):
        self.task.ui_get_current_page = Mock(return_value=page_battle)
        self.task.battle_goto_normal = Mock(return_value=True)
        self.task.ui_page_appear = lambda page: page == (
            page_boss if self.task.device.adb_shell.called else page_battle)
        self.task.loop = lambda **kwargs: iter(range(2))

    def test_taps_the_raid_card_at_its_shifted_position(self):
        self.prepare_battle_page()
        BOSS_CARD.ensure_template()
        self.task.device.image[552:588, 472:587] = BOSS_CARD.image

        self.task.boss_goto_page()

        self.task.device.adb_shell.assert_called_once_with(['input', 'tap', '529', '570'])
        self.assertEqual(self.task.ui_current, page_boss)

    def test_missing_card_times_out_without_a_tap(self):
        self.prepare_battle_page()
        self.task._battle_drag_once = Mock(return_value=False)

        with self.assertRaises(GameStuckError):
            self.task.boss_goto_page()

        self.task.device.adb_shell.assert_not_called()

    def test_scroll_stops_if_carousel_is_still_moving(self):
        self.task.wait_until_still = Mock(return_value=False)

        with self.assertRaises(GameStuckError):
            self.task.battle_scroll(forward=False)

        self.task.device.swipe_adb.assert_called_once_with((300, 400), (1000, 400), duration=0.625)
        self.task.wait_until_still.assert_called_once_with(
            (0, 140, 1280, 660), timeout=3, skip_first_screenshot=False)

    def test_locate_cards_across_updated_6card_carousel(self):
        start, end = make_carousel_frames()

        self.task.device.image = start.copy()
        self.task._battle_drag_once = Mock(return_value=False)
        self.assertEqual(self.task.battle_locate_card(BOSS_CARD), (191, 570))
        self.assertEqual(self.task.battle_locate_card(ARENA_CARD), (864, 570))
        self.task._battle_drag_once.assert_not_called()

        # Clipped STAR_CARD at start is skipped; dragging forward lands on unclipped slot.
        def drag_to_end(forward):
            if forward:
                self.task.device.image = end.copy()
                return True
            return False

        self.task.device.image = start.copy()
        self.task._battle_drag_once = Mock(side_effect=drag_to_end)
        self.assertEqual(self.task.battle_locate_card(STAR_CARD), (418, 570))
        self.task._battle_drag_once.assert_called_once_with(True)

        self.task.device.image = start.copy()
        self.task._battle_drag_once = Mock(side_effect=drag_to_end)
        self.assertEqual(self.task.battle_locate_card(DUNGEON_CARD), (755, 572))

        maze = LostswordMaze.__new__(LostswordMaze)
        maze.device = Mock()
        maze.device.image = start.copy()
        maze._battle_drag_once = Mock(side_effect=lambda f: (
            setattr(maze.device, 'image', end.copy()) or True) if f else False)
        maze.maze_on_map = Mock(side_effect=lambda: maze.device.adb_shell.called)
        maze.maze_finished = Mock(return_value=False)
        self.assertTrue(maze.maze_enter())
        maze.device.adb_shell.assert_called_once_with(['input', 'tap', '1092', '570'])

    def test_eaten_first_drag_still_locates_dungeon(self):
        start, end = make_carousel_frames()
        self.task.device.image = start.copy()
        drags = {'count': 0}

        def eaten_then_move(forward):
            drags['count'] += 1
            if drags['count'] == 1:
                return False
            self.task.device.image = end.copy()
            return True

        self.task._battle_drag_once = Mock(side_effect=eaten_then_move)
        self.assertEqual(self.task.battle_locate_card(DUNGEON_CARD), (755, 572))
        self.assertEqual(drags['count'], 2)

    def test_carousel_starting_at_end_scans_back_for_boss(self):
        start, end = make_carousel_frames()
        self.task.device.image = end.copy()

        def drag(forward):
            if forward:
                return False
            self.task.device.image = start.copy()
            return True

        self.task._battle_drag_once = Mock(side_effect=drag)
        self.assertEqual(self.task.battle_locate_card(BOSS_CARD), (191, 570))


if __name__ == '__main__':
    unittest.main()
