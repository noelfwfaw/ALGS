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
from module.chaoszero.rogue_events import (
    EventLibrary,
    NO_PRIORITY_TIER,
    PRIORITY_TIER_NAMES,
    SHARED_CHOICE_GROUPS,
    keyword_priority_tier,
    packs_for_world,
    reward_priority_tier,
    summarize_seen_events,
)
from module.config.config_generated import GeneratedConfig
from module.exception import RequestHumanTakeover, TaskFailed
from module.webui.app import ROGUE_SECTIONS


def record(name, options):
    return {'name': name, 'pack': 'uk_904_s01',
            'options': [{'order': order, 'flavor': title} for order, title in options]}


def make_task():
    task = ChaoszeroRogue.__new__(ChaoszeroRogue)
    task.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
    task.config = SimpleNamespace(ChaoszeroRogue_RogueEventPick=True,
                                  ChaoszeroRogue_RogueEventCapture=False,
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
    task.event_root = None
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
    task.rogue_event_record_seen = Mock()
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
        # Side-border pixels reaching y=674 must still anchor y from the flat bottom edge (689-12=677).
        u_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        u_frame[689, 320:620] = 255
        u_frame[674:690, 320:322] = 255
        u_frame[677:690, 618:620] = 255
        self.task.device.image = u_frame
        self.assertEqual(ChaoszeroRogue.rogue_option_points(self.task), [(470, 677)])

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
        self.task.rogue_dump_unknown.assert_not_called()
        self.assertIsNone(self.task.event_pending_choice)
        self.assertEqual(self.task.event_visit, {})

    def test_missing_random_option_still_stops_with_classified_source(self):
        from dev_tools.gen_chaoszero_rogue_db import parse_encounter

        raw = json.loads((Path(__file__).parent / 'fixtures' / 'chaoszero' /
                          'rogue_residue.json').read_text(encoding='utf-8'))
        self.task.event_library.records = {raw['id']: parse_encounter(raw)}
        self.task.event_picks = {raw['id']: [1]}
        self.feed(['檢查痛游', '承諾會擊殺怪物', '安慰'])
        self.assertIsNone(self.task.rogue_event_manual_index(
            ['檢查痛游', '承諾會擊殺怪物', '安慰'], packs_for_world('霧之城市')))
        self.assertTrue(self.step())
        self.task.rogue_event_record.assert_called_once()
        choice = self.task.event_pending_choice
        self.assertEqual((choice['source'], choice['id'], choice['order'], choice['position'], choice['tier_name']),
                         ('keyword_fallback', raw['id'], 4, 3, '随机灵闪'))

    def test_residue_priority_uses_first_verified_choice_on_each_page(self):
        event_id = 'uk_904_s01_06b'
        library = EventLibrary()
        defaults = ['檢查痛症', '承諾會擊殺怪物']
        flower = defaults + ['取出亡魂之花']
        comfort = defaults + ['安慰']
        cases = [
            ([1, 4, 2], flower, 1, 3, 'configured'),
            ([1, 4, 2], comfort, 4, 3, 'configured'),
            ([1, 2], comfort, 2, 1, 'configured'),
            ([1], comfort, 4, 3, 'keyword_fallback'),
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'rogue_event_picks.json'
            for priority, texts, order, position, source in cases:
                with self.subTest(priority=priority, order=order, source=source):
                    self.task = make_task()
                    self.task.event_library = library
                    self.task.event_visit[event_id] = 3
                    self.task.event_picks = None
                    path.write_text(json.dumps({'version': 1, 'picks': {
                        event_id: {'priority': priority},
                    }}), encoding='utf-8')
                    self.feed(texts)
                    with patch('module.chaoszero.rogue.EVENT_PICKS_FILE', str(path)):
                        self.assertTrue(self.step())
                        choice = self.task.event_pending_choice
                        self.assertEqual((choice['source'], choice['id'], choice['order'], choice['position']),
                                         (source, event_id, order, position))
                    self.assertEqual(self.task.event_visit[event_id], 3)

    def test_same_title_priority_accepts_visible_variant_without_guessing_its_order(self):
        event_id = 'uk_402_s01_19a'
        library = EventLibrary()
        first, second = '詢問有關他的事', '表示要寫下結局'
        cases = [
            ([first, second], [second, first], first, 2, 'configured'),
            ([first, second], [second], second, 1, 'configured'),
            ([first], [second], second, 1, 'keyword_fallback'),
            ([first], [first, first], None, None, None),
        ]
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'rogue_event_picks.json'
            for priority, texts, title, position, source in cases:
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
                            self.task.rogue_dump_unknown.assert_not_called()
                        else:
                            self.assertTrue(self.step())
                            choice = self.task.event_pending_choice
                            self.assertEqual(choice['source'], source)
                            if source == 'configured':
                                self.assertEqual((choice['id'], choice['order'], choice['target'], choice['position']),
                                                 (event_id, None, title, position))
                            else:
                                self.assertEqual((choice['id'], choice['target'], choice['position'], choice['tier_name']),
                                                 (event_id, title, position, '降低压力'))

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
                                self.assertIsNone(self.task.rogue_event_manual_index(titles, packs_for_world('藍壺')))
                                self.assertEqual(position, 2)
                                self.assertEqual(self.task.event_library.fallback_pick(titles, packs_for_world('藍壺'))['tier_name'], '卡牌删除')
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
        self.task.rogue_dump_unknown.assert_not_called()
        self.task.rogue_pick_index.assert_not_called()

    def test_known_event_without_user_rule_requests_human_once(self):
        self.task.config.ChaoszeroRogue_RogueWorld = '藍壺'
        self.task.event_library = EventLibrary()
        child = 'uk_300_s02_15b-1'
        self.task.event_picks = {child: {'priority': ['打開左邊的箱子']}}
        self.feed(['查看食尿鬼飼養場', '忽路'])
        self.assertTrue(self.step())
        self.task.rogue_event_record.assert_called_once()
        self.task.rogue_dump_unknown.assert_not_called()
        choice = self.task.event_pending_choice
        self.assertEqual((choice['source'], choice['id'], choice['position'], choice['tier_name']),
                         ('keyword_fallback', 'uk_300_s02_15b', 1, '获得装备'))

        # Known event without user rule and without any tier 1..13 reward still requests human takeover.
        self.task = make_task()
        self.task.config.ChaoszeroRogue_RogueWorld = '第0研究所'
        self.task.event_library = EventLibrary()
        self.task.event_picks = {}
        self.feed(['偷聽對話', '離開次元'])
        with self.assertRaisesRegex(RequestHumanTakeover, '第0研究所「舉杯慶祝的紀錄」\\(uk_e01_s01_08a\\)'):
            self.step()
        self.task.tap_point.assert_not_called()
        self.task.rogue_dump_unknown.assert_not_called()

    def test_disabled_event_recognition_does_not_enable_position_fallback(self):
        self.task.config.ChaoszeroRogue_RogueEventPick = False
        self.feed(['取出左側箱子', '離開洞窟'])
        with self.assertRaises(TaskFailed):
            self.step()
        self.task.tap_point.assert_not_called()
        self.task.rogue_pick_index.assert_not_called()
        self.task.rogue_dump_unknown.assert_not_called()

    def test_unrecognized_event_capture_is_off_by_default_and_saves_only_when_enabled(self):
        self.assertFalse(GeneratedConfig.ChaoszeroRogue_RogueEventCapture)
        self.assertEqual(ROGUE_SECTIONS['Events'], ('RogueEventPick', 'RogueEventCapture'))

        self.task.config.ChaoszeroRogue_RogueEventCapture = True
        self.feed(['亂碼未知甲', '亂碼未知乙'])
        with self.assertRaises(TaskFailed):
            self.step()
        self.task.rogue_dump_unknown.assert_called_once()

        self.task = make_task()
        self.task.config.ChaoszeroRogue_RogueWorld = '藍壺'
        self.task.config.ChaoszeroRogue_RogueEventCapture = True
        self.task.event_library = EventLibrary()
        self.task.event_picks = {}
        self.feed(['查看食尿鬼飼養場', '忽路'])
        self.assertTrue(self.step())
        self.task.rogue_dump_unknown.assert_called_once()
        self.assertEqual(self.task.event_pending_choice['source'], 'keyword_fallback')

        self.task = make_task()
        self.task.config.ChaoszeroRogue_RogueWorld = '第0研究所'
        self.task.config.ChaoszeroRogue_RogueEventCapture = True
        self.task.event_library = EventLibrary()
        self.task.event_picks = {}
        self.feed(['偷聽對話', '離開次元'])
        with self.assertRaises(RequestHumanTakeover):
            self.step()
        self.task.rogue_dump_unknown.assert_called_once()

        self.task = make_task()
        self.task.config.ChaoszeroRogue_RogueEventPick = False
        self.task.config.ChaoszeroRogue_RogueEventCapture = True
        self.feed(['取出左側箱子', '離開洞窟'])
        with self.assertRaises(TaskFailed):
            self.step()
        self.task.rogue_dump_unknown.assert_called_once()

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

    def test_event_recorder_counts_unique_confirmed_root_events_without_screenshots(self):
        from module.chaoszero import rogue_events

        with TemporaryDirectory() as directory:
            seen_path = Path(directory) / 'rogue_event_seen.json'
            with patch.object(rogue_events, 'EVENT_SEEN_FILE', str(seen_path)):
                summary = rogue_events.summarize_seen_events()
                lanhu = next(item for item in summary if item['world'] == '藍壺')
                self.assertEqual((lanhu['seen'], lanhu['total']), (0, 30))

                # Real confirmation on 藍壺 root event increments 0 -> 1, repeat stays 1.
                self.task = make_task()
                self.task.config.ChaoszeroRogue_RogueWorld = '藍壺'
                self.task.event_library = EventLibrary()
                self.task.rogue_event_record_seen = ChaoszeroRogue.rogue_event_record_seen.__get__(
                    self.task, ChaoszeroRogue)
                self.task.event_picks = {
                    'uk_300_s02_15b': {'priority': ['查看食屍鬼飼養場']},
                    'uk_300_s02_15b-1': {'priority': ['打開左邊的箱子']},
                }
                self.feed(['查看食屍鬼飼養場', '忽略'])
                self.assertTrue(self.step())
                self.confirm()
                lanhu = next(item for item in rogue_events.summarize_seen_events() if item['world'] == '藍壺')
                self.assertEqual((lanhu['seen'], lanhu['total']), (1, 30))

                # Sub-event and repeated encounter of the same root event do not increment again.
                self.feed(['打開左邊的箱子', '打開右邊的箱子'])
                self.assertTrue(self.step())
                self.confirm()
                self.feed(['查看食屍鬼飼養場', '忽略'])
                self.assertTrue(self.step())
                self.confirm()
                lanhu = next(item for item in rogue_events.summarize_seen_events() if item['world'] == '藍壺')
                self.assertEqual((lanhu['seen'], lanhu['total']), (1, 30))

                # Follow-up chain into another root id (02c -> 02a) attributes to the entry root (02c).
                self.task.event_followups.clear()
                self.task.event_root = None
                self.task.config.ChaoszeroRogue_RogueWorld = '雙星之影'
                self.task.event_picks = {'uk_302_s02_02c': [1], 'uk_302_s02_02a': [3]}
                self.feed(['欺騙侵略者', '活化蘑菇', '偷偷品嚐蘑菇'])
                self.assertTrue(self.step())
                self.confirm()
                self.feed(['品嚐蘑菇', '吸入孢子'])
                self.assertTrue(self.step())
                self.confirm()
                self.assertEqual(rogue_events.load_seen_events(), {'uk_300_s02_15b', 'uk_302_s02_02c'})

                # Unconfirmed / missing-rule / unknown events are never recorded.
                self.task.event_picks = {}
                self.feed(['亂碼未知甲', '亂碼未知乙'])
                with self.assertRaises(TaskFailed):
                    self.step()
                self.assertEqual(rogue_events.load_seen_events(), {'uk_300_s02_15b', 'uk_302_s02_02c'})

                # Clearing resets back to 0 / 30.
                self.assertTrue(rogue_events.clear_seen_events())
                lanhu = next(item for item in rogue_events.summarize_seen_events() if item['world'] == '藍壺')
                self.assertEqual((lanhu['seen'], lanhu['total']), (0, 30))

    def test_webui_event_recorder_renders_world_counts_and_clears(self):
        from contextlib import nullcontext
        from unittest.mock import MagicMock
        from module.chaoszero import rogue_events
        from module.webui import app as webui_app

        gui = webui_app.AlasGUI.__new__(webui_app.AlasGUI)
        collapses = []
        texts = []

        def fake_text(val):
            texts.append(val)
            m = MagicMock()
            m.style.return_value = m
            return m

        def fake_collapse(title, content):
            collapses.append(title)
            return MagicMock()

        with TemporaryDirectory() as directory:
            seen_path = Path(directory) / 'rogue_event_seen.json'
            with patch.object(rogue_events, 'EVENT_SEEN_FILE', str(seen_path)), \
                    patch.object(webui_app, 'use_scope', return_value=nullcontext()), \
                    patch.object(webui_app, 'put_html'), \
                    patch.object(webui_app, 'put_text', side_effect=fake_text), \
                    patch.object(webui_app, 'put_buttons'), \
                    patch.object(webui_app, 'put_collapse', side_effect=fake_collapse), \
                    patch.object(webui_app, 'toast') as fake_toast, \
                    patch.object(webui_app, 't', side_effect=lambda k, **kw: f'{k}:{kw}' if kw else k):
                rogue_events.record_seen_event('uk_300_s02_01a')
                gui._render_rogue_event_recorder()
                self.assertIn('藍壺　1 / 30', collapses)

                collapses.clear()
                gui._clear_rogue_event_recorder()
                self.assertIn('藍壺　0 / 30', collapses)
                fake_toast.assert_called_once()

    def test_ambiguous_candidates_proceed_only_when_all_agree_on_same_card(self):
        self.task.config.ChaoszeroRogue_RogueWorld = '雙星之影'
        self.task.event_library = EventLibrary()
        texts = ['取得生肉', '取得烤肉一', '調查尿體']

        # User configured both 糧倉倉庫 (05a -> 3, 05a-1 -> 2), both mean 取得烤肉 (card 2).
        self.task.event_picks = {'uk_302_s02_05a': [3], 'uk_302_s02_05a-1': [2]}
        self.feed(texts)
        self.assertTrue(self.step())
        self.assertEqual(self.task.event_pending_choice['position'], 2)
        self.assertEqual(self.task.event_pending_choice['target'], '取得烤肉')
        self.confirm()
        self.task.rogue_event_record_seen.assert_called_with('uk_302_s02_05a', '糧倉倉庫')

        # Missing one candidate or disagreeing on which card to pick yields None manually, then uses keyword fallback.
        for picks in (
            {'uk_302_s02_05a': [3]},
            {'uk_302_s02_05a': [3], 'uk_302_s02_05a-1': [1]},
        ):
            with self.subTest(picks=picks):
                self.task = make_task()
                self.task.config.ChaoszeroRogue_RogueWorld = '雙星之影'
                self.task.event_library = EventLibrary()
                self.task.event_picks = picks
                self.assertIsNone(self.task.rogue_event_manual_index(
                    texts, packs_for_world('雙星之影')))
                self.feed(texts)
                self.assertTrue(self.step())
                choice = self.task.event_pending_choice
                self.assertEqual((choice['source'], choice['position'], choice['target'], choice['tier_name']),
                                 ('keyword_fallback', 3, '調查屍體', '获得装备'))

        # Ambiguous sibling variants propagate followups from all agreeing candidates (08a/08b/08c).
        self.task = make_task()
        self.task.config.ChaoszeroRogue_RogueWorld = '雙星之影'
        self.task.event_library = EventLibrary()
        self.task.event_picks = {
            'uk_302_s02_08a': [2], 'uk_302_s02_08b': [2], 'uk_302_s02_08c': [2],
        }
        self.feed(['剝掉甲殼', '進入內部'])
        self.assertTrue(self.step())
        self.confirm()
        self.assertEqual(
            self.task.event_followups,
            {'uk_302_s02_08a-1', 'uk_302_s02_08b-1', 'uk_302_s02_08c-1'},
        )

        # Unselected child branch (uk_900_s02_06c -> 2 skips 06c-1) must not block root uk_900_s02_01c.
        self.task = make_task()
        self.task.config.ChaoszeroRogue_RogueWorld = '降臨的混沌'
        self.task.event_library = EventLibrary()
        self.task.event_picks = {'uk_900_s02_01c': [1], 'uk_900_s02_06c': [2]}
        self.feed(['威應聖物', '取得聖物'])
        self.assertTrue(self.step())
        self.assertEqual(self.task.event_pending_choice['id'], 'uk_900_s02_01c')
        self.assertEqual(self.task.event_pending_choice['position'], 1)
        self.confirm()
        self.task.rogue_event_record_seen.assert_called_with('uk_900_s02_01c', '歌唱聖物')

        # Complementary single-condition DEFAULT option ('贖罪' on 16a) filters out 16a on 2-card 16b page.
        self.task = make_task()
        self.task.config.ChaoszeroRogue_RogueWorld = '降臨的混沌'
        self.task.event_library = EventLibrary()
        self.task.event_picks = {'uk_900_s02_16b': [1]}
        self.feed(['懺悔罪刑', '接受罪行'])
        self.assertTrue(self.step())
        self.assertEqual(self.task.event_pending_choice['id'], 'uk_900_s02_16b')
        self.assertEqual(self.task.event_pending_choice['position'], 1)

    def test_glowing_gold_frame_dice_event_is_detected(self):
        import cv2

        fixture = Path(__file__).parent / 'fixtures' / 'chaoszero' / 'rogue_event_glow.png'
        self.task.device.image = cv2.cvtColor(cv2.imread(str(fixture)), cv2.COLOR_BGR2RGB)
        points = ChaoszeroRogue.rogue_option_points(self.task)
        self.assertEqual([x for x, _ in points], [472, 808])
        self.assertTrue(all(y == 677 for _, y in points))
        # Battle curve / empty frames must not trigger the glow fallback.
        self.task.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.assertEqual(ChaoszeroRogue.rogue_option_points(self.task), [])
        # Solid white buttons and bright clouds in OPTION_BAND must not trigger the glow fallback.
        shop_fixture = Path(__file__).parent / 'fixtures' / 'chaoszero' / 'rogue_equipment_shop.png'
        self.task.device.image = cv2.cvtColor(cv2.imread(str(shop_fixture)), cv2.COLOR_BGR2RGB)
        self.assertEqual(ChaoszeroRogue.rogue_option_points(self.task), [])
        cloud = np.zeros((720, 1280, 3), dtype=np.uint8)
        cloud[650:700, 764:1128] = 190
        self.task.device.image = cloud
        self.assertEqual(ChaoszeroRogue.rogue_option_points(self.task), [])
        # Cyan battle card-play arc at y=675..678 (and even y=689) must not trigger glow fallback.
        arc = np.zeros((720, 1280, 3), dtype=np.uint8)
        arc[675:679, 450:830] = (230, 255, 255)
        self.task.device.image = arc
        self.assertEqual(ChaoszeroRogue.rogue_option_points(self.task), [])
        arc[675:679] = 0
        arc[689:691, 450:830] = (180, 245, 245)
        self.task.device.image = arc
        self.assertEqual(ChaoszeroRogue.rogue_option_points(self.task), [])
        # White event card borders joined by bright sand at y=689..690 must still be detected cleanly.
        white_joined = np.zeros((720, 1280, 3), dtype=np.uint8)
        for seg in ((323, 460), (484, 621), (659, 796), (820, 957)):
            white_joined[689:691, seg[0]:seg[1]] = (250, 250, 250)
        white_joined[689:691, 621:659] = (165, 160, 155)
        self.task.device.image = white_joined
        self.assertEqual(ChaoszeroRogue.rogue_option_points(self.task), [(472, 677), (808, 677)])
        # One clean card plus two sand-bridged cards must recover all 3 cards via glow fallback.
        three_partial = np.zeros((720, 1280, 3), dtype=np.uint8)
        three_partial[677:691, 150] = (250, 250, 250)
        three_partial[677:691, 466] = (250, 250, 250)
        for seg in ((158, 294), (318, 455), (491, 628), (652, 789), (825, 962), (986, 1123)):
            three_partial[689:691, seg[0]:seg[1]] = (250, 250, 250)
        three_partial[689:691, 628:652] = (165, 160, 155)
        three_partial[650:700, 790:825] = (165, 160, 155)
        self.task.device.image = three_partial
        self.assertEqual(ChaoszeroRogue.rogue_option_points(self.task), [(306, 677), (640, 677), (974, 677)])

    def test_compatible_filter_uses_encounter_match_for_noisy_non_target_ocr(self):
        self.task.config.ChaoszeroRogue_RogueWorld = '雙星之影'
        self.task.event_library = EventLibrary()
        self.task.event_picks = {'uk_302_s02_03a': [2], 'uk_302_s02_03a-1': [2]}
        # 剝取甲殼 OCR'd as 劍取甲殼一一子 has ratio 0.545 (between ENCOUNTER_MATCH 0.45 and OPTION_MATCH 0.55).
        self.feed(['劍取甲殼一一子', '抽取精華'])
        self.assertTrue(self.step())
        self.assertEqual(self.task.event_pending_choice['position'], 2)
        self.assertEqual(self.task.event_pending_choice['target'], '抽取精華')
        self.confirm()
        self.task.rogue_event_record_seen.assert_called_with('uk_302_s02_03a', '侵略者的中樞')

    def test_noisy_sibling_card_does_not_steal_or_block_configured_option(self):
        self.task.config.ChaoszeroRogue_RogueWorld = '雙星之影'
        self.task.event_library = EventLibrary()
        self.task.event_picks = {
            'uk_302_s02_04a': {'priority': [1]},
            'uk_302_s02_04c': [3],
        }
        # Card 1 is 翻找表面 with trailing OCR noise; card 2 is 翻找裡面 OCR'd as 翻找裸面.
        # Distinct-option matching rules out 04c (only one 翻找表面) and per-card competition picks card 1.
        self.feed(['翻找表面一一名', '翻找裸面'])
        self.assertTrue(self.step())
        self.assertEqual(self.task.event_pending_choice['id'], 'uk_302_s02_04a')
        self.assertEqual(self.task.event_pending_choice['position'], 1)
        self.assertEqual(self.task.event_pending_choice['target'], '翻找表面')
        self.confirm()
        self.task.rogue_event_record_seen.assert_called_with('uk_302_s02_04a', '駭人的糧食')

    def test_custom_altar_event_matches_under_other_category(self):
        self.task.config.ChaoszeroRogue_RogueWorld = '雙星之影'
        self.task.event_library = EventLibrary()
        self.task.event_picks = {'uk_000_s01_05': {'priority': [2]}}
        self.feed(['順從一生', '抵抗一三', '奪取凝聚體一'])
        self.assertTrue(self.step())
        self.assertEqual(self.task.event_pending_choice['id'], 'uk_000_s01_05')
        self.assertEqual(self.task.event_pending_choice['position'], 2)
        self.assertEqual(self.task.event_pending_choice['target'], '抵抗')
        self.confirm()
        self.task.rogue_event_record_seen.assert_called_with('uk_000_s01_05', '不明能量的祭壇')
        summary = {item['world']: item for item in summarize_seen_events({'uk_000_s01_05'})}
        self.assertEqual(summary['其他']['seen'], 1)
        self.assertEqual(summary['其他']['total'], 13)

    def test_priority_tier_order_and_classifiers(self):
        expected_names = [
            (1, '指定复制'),
            (2, '随机复制'),
            (3, '指定神闪'),
            (4, '随机神闪'),
            (5, '指定灵闪'),
            (6, '随机灵闪'),
            (7, '卡牌删除'),
            (8, '获得装备'),
            (9, '提高HP上限'),
            (10, '获得信用点'),
            (11, '降低压力'),
            (12, '恢复HP'),
            (13, '卡牌转换'),
        ]
        self.assertEqual(list(PRIORITY_TIER_NAMES.items()), expected_names)

        reward_cases = [
            ({'type': 'CARD_COPY_HAVE_SELECT'}, 1),
            ({'type': 'CARD_COPY_SELECT_3_1'}, 2),
            ({'type': 'ADD_R_SPARK_GOD_SELECT'}, 3),
            ({'type': 'ADD_R_SPARK_GOD_RANDOM'}, 4),
            ({'type': 'R_SPARK_SELECT'}, 5),
            ({'type': 'R_SPARK_RANDOM'}, 6),
            ({'type': 'CARD_REMOVE_HAVE_SELECT'}, 7),
            ({'type': 'EQUIPMENT_PRE_RANDOM'}, 8),
            ({'type': 'MAX_HP_PCT', 'amount': [10, 10]}, 9),
            ({'type': 'CREDIT_VALUE', 'amount': [80, 120]}, 10),
            ({'type': 'STRESS_VALUE', 'amount': [-5, -5]}, 11),
            ({'type': 'HP_PCT', 'amount': [30, 30]}, 12),
            ({'type': 'CARD_TRANSFORM_HAVE_SELECT'}, 13),
            ({'type': 'MAX_HP_PCT', 'amount': [-10, -10]}, NO_PRIORITY_TIER),
            ({'type': 'CREDIT_VALUE', 'amount': [-30, -30]}, NO_PRIORITY_TIER),
            ({'type': 'STRESS_VALUE', 'amount': [5, 5]}, NO_PRIORITY_TIER),
            ({'type': 'HP_PCT', 'amount': [-10, -10]}, NO_PRIORITY_TIER),
        ]
        for reward, expected in reward_cases:
            with self.subTest(reward=reward):
                self.assertEqual(reward_priority_tier(reward), expected)

        keyword_cases = [
            ('選擇1張卡牌進行複製', 1),
            ('隨機複製1張卡牌', 2),
            ('賦予所選1張卡牌[戴奧斯]靈光一閃', 3),
            ('賦予隨機1張卡牌[戴奧斯]靈光一閃', 4),
            ('選擇張卡牌觸發靈光一閃', 5),
            ('隨機戰鬥員靈光一閃次', 6),
            ('選擇1張卡牌移除', 7),
            ('所有戰鬥員壓力增加獲得裝\n備複蝕核心', 8),
            ('最大HP 10% 增加', 9),
            ('信用點數 100 增加', 10),
            ('壓力減少 5', 11),
            ('恢復 30% HP', 12),
            ('選擇1張卡牌轉換', 13),
            ('最大HP 10% 減少', NO_PRIORITY_TIER),
            ('信用點數減少', NO_PRIORITY_TIER),
            ('所有戰鬥員壓力增加', NO_PRIORITY_TIER),
            ('移除 1 個隨機裝備', NO_PRIORITY_TIER),
        ]
        for text, expected in keyword_cases:
            with self.subTest(text=text):
                self.assertEqual(keyword_priority_tier(text), expected)

    def test_user_reported_ocr_miss_uk_900_s02_05b_uses_keyword_fallback(self):
        self.task.config.ChaoszeroRogue_RogueWorld = '降臨的混沌'
        self.task.event_library = EventLibrary()
        self.task.event_picks = {'uk_900_s02_05b': [4]}
        titles = ['口才察覺情緒', '挑戰', '全都逃走了']
        bodies = [
            '擲股\n茂功時無法預測結果',
            '淮入情怒的魔像自動機戰鬥\n選擇張卡牌觸發靈光一閃\n信用點數增加',
            '事件結束',
        ]
        side_effects = titles + [line for body in bodies for line in body.split('\n') + [''] * (3 - len(body.split('\n')))]
        self.feed(titles)
        self.task.card_reader.read_name = Mock(side_effect=side_effects)
        self.assertIsNone(self.task.rogue_event_manual_index(titles, packs_for_world('降臨的混沌')))
        self.assertTrue(self.step())
        self.task.rogue_event_record.assert_called_once()
        choice = self.task.event_pending_choice
        self.assertEqual((choice['source'], choice['id'], choice['order'], choice['position'], choice['tier'], choice['tier_name']),
                         ('keyword_fallback', 'uk_900_s02_05b', 4, 2, 5, '指定灵闪'))

    def test_body_ocr_keyword_fallback_picks_highest_priority_on_unknown_titles(self):
        self.task.event_library = EventLibrary.__new__(EventLibrary)
        self.task.event_library.records = {}
        titles = ['未知選項甲', '未知選項乙', '未知選項丙']
        body_calls = [
            '獲得隨機裝備', '', '',
            '賦予所選張卡牌戴奧斯靈光一閃', '', '',
            '壓力減少', '', '',
        ]
        self.feed(titles)
        self.task.card_reader.read_name = Mock(side_effect=titles + body_calls)
        self.assertTrue(self.step())
        self.task.rogue_event_record.assert_called_once()
        choice = self.task.event_pending_choice
        self.assertEqual((choice['source'], choice['position'], choice['tier'], choice['tier_name']),
                         ('keyword_fallback', 2, 3, '指定神闪'))

    def test_season_floor3_purple_healing_option_is_detected_and_fixed_to_card2(self):
        import cv2

        fixture = Path(__file__).parent / 'fixtures' / 'chaoszero' / 'rogue_event_floor3.png'
        im = cv2.cvtColor(cv2.imread(str(fixture)), cv2.COLOR_BGR2RGB)
        self.task.device.image = im
        self.task.config.ChaoszeroRogue_RogueWorld = '賽季卡厄思'
        self.task.event_library = EventLibrary()

        points = ChaoszeroRogue.rogue_option_points(self.task)
        self.assertEqual(points, [(472, 677), (808, 677)])
        self.task.rogue_option_points = Mock(return_value=points)
        self.task.card_reader = None
        self.assertTrue(self.step())
        self.assertEqual(self.task.event_index, 2)
        self.assertEqual(self.task.event_pending_choice['source'], 'season_floor3')
        self.task.tap_point.assert_called_once_with(808, 590, name='ROGUE_OPTION')

        # Even if card bodies vary completely on Floor 3 once floor3_started is set, always pick option 2.
        self.task.floor3_started = True
        self.task.option_pending = None
        self.task.event_page = None
        self.task.event_index = None
        self.task.event_pending_choice = None
        self.task.tap_point.reset_mock()
        self.task.card_reader = SimpleNamespace(read_name=Mock(side_effect=['隨機甲', '未知乙']))
        self.assertTrue(self.step())
        self.assertEqual(self.task.event_index, 2)
        self.task.tap_point.assert_called_once_with(808, 590, name='ROGUE_OPTION')

        # Keyword tier also covers OCR '恢複' variant for normal fallback recovery.
        self.assertEqual(keyword_priority_tier('恢複所有戰鬥員壓力'), 12)


if __name__ == '__main__':
    unittest.main()
