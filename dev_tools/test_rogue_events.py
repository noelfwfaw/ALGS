"""Event selection and sequence regressions; no device connection is used."""

import ast
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from module.config.server import set_server

set_server('chaoszero')

from module.base.timer import Timer
from module.chaoszero.rogue import ChaoszeroRogue
from module.chaoszero.rogue_events import EventLibrary, SHARED_CHOICE_GROUPS, packs_for_world
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
                                  (3, '將手伸入最深處'),
                                  (7, '取出能夠抓住的東西'), (8, '迎接虛無')]),
        'cave': record('猝死洞窟', [(1, '取出左側箱子'), (2, '救出倖存者'),
                                  (3, '取出右側箱子'), (4, '離開洞窟')]),
    }
    task.event_picks = {'void': [1, 2, 3, 7], 'cave': [1]}
    task.card_reader = SimpleNamespace(read_name=Mock())
    task.event_visit = {}
    task.event_followups = set()
    task.event_last_enc = None
    task.event_choice = None
    task.event_pending_choice = None
    task.event_submit_wait = None
    task.event_submit_clear = Timer(0.8, count=1)
    task.event_submit_attempts = 0
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

    def test_border_band_rejects_combat_effect_and_keeps_single_card(self):
        image = self.task.device.image
        image[650, 480:800] = 255
        image[650:662, 639] = 255
        self.assertEqual(ChaoszeroRogue.rogue_option_points(self.task), [])
        image[677, 480:800] = 255
        image[677:689, 639] = 255
        self.assertEqual(ChaoszeroRogue.rogue_option_points(self.task), [(640, 677)])

    def test_border_band_rejects_battle_bottom_curved_arc(self):
        image = self.task.device.image
        for base_x in (362, 664):
            for dx in range(252):
                y = 671 + int(round(19 * (dx / 251.0) ** 2))
                image[y:min(y + 2, 691), base_x + dx] = 255
        self.assertEqual(ChaoszeroRogue.rogue_option_points(self.task), [])

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
        self.assertTrue(self.step())
        expire(self.task.event_submit_clear)
        self.assertTrue(self.step())

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

    def test_gourmet_valid_routes_with_real_event_data(self):
        event_id = 'uk_904_s01_05a'
        library = EventLibrary()
        self.task.event_library.records = {event_id: library.records[event_id]}
        first = ['剖開腹部。', '餵食糧食', '阻止進食']
        second = ['剖開腹部。', '再次餵食', '阻止進食']
        third = ['剖開腹部。', '阻止進食']
        for orders, pages in [([8], [(first, 3)]), ([2, 6], [(first, 2), (second, 3)]),
                              ([2, 3, 7], [(first, 2), (second, 2), (third, 2)])]:
            with self.subTest(orders=orders):
                self.task.event_visit.clear()
                self.task.event_picks = {event_id: orders}
                for order, (texts, position) in zip(orders, pages):
                    self.feed(texts)
                    self.assertTrue(self.step())
                    self.assertEqual(self.task.event_pending_choice['position'], position)
                    self.assertEqual(self.task.event_pending_choice['order'], order)
                    self.confirm()

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

    def test_residue_priority_uses_first_verified_choice_on_each_page(self):
        event_id = 'uk_904_s01_06b'
        library = EventLibrary()
        defaults = ['檢查痛症', '承諾會擊殺怪物']
        flower = defaults + ['取出亡魂之花']
        comfort = defaults + ['安慰']
        cases = [
            ([1, 4, 2], flower, 1, 3),
            ([1, 4, 2], comfort, 4, 3),
            ([1, 2], comfort, 2, 1),
            ([1], comfort, None, None),
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'rogue_event_picks.json'
            for priority, texts, order, position in cases:
                with self.subTest(priority=priority, order=order):
                    self.task = make_task()
                    self.task.event_library = library
                    self.task.event_visit[event_id] = 3
                    self.task.event_picks = None
                    path.write_text(json.dumps({'version': 1, 'picks': {
                        event_id: {'priority': priority},
                    }}), encoding='utf-8')
                    self.feed(texts)
                    with patch('module.chaoszero.rogue.EVENT_PICKS_FILE', str(path)):
                        if order is None:
                            with self.assertRaises(TaskFailed):
                                self.step()
                            self.task.tap_point.assert_not_called()
                            self.task.rogue_dump_unknown.assert_called_once()
                            self.assertIsNone(self.task.event_pending_choice)
                        else:
                            self.assertTrue(self.step())
                            choice = self.task.event_pending_choice
                            self.assertEqual((choice['id'], choice['order'], choice['position']),
                                             (event_id, order, position))
                    self.assertEqual(self.task.event_visit[event_id], 3)

    def test_same_title_priority_accepts_visible_variant_without_guessing_its_order(self):
        event_id = 'uk_402_s01_19a'
        library = EventLibrary()
        first, second = '詢問有關他的事', '表示要寫下結局'
        cases = [
            ([first, second], [second, first], first, 2),
            ([first, second], [second], second, 1),
            ([first], [second], None, None),
            ([first], [first, first], None, None),
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'rogue_event_picks.json'
            for priority, texts, title, position in cases:
                with self.subTest(priority=priority, texts=texts):
                    self.task = make_task()
                    self.task.config.ChaoszeroRogue_RogueWorld = '虛像劇場'
                    self.task.event_library = library
                    self.task.event_picks = None
                    path.write_text(json.dumps({'version': 1, 'picks': {
                        event_id: {'priority': priority},
                    }}), encoding='utf-8')
                    self.feed(texts)
                    with patch('module.chaoszero.rogue.EVENT_PICKS_FILE', str(path)):
                        if title is None:
                            with self.assertRaises(TaskFailed):
                                self.step()
                            self.task.tap_point.assert_not_called()
                            self.task.rogue_dump_unknown.assert_called_once()
                        else:
                            self.assertTrue(self.step())
                            choice = self.task.event_pending_choice
                            self.assertEqual((choice['id'], choice['order'], choice['target'], choice['position']),
                                             (event_id, None, title, position))

    def test_cave_continuation_breaks_ties_from_the_confirmed_branch(self):
        root = 'uk_904_s01_09a'
        middle = root + '-1'
        end = middle + '-1'
        self.task.event_library = EventLibrary()
        self.task.event_picks = {
            root: {'priority': [2, 1, 3]}, middle: {'priority': [1, 4]},
            end: {'priority': [1, 4]}, 'uk_904_s01_09b': [1, 4],
        }
        pages = [
            (root, 2, ['取出左側箱子', '搜索屍體', '取出右側箱子']),
            (middle, 1, ['取出左側箱子', '取出右側箱子', '離開洞窟']),
            (end, 4, ['取出右側箱子', '離開洞窟']),
        ]
        for event_id, order, titles in pages:
            self.feed(titles)
            self.assertTrue(self.step())
            choice = self.task.event_pending_choice
            self.assertEqual((choice['id'], choice['order']), (event_id, order))
            self.confirm()

    def test_config_does_not_disambiguate_identical_titles_across_events(self):
        expected = 'uk_900_s02_06c-1'
        other = 'uk_900_s02_01c'
        texts = ['取得聖物', '感應聖物']
        packs = packs_for_world('降臨的混沌')
        self.task.event_library = EventLibrary()
        self.task.event_picks = {other: [1]}
        self.assertIsNone(self.task.rogue_event_manual_index(texts, packs))
        self.task.event_followups = {expected}
        self.assertIsNone(self.task.rogue_event_manual_index(texts, packs))
        self.assertEqual(self.task.event_followups, {expected})
        self.task.event_picks[expected] = [2]
        self.assertEqual(self.task.rogue_event_manual_index(texts, packs), 1)
        self.assertEqual(self.task.event_choice['id'], expected)

    def test_convictor_shared_pick_works_from_map_and_followups(self):
        main, battle, ambush = SHARED_CHOICE_GROUPS[0]
        titles = ['閱讀聖書', '小睡一下', '喝下聖水']
        self.task.config.ChaoszeroRogue_RogueWorld = '藍壺'
        self.task.event_library = EventLibrary()
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'picks.json'
            with patch('module.chaoszero.rogue.EVENT_PICKS_FILE', str(path)):
                for rules, expected in (
                    ({main: 1, ambush: [1]}, 1),
                    ({battle: 2}, 2),
                    ({main: 3}, 3),
                    ({main: 1, ambush: 2}, None),
                ):
                    for followups in (set(), {battle}, {ambush}):
                        with self.subTest(rules=rules, followups=followups):
                            path.write_text(json.dumps({'version': 1, 'picks': rules}), encoding='utf-8')
                            self.task.event_picks = None
                            self.task.event_followups = followups
                            self.feed(titles)
                            position = self.task.rogue_event_index(self.task.rogue_option_points())
                            if expected is None:
                                self.assertIsNone(position)
                                self.assertIsNone(self.task.event_choice)
                            else:
                                self.assertEqual(position, (2, 3, 1)[expected - 1])
                                self.assertEqual(self.task.event_choice['id'], next(iter(followups), main))
        self.task.tap_point.assert_not_called()

    def test_shared_priority_checks_actual_options(self):
        group = SHARED_CHOICE_GROUPS[1]
        self.task.event_library = EventLibrary()
        self.task.event_picks = {group[-1]: {'priority': [1, 4]}}
        texts = ['洗清罪刑', '銘記教誨']
        self.assertEqual(self.task.rogue_event_manual_index(texts, packs_for_world('藍壺')), 1)
        self.assertEqual(self.task.event_choice['order'], 4)

    def test_shared_groups_have_equivalent_terminal_outcomes_in_source(self):
        selector = Path(__file__).with_name('rogue_events') / 'index.html'
        groups = re.search(r'const sharedPickGroups = (\[.*?\]);', selector.read_text(encoding='utf-8'), re.S)
        self.assertIsNotNone(groups)
        self.assertEqual(tuple(map(tuple, ast.literal_eval(groups[1]))), SHARED_CHOICE_GROUPS)
        library = EventLibrary()
        for group in SHARED_CHOICE_GROUPS:
            for event_id in group:
                with self.subTest(event_id=event_id):
                    self.assertEqual(library.shared_choice_ids(event_id), group)

    def test_changed_outcome_invalidates_shared_choice(self):
        main, alias, _ = SHARED_CHOICE_GROUPS[0]
        self.task.event_library = EventLibrary()
        self.task.event_picks = {main: [1]}
        option = self.task.event_library.records[alias]['options'][0]
        option['raw']['success_link_encounter_option_eff']['reward0_multiple_link'] = 'up_mhp_10p'
        self.assertEqual(self.task.event_library.shared_choice_ids(main), (main,))
        self.assertIsNone(self.task.rogue_event_manual_index(
            ['小睡一下', '喝下聖水', '閱讀聖書'], packs_for_world('藍壺')))
        self.assertIsNone(self.task.event_choice)

    def test_optional_failure_link_lasts_until_confirmed_route_change(self):
        root = 'uk_302_s02_02c'
        child = 'uk_302_s02_02a'
        self.task.config.ChaoszeroRogue_RogueWorld = '雙星之影'
        self.task.event_library = EventLibrary()
        self.task.event_picks = {root: [1], child: [3]}
        self.feed(['欺騙侵略者', '活化蘑菇', '偷偷品嚐蘑菇'])
        self.assertTrue(self.step())
        self.confirm()
        self.assertEqual(self.task.event_followups, {child})

        # A failed attempt opens the linked event; a success returns to the map.
        packs = packs_for_world(self.task.config.ChaoszeroRogue_RogueWorld)
        self.assertEqual(self.task.rogue_event_manual_index(['品嚐蘑菇', '吸入孢子'], packs), 2)
        self.assertEqual(self.task.event_choice['id'], child)
        self.task.node_pending = object()
        self.task.route_step = 1
        self.task.plan_index = 1
        self.task.rogue_map_appear = Mock(return_value=True)
        self.task.rogue_map_preview_appear = Mock(return_value=False)
        self.task.rogue_prompt_appear = Mock(return_value=False)
        self.task.rogue_battle_appear = Mock(return_value=True)
        self.assertFalse(self.task.rogue_route_confirm_move())
        self.assertEqual(self.task.event_followups, {child})
        self.task.rogue_map_appear.return_value = False
        self.assertTrue(self.task.rogue_route_confirm_move())
        self.assertEqual(self.task.event_followups, set())
        self.assertEqual(self.task.event_visit, {})

    def test_legacy_number_does_not_choose_ordinary_same_title_branches(self):
        event_id = 'uk_401_s01_02a'
        titles = ['回想痛苦的記憶', '回想幸福的記憶', '對抗']
        packs = packs_for_world('燃燒的生命')
        self.task.event_library = EventLibrary()
        for order in (3, 4):
            with self.subTest(order=order):
                self.task.event_picks = {event_id: [order]}
                self.assertIsNone(self.task.rogue_event_manual_index(titles, packs))
        self.task.event_picks = {event_id: {'priority': ['對抗', 1]}}
        self.assertEqual(self.task.rogue_event_manual_index(titles, packs), 3)
        self.assertIsNone(self.task.event_choice['order'])

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

    def test_dropped_confirmation_is_retried_without_advancing(self):
        event_id = 'uk_904_s01_05a'
        self.task.event_library = EventLibrary()
        self.task.event_picks = {event_id: [2, 6]}
        self.feed(['剖開腹部。', '餵食糧食', '阻止進食'])
        self.assertTrue(self.step())
        check = (640, 681)
        self.task.rogue_option_check_point.return_value = check
        self.assertTrue(self.step())
        self.assertEqual(self.task.event_visit, {})
        self.task.rogue_option_check_point.return_value = None
        self.assertTrue(self.step())
        self.assertEqual(self.task.event_visit, {})
        self.task.rogue_option_check_point.return_value = check
        self.assertTrue(self.step())
        self.task.tap_point.assert_called_with(*check, name='ROGUE_OPTION_CONFIRM')
        self.assertEqual(self.task.event_submit_attempts, 2)
        self.assertEqual(self.task.event_visit, {})
        self.assertEqual(self.task.event_pending_choice['order'], 2)
        self.task.rogue_option_check_point.return_value = None
        self.assertTrue(self.step())
        expire(self.task.event_submit_clear)
        self.assertTrue(self.step())
        self.assertEqual(self.task.event_visit, {event_id: 1})
        self.assertEqual(self.task.event_followups, {event_id})
        self.assertEqual(self.task.tap_point.call_count, 3)

    def test_persistent_confirmation_stops_after_bounded_attempts(self):
        self.feed(['取出左側箱子', '離開洞窟'])
        self.assertTrue(self.step())
        self.task.rogue_option_check_point.return_value = (308, 681)
        for _ in range(8):
            self.assertTrue(self.step())
        expire(self.task.event_submit_wait)
        with self.assertRaisesRegex(TaskFailed, 'confirmation did not leave'):
            self.step()
        self.assertEqual(self.task.event_visit, {})
        self.assertEqual(self.task.tap_point.call_count, 4)

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

    def test_priority_rule_handles_confusion_loop_and_variant_fallback(self):
        self.task.event_library = EventLibrary()
        self.task.event_picks['uk_904_s01_15a'] = {'priority': [1, '打破混亂', 8]}
        self.assertEqual(
            self.task.rogue_event_manual_index(['重新分析現況', '打破混亂', '接受怪物'],
                                               packs_for_world('霧之城市')),
            1,
        )
        self.assertEqual(self.task.event_choice['order'], 1)
        self.assertEqual(
            self.task.rogue_event_manual_index(['打破混亂', '接受怪物'],
                                               packs_for_world('霧之城市')),
            1,
        )
        self.assertIsNone(self.task.event_choice['order'])
        self.assertEqual(self.task.event_choice['target'], '打破混亂')


if __name__ == '__main__':
    unittest.main()
