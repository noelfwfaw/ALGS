"""Equipment rules and real screenshot regressions, without device input."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from module.config.server import set_server

set_server('chaoszero')

from dev_tools.gen_chaoszero_rogue_relics import records
from module.chaoszero.rogue import ChaoszeroRogue, REST_WAIT
from module.chaoszero.rogue_equipment import DETAIL_TITLE, Equipment, RelicLibrary
from module.chaoszero.assets import ROGUE_EQUIP_ASSAULT_BOOTS
from module.exception import TaskFailed


FIXTURES = Path(__file__).parent / 'fixtures' / 'chaoszero'


def frame(state):
    return np.array(Image.open(str(FIXTURES / ('rogue_equipment_%s.png' % state))).convert('RGB'))


def make_task(state='event', rules=''):
    task = ChaoszeroRogue.__new__(ChaoszeroRogue)
    task.device = SimpleNamespace(image=frame(state), stuck_record_add=Mock())
    task.config = SimpleNamespace(data={'ChaoszeroRogue': {'ChaoszeroRogue': {'RogueEquipFilter': rules}}})
    task.tap_point = Mock()
    task.rogue_dump_unknown = Mock()
    task.route_step = 4
    task.core_started = False
    return task, Equipment(task)


def select_row(task, row):
    for r in range(3):
        task.device.image[159 + 160 * r:272 + 160 * r, 776:781] = 0
    if row is not None:
        task.device.image[159 + 160 * row:272 + 160 * row, 776:781] = (255, 180, 90)


def change_name(equipment, name, shop=False):
    def read(image, area, **kwargs):
        if area == (1000, 78, 1275, 120):
            return '請選擇戰鬥員'
        if area == (445, 650, 520, 690):
            return '取消' if shop else ''
        return name
    equipment.reader.read_name = Mock(side_effect=read)


class RelicLibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = RelicLibrary()

    def test_download_contains_equipment_slots_and_unique_tag_without_stars(self):
        self.assertGreaterEqual(len(self.library.items), 571)
        self.assertEqual({i['slot'] for i in self.library.items}, {0, 1, 2})
        self.assertTrue(any(i['unique'] for i in self.library.items))
        self.assertTrue(all('stars' not in i for i in self.library.items))
        self.assertEqual(self.library.lookup('調節時間器')['slot'], 2)
        self.assertFalse(self.library.lookup('寶石的心臟')['unique'])

    def test_generator_excludes_other_relics_and_preserves_unique_not_stars(self):
        source = [{'id': 'a', 'name': 'a', 'relic_type': 'EQUIP_WEAPON', 'rarity': 'RARITY_UNIQUE',
                   'reward_tag': ['delang']},
                  {'id': 'b', 'name': 'b', 'relic_type': 'RELIC', 'rarity': 'RARITY_RARE'}]
        result = records(source, [{'id': 'c', 'name': '角色', 'char_type': 'CHAR_COMBATANT'}])
        self.assertEqual(result['items'], [
            {'id': 'a', 'name': 'a', 'names': {}, 'slot': 0, 'unique': True, 'rarity': 3, 'icon': '', 'shop': True}])

    def test_rules_accept_wiki_names_english_and_ids(self):
        self.assertEqual(self.library.rules('調節時間器 = 維若妮卡'), {'eq_pub_035': '1033'})
        self.assertEqual(self.library.rules('# comment\nTime Regulator = Veronica'), {'eq_pub_035': '1033'})
        self.assertEqual(self.library.rules('eq_pub_035 = 1033'), {'eq_pub_035': '1033'})
        self.assertEqual(list(self.library.rules('混沌指控 = 1号位\n混沌觸手 = 1號位').items()),
                         [('eq_pub_038', 0), ('eq_pub_039', 0)])

    def test_arrow_priority_syntax_and_slot_type_enforcement(self):
        text = (
            '1号位 武器: 混沌指控 > 混沌觸手 > 迷霧水晶球\n'
            '1号位 护甲: 加強型戰鬥強化服\n'
            '維若妮卡 饰品: 調節時間器 > 亡魂之花\n'
        )
        rules = self.library.rules(text)
        self.assertEqual(list(rules.items()), [
            (self.library.lookup('混沌指控')['id'], 0),
            (self.library.lookup('混沌觸手')['id'], 0),
            (self.library.lookup('迷霧水晶球')['id'], 0),
            (self.library.lookup('加強型戰鬥強化服')['id'], 0),
            (self.library.lookup('調節時間器')['id'], '1033'),
            (self.library.lookup('亡魂之花')['id'], '1033'),
        ])
        self.assertEqual(
            list(self.library.rules('混沌指控 > 混沌觸手 = 1号位').items()),
            [('eq_pub_038', 0), ('eq_pub_039', 0)],
        )
        self.assertEqual(
            list(self.library.rules('[2号位]\n武器: 混沌指控 > 混沌觸手').items()),
            [('eq_pub_038', 1), ('eq_pub_039', 1)],
        )
        with self.assertRaises(ValueError):
            self.library.rules('1号位 武器: 調節時間器')

    def test_invalid_or_conflicting_rules_do_not_silently_change_recipients(self):
        for rule in ['調節時間器', '錯誤裝備 = 米卡', '調節時間器 = 錯誤角色',
                     '調節時間器 = 米卡\n調節時間器 = 維若妮卡']:
            with self.assertRaises(ValueError):
                self.library.rules(rule)

    def test_unknown_or_partial_names_are_not_guessed(self):
        for name in ['', '裝備', '變異', '時間']:
            self.assertIsNone(self.library.lookup(name, fuzzy=True), name)

    def test_same_named_source_variants_share_one_recipient_rule(self):
        first = self.library.lookup('加強型戰鬥強化服')
        self.assertIsNotNone(first)
        self.assertEqual(self.library.lookup('eq_tut_006')['id'], first['id'])
        self.assertEqual(self.library.rules('eq_tut_006 = 米卡'), {first['id']: '1039'})

    def test_verified_game_name_alias_preserves_wiki_name(self):
        self.assertEqual(self.library.lookup('禍之聖袍')['id'], 'eq_pub_041')
        self.assertEqual(self.library.lookup('禍之聖砲')['id'], 'eq_pub_041')

    def test_character_faces_are_identified_from_reference_screenshots(self):
        for state in ('event', 'shop', 'shop_disabled'):
            self.assertEqual(self.library.identify_characters(frame(state)), ['30093', '1033', '1039'])

    def test_reordered_party_is_identified_by_character_instead_of_row_number(self):
        image = frame('event')
        original = image.copy()
        for dest, source in enumerate((2, 0, 1)):
            image[147 + dest * 160:286 + dest * 160, 803:930] = original[
                147 + source * 160:286 + source * 160, 803:930]
        self.assertEqual(self.library.identify_characters(image), ['1039', '30093', '1033'])

    def test_missing_faces_do_not_produce_a_recipient(self):
        image = frame('event')
        image[147:610, 803:930] = 0
        self.assertEqual(self.library.identify_characters(image), [None, None, None])


class EquipmentTest(unittest.TestCase):
    def test_boots_ocr_correction_requires_matching_detail_art(self):
        task, equipment = make_task('event')
        equipment.reader.read_name = Mock(return_value='突擊軌')
        image = task.device.image
        self.assertIsNone(equipment.read_item(image, DETAIL_TITLE)[1])
        x1, y1, x2, y2 = ROGUE_EQUIP_ASSAULT_BOOTS.area
        reference = np.asarray(Image.open(ROGUE_EQUIP_ASSAULT_BOOTS.file).convert('RGB'))
        image[y1:y2, x1:x2] = reference[y1:y2, x1:x2]
        self.assertEqual(equipment.read_item(image, DETAIL_TITLE)[1]['id'], 'eq_pub_018')
        self.assertIsNone(equipment.read_item(image, (525, 151, 890, 188))[1])

    def test_empty_slots_precede_confirmed_upgrades_and_designated_gear_is_protected(self):
        task, equipment = make_task('shop', '調節時間器 = 維若妮卡')
        image = task.device.image
        incoming = equipment.library.lookup('亡魂之花')
        # The top accessory slot is empty, and the middle slot holds the specified clock.
        worn = equipment.library.equipped_items(image, 1, 2)
        self.assertIn('eq_pub_035', {item['id'] for item in worn})
        self.assertNotIn(1, equipment.recipients(incoming, image))
        # Without a reservation the same screenshot admits the higher-rarity replacement.
        equipment.rules.clear()
        self.assertEqual(equipment.recipients(incoming, image)[:2], [0, 1])
        self.assertNotIn(1, equipment.recipients(equipment.library.lookup('調節時間器'), image))

    def test_position_specific_priority_and_unique_slot_conflict(self):
        rules = ('混沌指控 = 2号位\n混沌觸手 = 2号位\n迷霧水晶球 = 2号位\n'
                 '亡魂之花 = 1号位\n非典型方塊 = 1号位')
        task, equipment = make_task('bloodsea', rules)
        image = task.device.image
        self.assertIn('eq_pub_039', {item['id'] for item in equipment.library.equipped_items(image, 1, 0)})
        self.assertEqual(equipment.recipients(equipment.library.lookup('混沌指控'), image), [1])
        self.assertEqual(equipment.recipients(equipment.library.lookup('迷霧水晶球'), image), [])
        self.assertNotIn(1, equipment.recipients(equipment.library.lookup('禍之聖袍'), image))

        image = frame('event_full')
        self.assertIn('eq_pub_031', {item['id'] for item in equipment.library.equipped_items(image, 0, 2)})
        self.assertEqual(equipment.recipients(equipment.library.lookup('亡魂之花'), image), [0])
        self.assertEqual(equipment.recipients(equipment.library.lookup('非典型方塊'), image), [])

    def test_unknown_occupied_slot_is_not_overwritten(self):
        task, equipment = make_task('event_full', '亡魂之花 = 1号位')
        image = task.device.image
        image[210:252, 1129:1177] = 0
        self.assertEqual(equipment.recipients(equipment.library.lookup('亡魂之花'), image), [])

    def test_shop_visits_only_for_available_unsatisfied_targets(self):
        rules = ('混沌指控 = 1号位\n混沌觸手 = 1号位\n迷霧水晶球 = 1号位\n黑曜石劍 = 1号位\n'
                 '亡魂之花 = 1号位\n非典型方塊 = 1号位')
        task, equipment = make_task('store', rules)
        self.assertEqual(equipment.shop_target_slots(), {0, 2})
        self.assertEqual({item['name'] for item in equipment.targets.values() if item['shop']},
                         {'黑曜石劍', '非典型方塊'})
        for name in ('混沌指控', '亡魂之花'):
            equipment.page = {'equipped_target': equipment.library.lookup(name)}
            equipment.record_equipped_target()
        self.assertFalse(equipment.shop_target_slots())
        self.assertFalse(equipment.handle_shop(Mock()))
        task.tap_point.assert_not_called()

    def test_shop_rejects_recognized_target_without_shop_tag(self):
        task, equipment = make_task('shop', '亡魂之花 = 1号位')
        change_name(equipment, '亡魂之花', shop=True)
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(465, 670, name='ROGUE_EQUIP_CANCEL')

    def test_reward_list_skips_superseded_target(self):
        task, equipment = make_task('list', '亡魂之花 = 1号位\n破壞之月 = 1号位')
        equipment.page = {'equipped_target': equipment.library.lookup('亡魂之花')}
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(420, 233, name='ROGUE_EQUIP_ITEM')

    def test_reward_list_salvages_only_when_every_choice_is_confirmed_obsolete(self):
        task, equipment = make_task('list', '亡魂之花 = 1号位\n破壞之月 = 1号位')
        equipment.record_equipped_target(equipment.library.lookup('亡魂之花'))
        lower = equipment.library.lookup('破壞之月')
        equipment.list_items = Mock(return_value=[(168, None), (408, lower)])
        equipment.handle(Mock())
        task.tap_point.assert_not_called()
        equipment.list_items.return_value = [(408, lower)]
        equipment.handle(Mock())
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(799, 670, name='ROGUE_EQUIP_SALVAGE')

    def test_english_numeric_equipment_name_survives_ocr(self):
        task, equipment = make_task('rfs17')
        area = (278, 278, 645, 316)
        self.assertEqual(equipment.reader.read_name(task.device.image, area, scale=1.5), '')
        text, item = equipment.read_item(task.device.image, area)
        self.assertIsNotNone(item, text)
        self.assertEqual(item['id'], equipment.library.lookup('RFS-17')['id'])

    def test_raw_name_fallback_preserves_letters_and_digits_without_changing_card_default(self):
        task, equipment = make_task('rfs17')
        equipment.reader._get_cht = Mock(return_value=None)
        ocr = Mock()
        ocr.cnocr.atomic_ocr_for_single_lines.return_value = [list('RFS-17')]
        equipment.reader._get_ocr = Mock(return_value=ocr)
        area = (278, 278, 645, 316)
        self.assertEqual(equipment.reader.read_name(task.device.image, area, raw=True), 'RFS-17')
        self.assertEqual(equipment.reader.read_name(task.device.image, area), '')

    def test_bloodsea_ocr_error_requires_a_clear_catalog_winner(self):
        task, equipment = make_task('bloodsea', '黑曜石劍 = 海德瑪麗')
        _, item = equipment.read_item(task.device.image, (278, 278, 645, 316))
        self.assertIsNotNone(item)
        self.assertEqual(item['id'], 'eq_pub_004')
        equipment.library.item_index.append({'id': 'test_close', 'name': '峰山血海',
                                              'names': {}, 'slot': 0, 'unique': False})
        self.assertIsNone(equipment.library.lookup('屁山血海', fuzzy=True))

    def test_unreadable_equipment_pages_stop_without_resetting_wait_or_submitted_state(self):
        for reason in ('prompt', 'mode', 'name', 'list'):
            for submitted in (False, True):
                with self.subTest(reason=reason, submitted=submitted):
                    task, equipment = make_task('list' if reason == 'list' else 'event')
                    if submitted:
                        equipment.page = {'identity': ('eq_pub_035', False), 'phase': 'submitted',
                                          'wait': Mock()}
                    if reason == 'prompt':
                        equipment.reader.read_name = Mock(return_value='')
                    elif reason == 'mode':
                        task.device.image[640:705, 700:1275] = 0
                        equipment.reader.read_name = Mock(side_effect=lambda image, area, scale=1.5:
                            '請選擇戰鬥員' if area[1] == 78 else '')
                    elif reason == 'name':
                        equipment.read_item = Mock(return_value=('', None))
                    else:
                        equipment.list_items = Mock(return_value=[])
                    self.assertTrue(equipment.handle(Mock()))
                    state = equipment.page
                    if submitted:
                        self.assertEqual(state['phase'], 'submitted')
                    wait = state['read_wait']
                    self.assertTrue(wait.started())
                    self.assertTrue(equipment.handle(Mock()))
                    self.assertIs(equipment.page, state)
                    self.assertIs(state['read_wait'], wait)
                    state['read_wait'] = Mock()
                    with self.assertRaises(TaskFailed):
                        equipment.handle(Mock())
                    task.tap_point.assert_not_called()

    def test_name_recovers_before_read_timeout_and_continues_assignment(self):
        task, equipment = make_task('event')
        item = equipment.library.lookup('調節時間器')
        equipment.read_item = Mock(side_effect=[('', None), (item['name'], item)])
        self.assertTrue(equipment.handle(Mock()))
        task.tap_point.assert_not_called()
        self.assertTrue(equipment.handle(Mock()))
        task.tap_point.assert_called_once_with(1153, 231, name='ROGUE_EQUIP_SLOT')
        self.assertNotIn('read_wait', equipment.page)

    def test_ordinary_item_fills_an_empty_slot_instead_of_replacing_existing_item(self):
        task, equipment = make_task()
        self.assertEqual(equipment.empty_slots(task.device.image),
                         [[True, True, True], [True, True, True], [True, True, False]])
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(1153, 231, name='ROGUE_EQUIP_SLOT')
        select_row(task, 0)
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_OK')

    def test_configured_recipient_overrides_empty_slots_and_game_recommendation(self):
        task, equipment = make_task(rules='調節時間器 = 米卡')
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(1153, 551, name='ROGUE_EQUIP_SLOT')
        select_row(task, 2)
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_OK')

    def test_absent_designated_character_is_not_replaced_by_another_character(self):
        task, equipment = make_task(rules='調節時間器 = 席琳娜')
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(799, 670, name='ROGUE_EQUIP_SALVAGE')

    def test_uncertain_character_does_not_destroy_reserved_equipment(self):
        task, equipment = make_task(rules='調節時間器 = 米卡')
        equipment.library.identify_characters = Mock(return_value=['30093', '1033', None])
        with self.assertRaises(TaskFailed):
            equipment.handle(Mock())
        task.tap_point.assert_not_called()
        task.rogue_dump_unknown.assert_called_once()

    def test_clicking_a_preselected_slot_can_toggle_it_off_then_retry(self):
        task, equipment = make_task(rules='調節時間器 = 維若妮卡')
        equipment.handle(Mock())
        select_row(task, None)
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_count, 2)
        select_row(task, 1)
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_OK')

    def test_no_empty_slots_salvages_event_equipment(self):
        task, equipment = make_task()
        equipment.empty_slots = Mock(return_value=[[False] * 3 for _ in range(3)])
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(799, 670, name='ROGUE_EQUIP_SALVAGE')

    def test_full_armor_event_layout_locates_right_hand_salvage_button(self):
        task, equipment = make_task('event_full')
        self.assertTrue(equipment.handle(Mock()))
        self.assertEqual(equipment.page['identity'], ('eq_pub_021', False))
        self.assertEqual(equipment.page['rows'], [])
        task.tap_point.assert_called_once_with(1052, 670, name='ROGUE_EQUIP_SALVAGE')
        self.assertTrue(equipment.page['salvage'])
        task.device.image = frame('salvage_confirm')
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_SALVAGE_CONFIRM')

    def test_salvage_button_must_be_visible_before_discarding(self):
        task, equipment = make_task('event_full')
        task.device.image[640:705, 700:1275] = 0
        equipment.page = {'identity': ('eq_pub_021', False), 'rows': [],
                          'index': 0, 'tries': 0, 'phase': 'select'}
        equipment.no_recipient(False)
        task.tap_point.assert_not_called()
        self.assertNotIn('salvage', equipment.page)
        self.assertEqual(equipment.page['phase'], 'select')

    def test_salvage_template_locates_controls_and_rejects_shop(self):
        for state, expected in [('event', (799, 670)), ('event_full', (1052, 670)),
                                ('shop', None), ('shop_disabled', None), ('list', (799, 670))]:
            with self.subTest(state=state):
                _, equipment = make_task(state)
                self.assertEqual(equipment.salvage_point(), expected)

    def test_reward_list_does_not_salvage_while_choosing_item(self):
        task, equipment = make_task('list')
        self.assertIsNotNone(equipment.salvage_point())
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_ITEM')

    def test_own_salvage_confirms_credit_dialog_once(self):
        task, equipment = make_task()
        equipment.empty_slots = Mock(return_value=[[False] * 3 for _ in range(3)])
        equipment.handle(Mock())
        task.device.image = frame('salvage_confirm')
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_SALVAGE_CONFIRM')
        for _ in range(4):
            equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_count, 2)
        equipment.page['wait'] = Mock()
        with self.assertRaises(TaskFailed):
            equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_count, 2)

    def test_restarting_on_salvage_dialog_cancels_then_rechecks_unobscured_equipment(self):
        task, equipment = make_task('salvage_confirm')
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(435, 454, name='ROGUE_EQUIP_SALVAGE_RECHECK')
        task.device.image = frame('event')
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_SLOT')

    def test_salvage_confirmation_ignores_other_dialogs_and_obeys_cooldown(self):
        task, equipment = make_task('salvage_confirm')
        press = Mock(); press.reached.return_value = False
        equipment.handle(press)
        task.tap_point.assert_not_called()
        task.device.image[282:340, 487:801] = 0
        equipment.handle(Mock())
        task.tap_point.assert_not_called()

    def test_shop_buys_only_configured_item_for_correct_character(self):
        task, equipment = make_task('shop', '寶石的心臟 = 海德瑪麗')
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(1153, 231, name='ROGUE_EQUIP_SLOT')
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_BUY')
        self.assertLess(task.tap_point.call_args[0][0], 1000)

    def test_nonconfigured_shop_equipment_is_cancelled_even_when_slots_are_empty(self):
        task, equipment = make_task('shop', '調節時間器 = 米卡')
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(465, 670, name='ROGUE_EQUIP_CANCEL')

    def test_unread_cancel_does_not_misclassify_shop_as_event_and_purchase(self):
        task, equipment = make_task('shop', '調節時間器 = 米卡')
        read = equipment.reader.read_name
        equipment.reader.read_name = Mock(side_effect=lambda image, area, **kw:
                                          '' if area == (445, 650, 520, 690) else read(image, area, **kw))
        self.assertTrue(equipment.handle(Mock()))
        task.tap_point.assert_not_called()

    def test_grey_purchase_never_submits_and_eventually_cancels(self):
        task, equipment = make_task('shop_disabled', '寶石的心臟 = 海德瑪麗')
        select_row(task, 0)
        for _ in range(3):
            equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_CANCEL')
        self.assertNotIn('ROGUE_EQUIP_BUY', [c[1]['name'] for c in task.tap_point.call_args_list])

    def test_unique_same_slot_replacement_is_allowed_for_designated_character(self):
        task, equipment = make_task(rules='混沌指控 = 維若妮卡')
        unique = equipment.library.lookup('混沌指控')
        occupied = equipment.empty_slots(task.device.image)
        occupied[1][0] = False
        equipment.empty_slots = Mock(return_value=occupied)
        equipment.library.equipped_items = Mock(return_value=[equipment.library.lookup('混沌觸手')])
        change_name(equipment, unique['name'])
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(971, 391, name='ROGUE_EQUIP_SLOT')
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_OK')

    def test_real_purple_unique_title_is_read_and_assigned_to_designated_character(self):
        task, equipment = make_task('unique', '禍之聖袍 = 維若妮卡')
        text, item = equipment.read_item(task.device.image, (278, 278, 645, 316))
        self.assertEqual(text, '禍之聖袍')
        self.assertEqual(item['id'], 'eq_pub_041')
        self.assertTrue(item['unique'])
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(1062, 391, name='ROGUE_EQUIP_SLOT')

    def test_unique_cross_slot_conflict_does_not_submit_or_give_reserved_item_away(self):
        task, equipment = make_task(rules='混沌指控 = 維若妮卡')
        unique = equipment.library.lookup('混沌指控')
        change_name(equipment, unique['name'])
        task.device.image[630:, 1015:] = 90  # Disabled confirmation; keep the salvage control visible.
        for _ in range(3):
            equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_SALVAGE')
        self.assertNotIn('ROGUE_EQUIP_OK', [c[1]['name'] for c in task.tap_point.call_args_list])

    def test_unreserved_unique_item_tries_next_empty_character_after_disabled_confirm(self):
        task, equipment = make_task()
        unique = next(i for i in equipment.library.items if i['unique'] and i['slot'] == 0)
        change_name(equipment, unique['name'])
        footer = task.device.image[630:].copy()
        equipment.handle(Mock())
        select_row(task, 0)
        task.device.image[630:, 1015:] = 90
        equipment.handle(Mock())
        equipment.handle(Mock())
        task.tap_point.assert_called_with(971, 391, name='ROGUE_EQUIP_SLOT')
        select_row(task, 1)
        task.device.image[630:] = footer
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_OK')

    def test_wrong_selected_row_does_not_submit_or_purchase(self):
        task, equipment = make_task('shop', '寶石的心臟 = 米卡')
        equipment.handle(Mock())
        equipment.handle(Mock())
        self.assertTrue(all(c[1]['name'] == 'ROGUE_EQUIP_SLOT' for c in task.tap_point.call_args_list))

    def test_unidentified_equipment_is_held_without_purchase_or_salvage(self):
        task, equipment = make_task()
        change_name(equipment, '無法識別的裝備')
        equipment.handle(Mock())
        task.tap_point.assert_not_called()

    def test_submission_is_not_clicked_twice(self):
        task, equipment = make_task('shop', '寶石的心臟 = 海德瑪麗')
        equipment.handle(Mock())
        equipment.handle(Mock())
        for _ in range(5):
            equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_count, 2)
        equipment.page['wait'] = Mock()
        with self.assertRaises(TaskFailed):
            equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_count, 2)
        task.rogue_dump_unknown.assert_called_once()

    def test_cooldown_prevents_clicks(self):
        task, equipment = make_task()
        press = Mock()
        press.reached.return_value = False
        self.assertTrue(equipment.handle(press))
        task.tap_point.assert_not_called()

    def test_equipment_list_selects_a_recognized_item_and_bounds_failed_clicks(self):
        task, equipment = make_task('list')
        for _ in range(3):
            equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_ITEM')
        with self.assertRaises(TaskFailed):
            equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_count, 3)

    def test_equipment_list_prioritizes_configured_second_item(self):
        task, equipment = make_task('list', '破壞之月 = 米卡')
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(420, 473, name='ROGUE_EQUIP_ITEM')

    def test_list_card_without_magnifier_is_still_recognized(self):
        task, equipment = make_task('list_no_icon')
        self.assertEqual([item['name'] for _, item in equipment.list_items(task.device.image)],
                         ['迷霧水晶球', '空空的虛無殘片'])

    def test_configured_reward_without_magnifier_is_not_skipped(self):
        task, equipment = make_task('list_no_icon', '迷霧水晶球 = 米卡')
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(420, 233, name='ROGUE_EQUIP_ITEM')

    def test_selected_boss_reward_requires_confirmation_before_assignment(self):
        task, equipment = make_task('list_selected')
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_CHOOSE')
        self.assertGreater(task.tap_point.call_args[0][0], 1000)
        for _ in range(4):
            equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_count, 1)
        equipment.list_wait = Mock()
        with self.assertRaises(TaskFailed):
            equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_count, 1)

    def test_selected_other_reward_is_changed_to_configured_reward_before_confirming(self):
        task, equipment = make_task('list_selected', '破壞之月 = 米卡')
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(420, 473, name='ROGUE_EQUIP_ITEM')

    def test_selected_reward_with_disabled_confirm_is_not_toggled_or_submitted(self):
        task, equipment = make_task('list_selected')
        task.device.image[630:] = 90
        equipment.handle(Mock())
        task.tap_point.assert_not_called()

    def test_confirmed_boss_reward_transitions_into_character_assignment(self):
        task, equipment = make_task('list_selected')
        equipment.handle(Mock())
        task.device.image = frame('event')
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_SLOT')
        self.assertIsNone(equipment.list_wait)

    def test_returning_to_list_does_not_reacquire_equipped_target(self):
        task, equipment = make_task('event', '調節時間器 = 維若妮卡')
        equipment.handle(Mock())
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_OK')
        task.device.image = frame('list')
        equipment.handle(Mock())
        task.device.image = frame('event')
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_EQUIP_SALVAGE')

    def test_no_rules_means_no_shop_inspection_or_purchase(self):
        task, equipment = make_task('store')
        self.assertFalse(equipment.handle_shop(Mock()))
        task.tap_point.assert_not_called()

    def test_store_previews_are_free_bounded_and_reset_at_the_next_node(self):
        task, equipment = make_task('store', '突擊靴 = 米卡')
        self.assertTrue(equipment.handle_shop(Mock()))
        task.tap_point.assert_called_with(140, 390, name='ROGUE_SHOP_EQUIPMENT')
        self.assertTrue(equipment.handle_shop(Mock()))
        task.tap_point.assert_called_with(390, 390, name='ROGUE_SHOP_EQUIPMENT')
        task.device.image[650:695, 175:250] = 0
        self.assertFalse(equipment.handle_shop(Mock()))
        task.route_step += 1
        self.assertTrue(equipment.handle_shop(Mock()))
        self.assertEqual(task.tap_point.call_count, 3)

    def test_actual_store_free_label_and_refresh_counter(self):
        task, equipment = make_task('store', '調節時間器 = 米卡')
        self.assertEqual(equipment.shop_free_refresh_count(), 2)
        equipment.shop_context = (task.core_started, task.route_step)
        equipment.shop_seen = {0, 1}
        self.assertTrue(equipment.handle_shop(Mock()))
        task.tap_point.assert_called_once_with(100, 672, name='ROGUE_SHOP_REFRESH_FREE')
        self.assertTrue(equipment.handle_shop(Mock()))
        self.assertEqual(task.tap_point.call_count, 1)

    def test_free_refresh_dialog_confirms_own_request_only_once(self):
        task, equipment = make_task('refresh_confirm', '黑曜石劍 = 海德瑪麗')
        wait = Mock()
        wait.reached.return_value = False
        equipment.shop_refresh = (2, wait)
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_SHOP_REFRESH_CONFIRM')
        self.assertTrue(equipment.shop_refresh_confirmed)
        with patch('module.base.timer.time', return_value=equipment.shop_refresh[1]._start + 12):
            equipment.handle(Mock())
            equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_count, 1)
        equipment.shop_refresh = (2, Mock())
        with self.assertRaises(TaskFailed):
            equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_count, 1)

    def test_last_free_refresh_is_confirmed_by_paid_state_without_clicking_paid_refresh(self):
        task, equipment = make_task('store_free_one', '突擊靴 = 海德瑪麗')
        equipment.shop_context = (task.core_started, task.route_step)
        equipment.shop_seen = {0, 1, 3}
        self.assertTrue(equipment.handle_shop(Mock()))
        task.tap_point.assert_called_once_with(100, 672, name='ROGUE_SHOP_REFRESH_FREE')
        task.device.image = frame('store_paid')
        self.assertTrue(equipment.handle_shop(Mock()))
        task.tap_point.assert_called_with(890, 390, name='ROGUE_SHOP_EQUIPMENT')
        equipment.handle_shop(Mock())
        task.tap_point.assert_called_with(1140, 390, name='ROGUE_SHOP_EQUIPMENT')
        self.assertFalse(equipment.handle_shop(Mock()))
        self.assertEqual(task.tap_point.call_count, 3)

    def test_restart_refresh_dialog_is_cancelled_before_rechecking_free_status(self):
        task, equipment = make_task('refresh_confirm', '突擊靴 = 海德瑪麗')
        equipment.handle(Mock())
        task.tap_point.assert_called_once_with(435, 454, name='ROGUE_SHOP_REFRESH_RECHECK')
        equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_count, 1)
        task.device.image = frame('store')
        self.assertFalse(equipment.handle(Mock()))
        equipment.handle_shop(Mock())
        task.tap_point.assert_called_with(140, 390, name='ROGUE_SHOP_EQUIPMENT')

    def test_refresh_dialog_respects_cooldown_and_does_not_confirm_another_modal(self):
        task, equipment = make_task('refresh_confirm', '黑曜石劍 = 海德瑪麗')
        press = Mock()
        press.reached.return_value = False
        self.assertTrue(equipment.handle(press))
        task.tap_point.assert_not_called()
        wait = Mock()
        wait.reached.return_value = False
        equipment.shop_refresh = (2, wait)
        task.device.image = frame('salvage_confirm')
        self.assertTrue(equipment.handle(Mock()))
        task.tap_point.assert_not_called()

    def test_camp_settle_timer_starts_once_before_shop_or_rest_can_act(self):
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.rest_settling = False
        self.assertFalse(task.rogue_rest_settled())
        wait = task.rest_wait
        self.assertTrue(wait.started())
        for _ in range(3):
            self.assertFalse(task.rogue_rest_settled())
            self.assertIs(task.rest_wait, wait)
        wait._start -= REST_WAIT + 1
        self.assertTrue(task.rogue_rest_settled())

    def test_store_only_previews_remaining_target_types(self):
        rules = '亡魂之花 = 1号位\n非典型方塊 = 1号位\n黑曜石劍 = 1号位'
        task, equipment = make_task('store_mixed', rules)
        for _ in range(3):
            self.assertTrue(equipment.handle_shop(Mock()))
        self.assertEqual([call[0] for call in task.tap_point.call_args_list],
                         [(390, 390), (890, 390), (1140, 390)])
        equipment.record_equipped_target(equipment.library.lookup('亡魂之花'))
        self.assertEqual(equipment.shop_equipment_slots(equipment.shop_target_slots()), [1, 4])
        task.device.image = frame('store')
        self.assertEqual(equipment.shop_equipment_slots(equipment.shop_target_slots()), [])

    def test_free_refresh_rechecks_new_stock_and_stops_when_free_label_disappears(self):
        task, equipment = make_task('store', '突擊靴 = 米卡')
        equipment.shop_free_refresh_count = Mock(return_value=2)
        equipment.shop_context = (task.core_started, task.route_step)
        equipment.shop_seen = {0, 1}
        equipment.handle_shop(Mock())
        equipment.shop_free_refresh_count.return_value = 1
        equipment.handle_shop(Mock())
        task.tap_point.assert_called_with(140, 390, name='ROGUE_SHOP_EQUIPMENT')
        equipment.handle_shop(Mock())
        task.tap_point.assert_called_with(390, 390, name='ROGUE_SHOP_EQUIPMENT')
        equipment.handle_shop(Mock())
        task.tap_point.assert_called_with(100, 672, name='ROGUE_SHOP_REFRESH_FREE')
        task.device.image = frame('store_paid')
        equipment.handle_shop(Mock())
        equipment.handle_shop(Mock())
        self.assertFalse(equipment.handle_shop(Mock()))
        refreshes = [call for call in task.tap_point.call_args_list
                     if call[1]['name'] == 'ROGUE_SHOP_REFRESH_FREE']
        self.assertEqual(len(refreshes), 2)

    def test_free_count_parser_rejects_invalid_or_partial_numbers(self):
        _, equipment = make_task('store')
        for text in ('', '4/3', '3/0', '123', '2junk'):
            with patch('module.chaoszero.rogue_equipment.SHOP_FREE_REFRESH_COUNT.ocr', return_value=text):
                self.assertIsNone(equipment.shop_free_refresh_count(), text)
        with patch('module.chaoszero.rogue_equipment.SHOP_FREE_REFRESH_COUNT.ocr', return_value='0'):
            self.assertEqual(equipment.shop_free_refresh_count(), 0)

    def test_no_refresh_when_free_is_not_visible_or_quota_is_zero(self):
        for label, count in (('', 2), ('付費', 2), ('免費', 0)):
            task, equipment = make_task('store', '調節時間器 = 米卡')
            equipment.shop_context = (task.core_started, task.route_step)
            equipment.shop_seen = {0, 1}
            equipment.reader.read_name = Mock(return_value=label)
            equipment.shop_free_refresh_count = Mock(return_value=count)
            self.assertFalse(equipment.handle_shop(Mock()))
            task.tap_point.assert_not_called()

    def test_free_refresh_with_unreadable_count_stops_without_clicking(self):
        task, equipment = make_task('store', '調節時間器 = 米卡')
        equipment.shop_context = (task.core_started, task.route_step)
        equipment.shop_seen = {0, 1}
        equipment.shop_free_refresh_count = Mock(return_value=None)
        with self.assertRaises(TaskFailed):
            equipment.handle_shop(Mock())
        task.tap_point.assert_not_called()
        task.rogue_dump_unknown.assert_called_once()

    def test_zero_free_count_never_refreshes_even_if_free_label_remains(self):
        task, equipment = make_task('store', '調節時間器 = 米卡')
        equipment.shop_context = (task.core_started, task.route_step)
        equipment.shop_seen = {0, 1}
        with patch('module.chaoszero.rogue_equipment.SHOP_FREE_REFRESH_COUNT.ocr', return_value='0'):
            self.assertFalse(equipment.handle_shop(Mock()))
        task.tap_point.assert_not_called()

    def test_unreadable_or_impossible_free_count_never_refreshes(self):
        for text in ('', 'unknown', '2x'):
            task, equipment = make_task('store', '調節時間器 = 米卡')
            equipment.shop_context = (task.core_started, task.route_step)
            equipment.shop_seen = {0, 1}
            with patch('module.chaoszero.rogue_equipment.SHOP_FREE_REFRESH_COUNT.ocr', return_value=text):
                with self.assertRaises(TaskFailed):
                    equipment.handle_shop(Mock())
            task.tap_point.assert_not_called()

    def test_unconfirmed_refresh_holds_stock_and_times_out_without_another_click(self):
        task, equipment = make_task('store', '調節時間器 = 米卡')
        equipment.shop_context = (task.core_started, task.route_step)
        equipment.shop_seen = {0, 1}
        equipment.shop_free_refresh_count = Mock(return_value=2)
        equipment.handle_shop(Mock())
        equipment.handle_shop(Mock())
        self.assertEqual(equipment.shop_seen, {0, 1})
        equipment.shop_refresh = (2, Mock())
        with self.assertRaises(TaskFailed):
            equipment.handle_shop(Mock())
        self.assertEqual(task.tap_point.call_count, 1)

    def test_missing_free_label_does_not_imply_paid_state_or_refresh_success(self):
        task, equipment = make_task('store', '黑曜石劍 = 海德瑪麗')
        equipment.shop_context = (task.core_started, task.route_step)
        equipment.shop_seen = {0, 1}
        equipment.handle_shop(Mock())
        task.device.image[640:710, 150:440] = 0
        self.assertTrue(equipment.handle_shop(Mock()))
        self.assertEqual(equipment.shop_seen, {0, 1})
        self.assertEqual(task.tap_point.call_count, 1)
        equipment.shop_refresh = (2, Mock())
        with self.assertRaises(TaskFailed):
            equipment.handle_shop(Mock())
        self.assertEqual(task.tap_point.call_count, 1)

    def test_refresh_cooldown_and_next_node_reset(self):
        task, equipment = make_task('store', '突擊靴 = 米卡')
        equipment.shop_context = (task.core_started, task.route_step)
        equipment.shop_seen = {0, 1}
        press = Mock()
        press.reached.return_value = False
        self.assertTrue(equipment.handle_shop(press))
        task.tap_point.assert_not_called()
        equipment.shop_refresh = (2, Mock())
        task.route_step += 1
        self.assertTrue(equipment.handle_shop(Mock()))
        self.assertIsNone(equipment.shop_refresh)
        self.assertEqual(equipment.shop_seen, {0})

    def test_refresh_transition_is_held_before_generic_handlers(self):
        task, equipment = make_task('store', '調節時間器 = 米卡')
        timer = Mock()
        timer.reached.return_value = False
        equipment.shop_refresh = (2, timer)
        task.device.image[:] = 0
        self.assertTrue(equipment.handle(Mock()))
        task.tap_point.assert_not_called()
        timer.reached.return_value = True
        with self.assertRaises(TaskFailed):
            equipment.handle(Mock())

    def test_unknown_shop_preview_is_held_then_stops_without_generic_clicks(self):
        task, equipment = make_task('store', '突擊靴 = 米卡')
        equipment.handle_shop(Mock())
        task.tap_point.assert_called_once_with(140, 390, name='ROGUE_SHOP_EQUIPMENT')
        task.device.image[:] = 0
        self.assertTrue(equipment.handle(Mock()))
        equipment.shop_opening = Mock()
        with self.assertRaises(TaskFailed):
            equipment.handle(Mock())
        self.assertEqual(task.tap_point.call_count, 1)


if __name__ == '__main__':
    unittest.main()
