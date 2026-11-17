"""Event selection and sequence regressions; no device connection is used."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from module.config.server import set_server

set_server('chaoszero')

from module.base.timer import Timer
from module.chaoszero.rogue import ChaoszeroRogue
from module.chaoszero.rogue_events import EventLibrary, packs_for_world
from module.exception import TaskFailed


def record(name, options):
    return {'name': name, 'pack': 'uk_904_s01',
            'options': [{'order': order, 'flavor': title} for order, title in options]}


def make_task():
    task = ChaoszeroRogue.__new__(ChaoszeroRogue)
    task.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
    task.config = SimpleNamespace(ChaoszeroRogue_RogueEventPick=True,
                                  ChaoszeroRogue_RogueWorld='霧之城市')
    task.event_library = EventLibrary.__new__(EventLibrary)
    task.event_library.records = {
        'void': record('虛無牧者', [(1, '將手伸入深處'), (2, '將手伸入更深處'),
                                  (3, '將手伸入最深處'), (4, '取出能夠抓住的東西'),
                                  (7, '取出能夠抓住的東西'), (8, '迎接虛無')]),
        'cave': record('猝死洞窟', [(1, '取出左側箱子'), (2, '救出倖存者'),
                                  (3, '取出右側箱子'), (4, '離開洞窟')]),
    }
    task.event_picks = {'void': [1, 2, 3, 7], 'cave': [1]}
    task.card_reader = SimpleNamespace(read_name=Mock())
    task.event_visit = {}
    task.event_last_enc = None
    task.event_choice = None
    task.event_pending_choice = None
    task.event_submit_wait = None
    task.event_unknown = False
    task.event_page = None
    task.event_index = None
    task.option_pending = None
    task.rogue_event_record = Mock()
    task.rogue_dump_unknown = Mock()
    task.tap_point = Mock()
    task.rogue_pick_index = Mock(return_value=1)
    task.rogue_option_points = Mock()
    task.rogue_option_check_point = Mock(return_value=None)
    task.rogue_option_check_any = Mock(return_value=None)
    return task


def expire(timer):
    timer._start = 1
    timer._access = timer.count + 1


class EventSelectionTest(unittest.TestCase):
    def setUp(self):
        self.task = make_task()

    def feed(self, texts):
        self.task.card_reader.read_name = Mock(side_effect=texts)
        self.task.rogue_option_points.return_value = [(308 + index * 332, 677)
                                                     for index in range(len(texts))]

    def step(self):
        return self.task.handle_rogue_event(Timer(0))

    def confirm(self):
        x, _ = self.task.option_pending
        self.task.rogue_option_check_point.return_value = (x, 681)
        self.assertTrue(self.step())
        self.task.rogue_option_check_point.return_value = None
        expire(self.task.event_submit_wait)

    def test_sequence_reidentifies_after_each_commit_even_with_identical_positions(self):
        pages = [(['取出能夠抓住的東西', '將手伸入深處', '迎接虛無'], 2),
                 (['將手伸入更深處', '迎接虛無', '取出能夠抓住的東西'], 1),
                 (['取出能夠抓住的東西', '迎接虛無', '將手伸入最深處'], 3),
                 (['迎接虛無', '取出能夠抓住的東西'], 2)]
        for round_index, (texts, expected) in enumerate(pages):
            with self.subTest(round=round_index + 1):
                self.feed(texts)
                self.assertTrue(self.step())
                self.task.tap_point.assert_called_with(308 + (expected - 1) * 332, 590,
                                                       name='ROGUE_OPTION')
                self.assertEqual(self.task.event_visit.get('void', 0), round_index)
                self.assertEqual(self.task.event_pending_choice['order'], [1, 2, 3, 7][round_index])
                self.confirm()
                self.assertEqual(self.task.event_visit['void'], round_index + 1)
                self.assertIsNone(self.task.event_page)
                self.assertIsNone(self.task.event_index)

    def test_unavailable_configured_target_has_no_pending_identity(self):
        result = self.task.rogue_event_manual_index(['救出偉存者', '離開洞窟'],
                                                   packs_for_world('霧之城市'))
        self.assertIsNone(result)
        self.assertIsNone(self.task.event_last_enc)
        self.assertIsNone(self.task.event_choice)

    def test_new_branch_without_configured_target_stops_without_old_or_fallback_click(self):
        self.task.event_index = 2
        self.task.event_page = ((100, 677), (200, 677), (300, 677))
        self.feed(['救出倖存者', '離開洞窟'])
        with self.assertRaises(TaskFailed):
            self.step()
        self.task.tap_point.assert_not_called()
        self.task.rogue_pick_index.assert_not_called()
        self.task.rogue_dump_unknown.assert_called_once()
        self.assertIsNone(self.task.event_pending_choice)
        self.assertEqual(self.task.event_visit, {})

    def test_missing_random_option_still_stops_with_classified_source(self):
        import json
        from pathlib import Path
        from dev_tools.gen_chaoszero_rogue_db import parse_encounter

        raw = json.loads((Path(__file__).parent / 'fixtures' / 'chaoszero' /
                          'rogue_residue.json').read_text(encoding='utf-8'))
        self.task.event_library.records = {raw['id']: parse_encounter(raw)}
        self.task.event_picks = {raw['id']: [1]}
        self.feed(['檢查痛游', '承諾會擊殺怪物', '安慰'])
        with self.assertRaises(TaskFailed):
            self.step()
        self.task.tap_point.assert_not_called()
        self.task.rogue_pick_index.assert_not_called()
        self.task.rogue_dump_unknown.assert_called_once()

    def test_similar_stage_title_does_not_impersonate_requested_stage(self):
        self.task.event_visit['void'] = 1
        self.assertIsNone(self.task.rogue_event_manual_index(
            ['將手伸入最深處', '取出能夠抓住的東西', '迎接虛無'],
            packs_for_world('霧之城市')))
        self.assertIsNone(self.task.event_last_enc)

    def test_failed_selection_does_not_advance_sequence(self):
        self.feed(['將手伸入深處', '取出能夠抓住的東西', '迎接虛無'])
        self.step()
        expire(self.task.option_pending[1])
        self.step()
        self.assertEqual(self.task.event_visit, {})
        self.assertIsNone(self.task.event_pending_choice)
        self.feed(['將手伸入深處', '取出能夠抓住的東西', '迎接虛無'])
        self.step()
        self.assertEqual(self.task.event_pending_choice['order'], 1)

    def test_retrying_confirmation_does_not_advance_twice(self):
        self.feed(['將手伸入深處', '取出能夠抓住的東西', '迎接虛無'])
        self.step()
        self.confirm()
        self.task.rogue_event_confirmed()
        self.assertEqual(self.task.event_visit['void'], 1)

    def test_lifted_card_is_not_reidentified_while_waiting_for_confirmation(self):
        self.feed(['將手伸入深處', '取出能夠抓住的東西', '迎接虛無'])
        self.step()
        self.task.rogue_option_points.return_value = [(640, 677), (972, 677)]
        self.step()
        self.assertEqual(self.task.card_reader.read_name.call_count, 3)
        self.assertEqual(self.task.event_pending_choice['order'], 1)
        self.assertEqual(self.task.event_visit, {})

    def test_unknown_titles_stop_immediately_without_clicking_or_stale_choice(self):
        self.task.event_index = 3
        self.feed(['亂碼未知甲', '亂碼未知乙'])
        with self.assertRaises(TaskFailed):
            self.step()
        self.assertTrue(self.task.event_unknown)
        self.assertIsNone(self.task.event_index)
        self.task.tap_point.assert_not_called()
        self.task.rogue_dump_unknown.assert_called_once()
        self.task.rogue_pick_index.assert_not_called()

    def test_known_event_without_user_rule_stops(self):
        self.task.event_picks = {}
        self.feed(['取出左側箱子', '離開洞窟'])
        with self.assertRaises(TaskFailed):
            self.step()
        self.task.tap_point.assert_not_called()
        self.task.rogue_dump_unknown.assert_called_once()

    def test_disabled_event_recognition_does_not_enable_position_fallback(self):
        self.task.config.ChaoszeroRogue_RogueEventPick = False
        self.feed(['取出左側箱子', '離開洞窟'])
        with self.assertRaises(TaskFailed):
            self.step()
        self.task.tap_point.assert_not_called()
        self.task.rogue_pick_index.assert_not_called()

    def test_preselected_option_without_own_pending_choice_is_not_confirmed(self):
        self.feed(['取出左側箱子', '離開洞窟'])
        self.task.rogue_option_check_any.return_value = (640, 681)
        with self.assertRaises(TaskFailed):
            self.step()
        self.task.tap_point.assert_not_called()
        self.assertEqual(self.task.event_visit, {})

    def test_pending_selection_does_not_confirm_another_columns_checkmark(self):
        self.feed(['取出左側箱子', '離開洞窟'])
        self.step()
        self.task.tap_point.reset_mock()
        self.task.rogue_option_check_any.return_value = (640, 681)
        self.step()
        self.task.tap_point.assert_not_called()
        self.task.rogue_option_check_any.assert_called_once()
        self.assertEqual(self.task.event_visit, {})

    def test_submit_transition_is_consumed_without_another_pick(self):
        self.feed(['將手伸入深處', '取出能夠抓住的東西', '迎接虛無'])
        self.step()
        self.confirm()
        self.task.event_submit_wait.reset()
        self.task.tap_point.reset_mock()
        self.step()
        self.task.tap_point.assert_not_called()

    def test_sequence_exhaustion_keeps_final_configured_choice(self):
        self.task.event_visit['void'] = 8
        result = self.task.rogue_event_manual_index(['迎接虛無', '取出能夠抓住的東西'],
                                                   packs_for_world('霧之城市'))
        self.assertEqual(result, 2)
        self.assertEqual(self.task.event_choice['order'], 7)

    def test_configured_order_missing_from_database_does_not_leak_identity(self):
        self.task.event_picks['cave'] = [99]
        self.assertIsNone(self.task.rogue_event_manual_index(['取出左側箱子', '離開洞窟'],
                                                           packs_for_world('霧之城市')))
        self.assertIsNone(self.task.event_last_enc)

    def test_confirm_not_clicked_before_press_interval_does_not_advance(self):
        self.feed(['將手伸入深處', '取出能夠抓住的東西', '迎接虛無'])
        self.step()
        self.task.rogue_option_check_point.return_value = (308, 681)
        self.task.tap_point.reset_mock()
        self.task.handle_rogue_event(Mock(reached=Mock(return_value=False)))
        self.task.tap_point.assert_not_called()
        self.assertEqual(self.task.event_visit, {})

    def test_empty_page_is_not_handled(self):
        self.task.rogue_option_points.return_value = []
        self.assertFalse(self.step())
        self.task.tap_point.assert_not_called()


if __name__ == '__main__':
    unittest.main()
