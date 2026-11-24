"""Pending meditation regressions; no device connection is used."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2

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
        task.card_reader.read_name.side_effect = ['劍之雨', '展開極光', '展開極光']
        self.assertEqual(task.rogue_meditate_card()[1], '劍之雨')
        task.card_library.pick_column.return_value = (1, 0.9, 1, 'wanted')
        task.rogue_flash_column()
        task.card_reader.read_name.side_effect = ['劍之雨', '劍之雨', '展開極光']
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
        task.card_reader.read_name.side_effect = ['一縷光芒', '一縷光芒', '劍之雨']
        self.assertEqual(task.rogue_meditate_card(), ((450, 220), '劍之雨', 1.0))
        task.device.swipe.assert_called_once()

    def test_real_beam_card_detected_without_false_scroll_cancel(self):
        fixture = Path(__file__).resolve().parent / 'fixtures' / 'chaoszero' / 'rogue_meditate_beam.png'
        im = cv2.cvtColor(cv2.imread(str(fixture)), cv2.COLOR_BGR2RGB)
        task = make_task()
        task.device = SimpleNamespace(image=im, swipe=Mock(), sleep=Mock(), screenshot=Mock())
        task.card_reader = None
        task.rogue_spark_filter.return_value = {'一縷光芒': ['2']}
        task.meditate_pending = ['一縷光芒']
        points = task._flash_points_merged()
        self.assertEqual(len(points), 5)
        picked = task.rogue_meditate_card()
        self.assertIsNotNone(picked)
        self.assertEqual(picked[1], '一縷光芒')
        self.assertGreaterEqual(picked[2], 0.90)
        task.device.swipe.assert_not_called()

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

    def test_grid_reads_name_band_above_card_frame_at_2x(self):
        task = make_task()
        task.meditate_pending = ['劍之雨']
        task.rogue_flash_card_points = Mock(return_value=[(450, 220, 80, 360, 190, 280)])
        task.card_reader.read_name.return_value = '劍之雨'
        self.assertEqual(task.rogue_meditate_card()[1], '劍之雨')
        task.card_reader.read_name.assert_called_once_with(
            task.device.image, (370, 86, 540, 114), scale=2)

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

    def test_free_covenant_skip_and_fallback_selection(self):
        # On Stage 2 Covenant free re-spark (174549.png): god-sparked 劍之雨 &
        # already-matched 萬人的英雄 (rsp1) are protected, un-sparked 一縷光芒 is
        # not forced -> returns None; if 萬人的英雄 missed its rule, picks it.
        p49 = Path('log/rogue_card_pages/meditate/174549.png')
        if p49.exists():
            im = cv2.cvtColor(cv2.imread(str(p49)), cv2.COLOR_BGR2RGB)
            task = make_task()
            task.device = SimpleNamespace(image=im, swipe=Mock(), sleep=Mock(), screenshot=Mock())
            task.card_reader = None
            task.card_library = None
            task.rogue_spark_filter.return_value = {'劍之雨': ['2'], '萬人的英雄': ['1']}
            self.assertTrue(task._meditate_is_free_skip())
            self.assertIsNone(task.rogue_meditate_card())

            # When 萬人的英雄 expects a DIFFERENT form (e.g. '3'), it picks it!
            task.rogue_spark_filter.return_value = {'劍之雨': ['2'], '萬人的英雄': ['3']}
            picked = task.rogue_meditate_card()
            self.assertIsNotNone(picked)
            self.assertEqual(picked[1], '萬人的英雄')

        p52 = Path('log/rogue_card_pages/meditate/174552.png')
        if p52.exists():
            im52 = cv2.cvtColor(cv2.imread(str(p52)), cv2.COLOR_BGR2RGB)
            task52 = make_task()
            task52.device = SimpleNamespace(image=im52, swipe=Mock(), sleep=Mock(), screenshot=Mock())
            self.assertIsNotNone(ChaoszeroRogue.rogue_dialog_point(task52))

    def test_unaffordable_credits_skip_meditation_without_false_fade_positive(self):
        import numpy as np
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        im = np.zeros((720, 1280, 3), dtype=np.uint8)
        task.device = SimpleNamespace(image=im)
        task.core_started = False
        task.route_step = 5
        task.rogue_rest_appear = Mock(return_value=True)
        task.rogue_confirm_point = Mock(return_value=None)
        task.rogue_count = Mock(return_value=200)
        task.appear = Mock(return_value=False)

        # Even if sunset / fade-in puts orange-red pixels behind the price area, sufficient credits stay allowed.
        im[440:458, 1025:1090] = (200, 90, 90)
        task.credits = 205
        self.assertTrue(task.rogue_meditate_available())

        task.credits = 75
        self.assertFalse(task.rogue_meditate_available())

        task.credits = 80
        self.assertTrue(task.rogue_meditate_available())

    def test_partial_read_still_queues_when_clicked_column_is_known_wrong(self):
        task = make_task()
        task.spark_pending = None
        task.spark_selected = None
        # col1=rsp3, col2=unmatched, col3=rsp4; want=rsp1 -> rogue_choose_flash picks col1 -> queued!
        task.card_library.read_columns.return_value = [(0, 0.77, 2), (2, 0.92, 3)]
        task.rogue_pick = Mock(return_value=True)
        task.rogue_pick_index = Mock(return_value=1)
        task.rogue_god_pick = Mock(return_value=1)
        task.rogue_choose_flash(god=True)
        self.assertEqual(task.meditate_pending, ['劍之雨'])

        # Clicking the unread col2 instead does NOT blindly queue without confirming its form.
        task2 = make_task()
        task2.spark_pending = None
        task2.spark_selected = None
        task2.card_library.read_columns.return_value = [(0, 0.77, 2), (2, 0.92, 3)]
        task2.rogue_pick = Mock(return_value=True)
        task2.rogue_pick_index = Mock(return_value=2)
        task2.flash_god_column = None
        task2.rogue_god_pick = Mock(return_value=None)
        task2.rogue_choose_flash(god=True)
        self.assertEqual(task2.meditate_pending, [])

    def test_shop_leave_has_cooldown_to_prevent_double_click_skipping_camp(self):
        from types import SimpleNamespace
        from module.base.timer import Timer
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.tap_point = Mock()
        task.equipment = SimpleNamespace(shop_refresh=(1, Timer(30)), shop_refresh_confirmed=True)
        press = Timer(0)
        task._rogue_leave_shop(press, 'leave 1')
        task.tap_point.assert_called_once_with(1136, 678, name='ROGUE_SHOP_LEAVE')
        self.assertIsNone(task.equipment.shop_refresh)
        self.assertFalse(task.equipment.shop_refresh_confirmed)
        # Subsequent call within 3.5s is suppressed even if press timer is ready.
        press.reset()
        press = Timer(0)
        task._rogue_leave_shop(press, 'leave 2')
        task.tap_point.assert_called_once()


if __name__ == '__main__':
    unittest.main()
