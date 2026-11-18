"""Pending meditation regressions; no device connection is used."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from module.config.server import set_server

set_server('chaoszero')

from module.chaoszero.rogue import ChaoszeroRogue


def make_task():
    task = ChaoszeroRogue.__new__(ChaoszeroRogue)
    task.config = SimpleNamespace(ChaoszeroRogue_RogueMeditate=True)
    task.device = SimpleNamespace(image=None, swipe=Mock(), sleep=Mock(), screenshot=Mock())
    task.rogue_meditate_appear = Mock(return_value=True)
    task.wait_until_still = Mock(return_value=True)
    task.meditate_pending = []
    task.meditate_step = -1
    task.route_step = 1
    task.rogue_spark_filter = Mock(return_value={'劍之雨': ['2'], '展開極光': ['2']})
    task.card_reader = Mock()
    task.card_reader.read_all.return_value = ['first', 'second', 'third']
    task.card_library = Mock()
    task.card_library.identify.return_value = ('劍之雨', 0.95, 0.3)
    task.card_library.forms.return_value = (['a', 'b', 'c'], [])
    task.card_library.read_columns.return_value = [(0, 0.9, 0), (1, 0.9, 2), (2, 0.9, 3)]
    task.card_library.pick_column.return_value = None
    return task


class MeditationTest(unittest.TestCase):
    def test_multiple_missed_cards_stay_in_first_seen_order(self):
        task = make_task()
        task.rogue_flash_column()
        task.card_library.identify.return_value = ('展開極光', 0.95, 0.3)
        task.rogue_flash_column()
        self.assertEqual(task.meditate_pending, ['劍之雨', '展開極光'])

    def test_repeated_miss_does_not_duplicate_or_reorder_cards(self):
        task = make_task()
        task.rogue_flash_column()
        task.card_library.identify.return_value = ('展開極光', 0.95, 0.3)
        task.rogue_flash_column()
        task.card_library.identify.return_value = ('劍之雨', 0.95, 0.3)
        task.rogue_flash_column()
        self.assertEqual(task.meditate_pending, ['劍之雨', '展開極光'])

    def test_matching_one_card_removes_only_that_request(self):
        task = make_task()
        task.rogue_flash_column()
        task.card_library.identify.return_value = ('展開極光', 0.95, 0.3)
        task.rogue_flash_column()
        task.card_library.pick_column.return_value = (1, 0.9, 1, 'wanted')
        task.rogue_flash_column()
        self.assertEqual(task.meditate_pending, ['劍之雨'])

    def test_failed_reroll_keeps_head_and_other_requests_for_next_camp(self):
        task = make_task()
        task.meditate_pending = ['劍之雨', '展開極光']
        task.meditate_step = task.route_step
        task.rogue_flash_column()
        self.assertEqual(task.meditate_pending, ['劍之雨', '展開極光'])
        self.assertFalse(task.rogue_meditate_needed())
        task.route_step += 1
        self.assertTrue(task.rogue_meditate_needed())

    def test_grid_advances_to_next_card_only_after_head_matches(self):
        task = make_task()
        task.meditate_pending = ['劍之雨', '展開極光']
        task.rogue_flash_card_points = Mock(return_value=[
            (450, 220, 80, 360, 190, 280), (660, 220, 80, 570, 190, 280)])
        task.card_reader.read_name.side_effect = ['劍之雨', '展開極光']
        self.assertEqual(task.rogue_meditate_card()[1], '劍之雨')
        task.card_library.pick_column.return_value = (1, 0.9, 1, 'wanted')
        task.rogue_flash_column()
        task.card_reader.read_name.side_effect = ['劍之雨', '展開極光']
        self.assertEqual(task.rogue_meditate_card()[1], '展開極光')

    def test_four_target_cards_are_all_retained(self):
        task = make_task()
        names = ['劍之雨', '展開極光', '一縷光芒', '萬人的英雄']
        task.rogue_spark_filter.return_value = {name: ['2'] for name in names}
        for name in names:
            task.card_library.identify.return_value = (name, 0.95, 0.3)
            task.rogue_flash_column()
        self.assertEqual(task.meditate_pending, names)
        task.meditate_tries = 3
        self.assertTrue(task.rogue_meditate_needed())

    def test_uncertain_reroll_preserves_all_requests(self):
        task = make_task()
        task.meditate_pending = ['劍之雨', '展開極光']
        task.card_library.read_columns.return_value = [(0, 0.9, 0)]
        task.rogue_flash_column()
        self.assertEqual(task.meditate_pending, ['劍之雨', '展開極光'])

    def test_matching_all_pending_cards_ends_meditation_requests(self):
        task = make_task()
        task.meditate_pending = ['劍之雨', '展開極光']
        task.card_library.pick_column.return_value = (1, 0.9, 1, 'wanted')
        for name in list(task.meditate_pending):
            task.card_library.identify.return_value = (name, 0.95, 0.3)
            task.rogue_flash_column()
        self.assertEqual(task.meditate_pending, [])
        self.assertFalse(task.rogue_meditate_needed())

    def test_missing_wanted_form_marks_that_card(self):
        task = make_task()
        self.assertIsNone(task.rogue_flash_column())
        self.assertEqual(task.meditate_pending, ['劍之雨'])
        self.assertTrue(task.rogue_meditate_needed())

    def test_success_on_another_card_preserves_pending_target(self):
        task = make_task()
        task.rogue_flash_column()
        task.card_library.identify.return_value = ('展開極光', 0.95, 0.3)
        task.card_library.pick_column.return_value = (1, 0.9, 1, 'wanted')
        self.assertEqual(task.rogue_flash_column(), 2)
        self.assertEqual(task.meditate_pending, ['劍之雨'])
        self.assertTrue(task.rogue_meditate_needed())

    def test_success_on_pending_card_clears_request(self):
        task = make_task()
        task.rogue_flash_column()
        task.card_library.pick_column.return_value = (1, 0.9, 1, 'wanted')
        self.assertEqual(task.rogue_flash_column(), 2)
        self.assertEqual(task.meditate_pending, [])
        self.assertFalse(task.rogue_meditate_needed())

    def test_failed_attempt_waits_for_next_node_without_losing_target(self):
        task = make_task()
        task.rogue_flash_column()
        task.meditate_step = task.route_step
        self.assertFalse(task.rogue_meditate_needed())
        self.assertEqual(task.meditate_pending, ['劍之雨'])
        task.route_step += 1
        self.assertTrue(task.rogue_meditate_needed())

    def test_disabled_meditation_keeps_pending_target(self):
        task = make_task()
        task.rogue_flash_column()
        task.config.ChaoszeroRogue_RogueMeditate = False
        self.assertFalse(task.rogue_meditate_needed())
        self.assertEqual(task.meditate_pending, ['劍之雨'])

    def test_uncertain_read_does_not_request_meditation(self):
        task = make_task()
        task.card_library.read_columns.return_value = []
        task.rogue_flash_column()
        self.assertFalse(task.rogue_meditate_needed())

    def test_grid_without_pending_target_never_chooses_another_card(self):
        task = make_task()
        self.assertIsNone(task.rogue_meditate_card())
        task.card_reader.read_name.assert_not_called()

    def test_partially_read_columns_do_not_claim_wanted_form_is_missing(self):
        task = make_task()
        task.card_library.read_columns.return_value = [(0, 0.9, 0)]
        task.rogue_flash_column()
        self.assertFalse(task.rogue_meditate_needed())

    def test_target_below_first_screen_is_found_after_scroll(self):
        task = make_task()
        task.meditate_pending = ['劍之雨']
        task.rogue_flash_card_points = Mock(return_value=[(450, 220, 80, 360, 190, 280)])
        task.card_reader.read_name.side_effect = ['一縷光芒', '劍之雨']
        self.assertEqual(task.rogue_meditate_card(), ((450, 220), '劍之雨', 1.0))
        task.device.swipe.assert_called_once()

    def test_missing_target_has_bounded_scrolls(self):
        task = make_task()
        task.meditate_pending = ['劍之雨']
        task.rogue_flash_card_points = Mock(return_value=[])
        self.assertIsNone(task.rogue_meditate_card())
        self.assertEqual(task.device.swipe.call_count, 3)

    def test_scroll_stops_when_grid_disappears(self):
        task = make_task()
        task.meditate_pending = ['劍之雨']
        task.rogue_flash_card_points = Mock(return_value=[])
        task.rogue_meditate_appear.return_value = False
        self.assertIsNone(task.rogue_meditate_card())
        task.device.swipe.assert_called_once()

    def test_moving_grid_is_not_clicked(self):
        task = make_task()
        task.meditate_pending = ['劍之雨']
        task.rogue_flash_card_points = Mock(return_value=[])
        task.wait_until_still.return_value = False
        self.assertIsNone(task.rogue_meditate_card())
        task.device.swipe.assert_called_once()

    def test_ambiguous_duplicate_cards_are_not_guessed(self):
        task = make_task()
        task.meditate_pending = ['劍之雨']
        task.rogue_flash_card_points = Mock(return_value=[
            (450, 220, 80, 360, 190, 280), (660, 220, 80, 570, 190, 280)])
        task.card_reader.read_name.return_value = '劍之雨'
        self.assertIsNone(task.rogue_meditate_card())
        task.device.swipe.assert_not_called()

    def test_meditation_restricts_to_rogue_member_slot_character(self):
        task = make_task()
        task.rogue_spark_filter.return_value = {'劍之雨': ['2'], '水之根源': ['2']}
        node = {
            'RogueMember': 1,
            'RogueSlot1Member': '30093',
            'RogueSlot2Member': '1039',
            'RogueSlot3Member': '',
        }
        task.config = SimpleNamespace(
            ChaoszeroRogue_RogueMeditate=True,
            data={'ChaoszeroRogue': {'ChaoszeroRogue': node}},
        )
        task.card_library.identify.return_value = ('水之根源', 0.95, 0.3)
        task.rogue_flash_column()
        self.assertEqual(task.meditate_pending, [])
        self.assertFalse(task.rogue_meditate_needed())

        task.card_library.identify.return_value = ('劍之雨', 0.95, 0.3)
        task.rogue_flash_column()
        self.assertEqual(task.meditate_pending, ['劍之雨'])
        self.assertTrue(task.rogue_meditate_needed())

        node['RogueMember'] = 2
        self.assertFalse(task.rogue_meditate_needed())
        self.assertIsNone(task.rogue_meditate_card())


if __name__ == '__main__':
    unittest.main()
