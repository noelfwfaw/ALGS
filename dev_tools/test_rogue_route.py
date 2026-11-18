import unittest
from pathlib import Path
from unittest.mock import Mock

import cv2

from module.config.server import set_server

set_server('chaoszero')
from module.chaoszero import rogue_route as route
from module.chaoszero.rogue import ChaoszeroRogue


FIXTURES = Path(__file__).parent / 'fixtures' / 'chaoszero'


def capture(name):
    return cv2.cvtColor(cv2.imread(str(FIXTURES / name)), cv2.COLOR_BGR2RGB)


class TestRoute(unittest.TestCase):
    def test_grey_start_keeps_first_column_and_selects_top_branch(self):
        image = capture('rogue_route_opening.png')
        nodes = route.read_nodes(image)
        self.assertEqual(route.LAST_PIN_X, 178)
        first = [node for node in nodes if node.tier == 0]
        self.assertEqual([(node.x, node.kind) for node in first], [(341, 'battle')] * 3)
        plan = route.plan(nodes, edges=route.read_edges(image, nodes))
        self.assertEqual([entry[0]['kind'] for entry in plan],
                         ['battle', 'event', 'rest', 'battle', 'event', 'battle'])
        cards = route.read_cards(capture('rogue_route_platforms.png'))
        self.assertIs(route.planned_card(cards, plan[0][0]), min(cards, key=lambda card: card.y))
        self.assertIsNone(route.planned_card(cards[:2], plan[0][0]))
        self.assertEqual(plan[1][0]['choices'], ['event', 'event'])

    def test_missing_pin_does_not_guess_first_column(self):
        image = capture('rogue_route_opening.png')
        image[310:355, 155:201] = 0
        self.assertEqual(route.read_nodes(image), [])
        self.assertIsNone(route.LAST_PIN_X)

    def test_neighboring_horizontal_line_is_not_a_diagonal_edge(self):
        image = capture('rogue_route_opening.png')
        nodes = route.read_nodes(image)
        edges = set(route.read_edges(image, nodes))
        middle_event = min(range(len(nodes)), key=lambda i: abs(nodes[i].x - 505) + abs(nodes[i].y - 258))
        lower_event = min(range(len(nodes)), key=lambda i: abs(nodes[i].x - 505) + abs(nodes[i].y - 366))
        rest = min(range(len(nodes)), key=lambda i: abs(nodes[i].x - 669) + abs(nodes[i].y - 258))
        self.assertIn((middle_event, rest), edges)
        self.assertNotIn((lower_event, rest), edges)

    def test_glow_does_not_hide_the_event_diamond_or_elite_platform(self):
        image = capture('rogue_route_glowing_preview.png')
        nodes = route.read_nodes(image)
        entry = route.plan(nodes, state={'avoid_elite': True},
                           edges=route.read_edges(image, nodes))[0][0]
        self.assertEqual(entry['choices'], ['event', 'elite', 'event'])
        cards = route.read_cards(capture('rogue_route_glowing_platforms.png'))
        self.assertEqual([card.kind for card in sorted(cards, key=lambda card: card.y)],
                         entry['choices'])
        self.assertIs(route.planned_card(cards, entry), max(cards, key=lambda card: card.y))

    def test_only_confirmed_entry_advances_counters_once(self):
        task = Mock(spec=ChaoszeroRogue)
        task.node_pending = object()
        task.route_step, task.plan_index = 7, 2
        task.event_visit = {'old': 1}
        for name in (
                'rogue_map_appear', 'rogue_map_preview_appear', 'rogue_battle_appear',
                'rogue_prompt_appear', 'rogue_rest_appear', 'rogue_story_appear',
                'rogue_choice_appear', 'rogue_beacon_stage', 'rogue_treasure_card_appear',
                'rogue_dice_appear', 'rogue_dice_result_appear', 'rogue_card_reward_appear',
                'rogue_flash_appear', 'rogue_god_appear', 'rogue_option_points',
                'rogue_primary_point'):
            getattr(task, name).return_value = False
        confirm = lambda: ChaoszeroRogue.rogue_route_confirm_move(task)
        task.rogue_battle_appear.return_value = True
        task.rogue_map_appear.return_value = True
        self.assertFalse(confirm())
        self.assertFalse(confirm())
        task.rogue_map_appear.return_value = False
        task.rogue_map_preview_appear.return_value = True
        self.assertFalse(confirm())
        task.rogue_map_preview_appear.return_value = False
        task.rogue_battle_appear.return_value = False
        self.assertFalse(confirm())
        task.rogue_prompt_appear.return_value = True
        task.rogue_primary_point.return_value = True
        self.assertFalse(confirm())
        task.rogue_prompt_appear.return_value = False
        task.rogue_primary_point.return_value = False
        self.assertEqual((task.route_step, task.plan_index), (7, 2))
        self.assertEqual(task.event_visit, {'old': 1})
        task.rogue_rest_appear.return_value = True
        self.assertTrue(confirm())
        self.assertFalse(confirm())
        self.assertEqual((task.route_step, task.plan_index), (8, 3))
        self.assertEqual(task.event_visit, {})


if __name__ == '__main__':
    unittest.main()
