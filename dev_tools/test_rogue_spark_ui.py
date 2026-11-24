# -*- coding: utf-8 -*-
"""Unit tests for ChaoszeroRogue per-slot character and spark-form WebUI helpers."""

import queue
import unittest
from unittest.mock import MagicMock, patch

from module.chaoszero import rogue_spark_catalog as rogue_cards
from module.webui import app as webui_app
from module.webui.fake_pil_module import remove_fake_pil_module

remove_fake_pil_module()


class RogueSparkCatalogTest(unittest.TestCase):
    def test_catalog_covers_all_40_characters_with_four_spark_cards_each(self):
        chars, by_char = rogue_cards.spark_catalog()
        self.assertEqual(len(chars), 40)
        self.assertEqual(len(by_char), 40)
        for entry in chars:
            cards = by_char[entry['id']]
            self.assertEqual(len(cards), 4)
            for card in cards:
                self.assertEqual([f['index'] for f in card['forms']], [1, 2, 3, 4, 5])
        blaze = {c['name']: c for c in by_char['custom_blazebel']}
        self.assertEqual(set(blaze), {'飄散的火花', '火焰之觸', '芙蕾雅的祝福', '共鳴的火花'})
        self.assertEqual(blaze['飄散的火花']['cost'], 0)
        self.assertEqual(blaze['飄散的火花']['category'], 'CARD_SKILL')
        self.assertNotIn('此卡牌費用減少1', rogue_cards.god_spark_options(blaze['飄散的火花']))
        self.assertIn('獲得AP1', rogue_cards.god_spark_options(blaze['飄散的火花']))
        self.assertIn('常態弱點攻擊', rogue_cards.god_spark_options(blaze['火焰之觸']))
        self.assertIn('此卡牌費用減少1', rogue_cards.god_spark_options(blaze['火焰之觸']))
        self.assertIn('此卡牌費用減少1', rogue_cards.god_spark_options(blaze['共鳴的火花']))

    def test_character_name_localization(self):
        entry = {'id': '1003', 'names': {'en': 'Nia', 'zhs': '妮雅简', 'zht': '妮雅繁'}}
        self.assertEqual(rogue_cards.character_name(entry, 'zh-CN'), '妮雅简')
        self.assertEqual(rogue_cards.character_name(entry, 'zh-TW'), '妮雅繁')
        self.assertEqual(rogue_cards.character_name(entry, 'en-US'), 'Nia')

    def test_parse_and_update_spark_filter_preserves_other_rules(self):
        source = '# keep comment\nG和弦 = 3\n劍之雨 = 2\n喘氣 = 上膛,痛苦\n'
        parsed = rogue_cards.parse_spark_filter(source)
        self.assertEqual(parsed, {'G和弦': '3', '劍之雨': '2', '喘氣': '上膛,痛苦'})

        updated = rogue_cards.update_spark_filter(source, 'G和弦', '5')
        self.assertIn('# keep comment', updated)
        self.assertIn('G和弦 = 5', updated)
        self.assertIn('劍之雨 = 2', updated)
        self.assertIn('喘氣 = 上膛,痛苦', updated)

        removed = rogue_cards.update_spark_filter(updated, 'G和弦', '')
        self.assertNotIn('G和弦', removed)
        self.assertIn('劍之雨 = 2', removed)

        added = rogue_cards.update_spark_filter(removed, '慢板', '4')
        self.assertTrue(added.endswith('慢板 = 4'))

        normalized = rogue_cards.update_spark_filter('劍 之 雨 = 1', '劍之雨', '4')
        self.assertEqual(normalized, '劍之雨 = 4')

    def test_deck_catalog_and_delete_filter_helpers(self):
        deck = rogue_cards.deck_catalog()
        self.assertEqual(len(deck), 40)
        blaze = {c['name']: c for c in deck['custom_blazebel']}
        self.assertEqual(blaze['紅色火焰']['kind'], 'basic')
        self.assertEqual(blaze['蔚藍火焰']['count'], 2)
        self.assertEqual(blaze['蔚藍火焰']['kind'], 'basic')
        self.assertEqual(blaze['飄散的火花']['kind'], 'spark')
        self.assertEqual(blaze['火花的殘影']['kind'], 'unique')
        heidi = {c['name']: c for c in deck['30093']}
        self.assertEqual(heidi['劍光']['count'], 2)
        self.assertEqual(heidi['劍光']['kind'], 'basic')
        self.assertEqual(heidi['劍幕']['count'], 1)
        self.assertEqual(heidi['劍之雨']['kind'], 'spark')
        self.assertEqual(heidi['凝結極光']['kind'], 'unique')

        parsed = rogue_cards.parse_delete_filter('# comment\n劍幕 = 1\n劍光 = 2\n無效 = 0\n')
        self.assertEqual(parsed, [('劍幕', 1), ('劍光', 2)])
        updated = rogue_cards.update_delete_filter('劍幕 = 1\n劍光 = 2', '劍光', 1)
        self.assertEqual(updated, '劍幕 = 1\n劍光 = 1')
        removed = rogue_cards.update_delete_filter(updated, '劍幕', 0)
        self.assertEqual(removed, '劍光 = 1')

        # 30093 = 劍光, 1039 = 水護盾
        ordered = rogue_cards.prioritize_delete_rules(
            [('劍光', 2), ('水護盾', 1)],
            ['30093', '1039', ''],
            preferred_slot=2,
        )
        self.assertEqual(ordered, [('水護盾', 1), ('劍光', 2)])


class FakePin(dict):
    def __getitem__(self, key):
        return self.get(key)


class RogueSparkWebUITest(unittest.TestCase):
    def _make_gui(self):
        gui = webui_app.AlasGUI.__new__(webui_app.AlasGUI)
        gui.alas_name = 'template'
        gui.alas_config = MagicMock()
        gui.alas_config.read_file.return_value = {
            'ChaoszeroRogue': {
                'ChaoszeroRogue': {
                    'RogueSlot1Member': '',
                    'RogueSlot2Member': '',
                    'RogueSlot3Member': '',
                    'RogueSparkFilter': '',
                }
            }
        }
        gui.modified_config_queue = queue.Queue()
        gui._rogue_spark_active = True
        gui._rogue_hidden_values = {'RogueSparkFilter': '', 'RogueDeleteFilter': ''}
        return gui

    def test_character_options_include_unselected_and_all_characters(self):
        with patch.object(webui_app, 'pin', FakePin()), \
                patch.object(webui_app.lang, 'LANG', 'zh-CN'), \
                patch.object(webui_app, 't', side_effect=lambda k, *_: k):
            options, labels = webui_app.AlasGUI._rogue_character_options()
        self.assertEqual(options[0], '')
        self.assertEqual(labels[0], 'Gui.Rogue.Unselected')
        self.assertEqual(len(options), 41)
        self.assertEqual(len(labels), 41)
        self.assertIn('custom_blazebel', options)

    def test_render_empty_slots_shows_empty_hint(self):
        gui = self._make_gui()
        fake_pin = FakePin()
        texts = []

        def fake_text(val):
            texts.append(val)
            m = MagicMock()
            m.style.return_value = m
            return m

        with patch.object(webui_app, 'pin', fake_pin), \
                patch.object(webui_app, 't', side_effect=lambda k, *_: k), \
                patch.object(webui_app, 'use_scope'), \
                patch.object(webui_app, 'put_text', side_effect=fake_text), \
                patch.object(webui_app, 'put_arg_select') as mock_select, \
                patch.object(webui_app, 'pin_on_change'):
            gui._render_rogue_spark_picker()

        self.assertIn('Gui.Rogue.SparkPickerEmpty', texts)
        mock_select.assert_called_once()
        target = mock_select.call_args[0][0]
        self.assertEqual(target['options'], [''])
        self.assertEqual(target['value'], '')

    def test_render_selected_slots_and_sync_card_change(self):
        gui = self._make_gui()
        gui._rogue_hidden_values['RogueSparkFilter'] = 'G和弦 = 3\n慢板 = 自訂關鍵詞\n劍之雨 = 2'
        gui._rogue_hidden_values['RogueDeleteFilter'] = '增幅治療 = 2'
        fake_pin = FakePin({
            'ChaoszeroRogue_ChaoszeroRogue_RogueSlot1Member': '1003',
            'ChaoszeroRogue_ChaoszeroRogue_RogueSlot2Member': '1004',
            'ChaoszeroRogue_ChaoszeroRogue_RogueSlot3Member': '1003',
        })
        rendered = []

        def fake_arg_select(kwargs):
            rendered.append(kwargs)
            return MagicMock()

        def fake_text(val):
            m = MagicMock()
            m.style.return_value = m
            return m

        with patch.object(webui_app, 'pin', fake_pin), \
                patch.object(webui_app.lang, 'LANG', 'zh-CN'), \
                patch.object(webui_app, 't', side_effect=lambda k, *_, **__: k), \
                patch.object(webui_app, 'use_scope'), \
                patch.object(webui_app, 'put_text', side_effect=fake_text), \
                patch.object(webui_app, 'put_arg_select', side_effect=fake_arg_select), \
                patch.object(webui_app, 'pin_on_change') as mock_watch:
            gui._render_rogue_pickers()
            # Spark picker: 4 cards for 1003 + 4 cards for 1004 = 8;
            # Remove picker: 7 distinct cards for 1003 + 7 for 1004 = 14. Total = 22.
            spark_items = [item for item in rendered if item['name'].startswith('rogue_spark_card_')]
            remove_items = [item for item in rendered if item['name'].startswith('rogue_remove_card_')]
            self.assertEqual(len(spark_items), 8)
            self.assertEqual(len(remove_items), 14)

            spark_by_title = {item['title']: item for item in spark_items}
            self.assertEqual(spark_by_title['G和弦']['value'], '3')
            self.assertEqual(spark_by_title['慢板']['value'], webui_app.ROGUE_SPARK_CUSTOM_OPTION)
            self.assertEqual(spark_by_title['連續擊發']['value'], '')

            remove_by_title = {item['title']: item for item in remove_items}
            self.assertEqual(remove_by_title['增幅治療']['value'], '2')
            self.assertEqual(remove_by_title['增幅治療']['options'], ['0', '1', '2'])
            self.assertEqual(remove_by_title['掃弦']['options'], ['0', '1'])
            self.assertEqual(mock_watch.call_count, 31)
            for call in mock_watch.call_args_list:
                self.assertTrue(call[1].get('clear'))

            rendered.clear()
            gui._on_rogue_spark_card_change('連續擊發', '4')
            gui._on_rogue_remove_card_change('掃弦', '1')

        saved_spark = gui._rogue_hidden_values['RogueSparkFilter']
        self.assertIn('連續擊發 = 4', saved_spark)
        self.assertIn('劍之雨 = 2', saved_spark)
        self.assertIn('慢板 = 自訂關鍵詞', saved_spark)
        saved_delete = gui._rogue_hidden_values['RogueDeleteFilter']
        self.assertIn('增幅治療 = 2', saved_delete)
        self.assertIn('掃弦 = 1', saved_delete)

        q1 = gui.modified_config_queue.get_nowait()
        q2 = gui.modified_config_queue.get_nowait()
        self.assertEqual(q1['name'], 'ChaoszeroRogue.ChaoszeroRogue.RogueSparkFilter')
        self.assertEqual(q1['value'], saved_spark)
        self.assertEqual(q2['name'], 'ChaoszeroRogue.ChaoszeroRogue.RogueDeleteFilter')
        self.assertEqual(q2['value'], saved_delete)

    def test_god_spark_catalog_and_ordered_filter_helpers(self):
        _, by_char = rogue_cards.spark_catalog()
        rain = next(c for c in by_char['30093'] if c['name'] == '劍之雨')
        opts = rogue_cards.god_spark_options(rain)
        self.assertEqual(len(opts), 28)
        self.assertGreater(opts.index('此卡牌費用減少1'), opts.index('獲得AP1'))
        self.assertGreater(opts.index('常態弱點攻擊'), opts.index('此卡牌費用減少1'))
        self.assertGreater(opts.index('賦予此卡牌開戰'), opts.index('抽取1'))
        self.assertNotIn('費用變更為0', opts)
        self.assertNotIn('賦予目標脆弱3', opts)

        rsp1_entries = rogue_cards.god_spark_option_entries(rain, '1')
        self.assertEqual(len(rsp1_entries), 21)
        self.assertEqual(sum(not e['is_sortie'] for e in rsp1_entries), 9)
        self.assertEqual(sum(e['is_sortie'] for e in rsp1_entries), 12)
        self.assertEqual(
            [e['is_sortie'] for e in rsp1_entries],
            sorted(e['is_sortie'] for e in rsp1_entries),
        )
        ap_entry = next(e for e in rsp1_entries if e['desc'] == '獲得AP1')
        self.assertEqual(ap_entry, {'desc': '獲得AP1', 'is_sortie': False, 'god_name': ''})
        kai_entry = next(e for e in rsp1_entries if e['desc'] == '賦予此卡牌開戰')
        self.assertEqual(kai_entry, {'desc': '賦予此卡牌開戰', 'is_sortie': True, 'god_name': '維托'})
        self.assertIn('常態弱點攻擊', rogue_cards.god_spark_options(rain, '1'))
        self.assertNotIn('常態弱點攻擊', rogue_cards.god_spark_options(rain, '3'))

        launch = next(c for c in by_char['1033'] if c['name'] == '準備發射')
        self.assertNotIn('常態弱點攻擊', rogue_cards.god_spark_options(launch))

        parsed = rogue_cards.parse_god_spark_filter(
            '劍之雨 = 獲得AP1 > 此卡牌費用減少1 > 獲得AP1\n喘氣 = 抽取1, 獲得AP1'
        )
        self.assertEqual(parsed, {'劍之雨': ['獲得AP1', '此卡牌費用減少1'], '喘氣': ['抽取1', '獲得AP1']})
        updated = rogue_cards.update_god_spark_filter('', '劍之雨', ['獲得AP1', '此卡牌費用減少1'])
        self.assertEqual(updated, '劍之雨 = 獲得AP1 > 此卡牌費用減少1')
        self.assertEqual(rogue_cards.update_god_spark_filter(updated, '劍之雨', []), '')

    def test_god_spark_webui_multiselect_reorder_and_clear(self):
        gui = self._make_gui()
        fake_pin = FakePin({'ChaoszeroRogue_ChaoszeroRogue_RogueSlot1Member': '1003'})
        btn_groups = []
        selects = []

        def fake_buttons(buttons=None, **_kwargs):
            btn_groups.append(buttons)

        def fake_select(kw):
            selects.append(kw)
            return MagicMock()

        with patch.object(webui_app, 'pin', fake_pin), \
                patch.object(webui_app.lang, 'LANG', 'zh-CN'), \
                patch.object(webui_app, 't', side_effect=lambda k, *_, **__: k), \
                patch.object(webui_app, 'use_scope'), \
                patch.object(webui_app, 'put_text'), \
                patch.object(webui_app, 'put_arg_select', side_effect=fake_select), \
                patch.object(webui_app, 'put_buttons', side_effect=fake_buttons), \
                patch.object(webui_app, 'pin_on_change'):
            gui._on_rogue_god_spark_add('G和弦', '獲得AP1')
            g_god_select = next(
                kw for kw in reversed(selects)
                if kw.get('title') == 'G和弦 · Gui.Rogue.GodSparkTitle'
            )
            self.assertIn('賦予此卡牌開戰', g_god_select['options'])
            kai_idx = g_god_select['options'].index('賦予此卡牌開戰')
            self.assertEqual(g_god_select['options_label'][kai_idx], '賦予此卡牌開戰 (維托 · 出擊)')

            gui._on_rogue_god_spark_add('G和弦', '此卡牌費用減少1')
            self.assertEqual(
                gui._rogue_hidden_values['RogueGodSparkFilter'],
                'G和弦 = 獲得AP1 > 此卡牌費用減少1',
            )
            values = [b['value'] for b in btn_groups[-1]]
            self.assertEqual(values, ['del:0', 'up:1', 'del:1', 'clear'])

            gui._on_rogue_god_spark_action('G和弦', 'up:1')
            self.assertEqual(
                gui._rogue_hidden_values['RogueGodSparkFilter'],
                'G和弦 = 此卡牌費用減少1 > 獲得AP1',
            )
            gui._on_rogue_god_spark_action('G和弦', 'del:0')
            self.assertEqual(gui._rogue_hidden_values['RogueGodSparkFilter'], 'G和弦 = 獲得AP1')
            gui._on_rogue_god_spark_action('G和弦', 'clear')
            self.assertEqual(gui._rogue_hidden_values['RogueGodSparkFilter'], '')
            last_msg = None
            while not gui.modified_config_queue.empty():
                last_msg = gui.modified_config_queue.get_nowait()
            self.assertEqual(last_msg, {'name': 'ChaoszeroRogue.ChaoszeroRogue.RogueGodSparkFilter', 'value': ''})

    def test_spark_check_picker_saves_one_card_and_refreshes_valid_targets(self):
        gui = self._make_gui()
        gui._rogue_hidden_values['RogueSparkFilter'] = 'G和弦 = 3\n慢板 = 自訂關鍵詞\n劍之雨 = 2'
        slot_pin = 'ChaoszeroRogue_ChaoszeroRogue_RogueSlot1Member'
        fake_pin = FakePin({slot_pin: '1003'})

        with patch.object(webui_app, 'pin', fake_pin), \
                patch.object(webui_app, 't', side_effect=lambda k, *_: k), \
                patch.object(webui_app, 'use_scope'), \
                patch.object(webui_app, 'put_text'), \
                patch.object(webui_app, 'put_arg_select') as select, \
                patch.object(webui_app, 'pin_on_change') as watch:
            gui._render_rogue_spark_picker()
            target = select.call_args[0][0]
            self.assertEqual(target['name'], 'rogue_spark_check_card')
            self.assertCountEqual(target['options'], ['', 'G和弦', '慢板'])
            self.assertEqual(target['value'], '')
            self.assertIn('③', target['options_label'][target['options'].index('G和弦')])
            watch.call_args[1]['onchange']('G和弦')
            self.assertEqual(gui.modified_config_queue.get_nowait(), {
                'name': 'ChaoszeroRogue.ChaoszeroRogue.RogueSparkCheckCard',
                'value': 'G和弦',
            })
            gui._render_rogue_spark_picker()
            self.assertEqual(select.call_args[0][0]['value'], 'G和弦')
            gui._on_rogue_spark_card_change('G和弦', '')
            self.assertNotIn('G和弦', select.call_args[0][0]['options'])
            self.assertEqual(select.call_args[0][0]['value'], '')
            fake_pin[slot_pin] = '30093'
            gui._render_rogue_spark_picker()
            self.assertEqual(select.call_args[0][0]['options'], ['', '劍之雨'])
            self.assertEqual(select.call_args[0][0]['value'], '')

    def test_remove_priority_reorders_slots_and_watcher_uses_clear(self):
        gui = self._make_gui()
        gui.ALAS_ARGS = {
            'ChaoszeroRogue': {
                'ChaoszeroRogue': {
                    'RogueSlot1Member': {},
                    'RogueRemoveMember': {},
                }
            }
        }
        texts = []
        rendered_names = []

        def fake_text(val):
            texts.append(val)
            m = MagicMock()
            m.style.return_value = m
            return m

        with patch.object(webui_app, 'pin_on_change') as mock_init_watch:
            gui._init_alas_config_watcher()
            self.assertEqual(mock_init_watch.call_count, 2)
            for call in mock_init_watch.call_args_list:
                self.assertTrue(call[1].get('clear'))
            callbacks = {c[1]['name']: c[1]['onchange'] for c in mock_init_watch.call_args_list}

        with patch.object(webui_app, 'pin', FakePin()), \
                patch.object(webui_app.lang, 'LANG', 'zh-CN'), \
                patch.object(webui_app, 't', side_effect=lambda k, *_, **__: k), \
                patch.object(webui_app, 'use_scope'), \
                patch.object(webui_app, 'put_text', side_effect=fake_text), \
                patch.object(webui_app, 'put_arg_select', side_effect=lambda kw: (rendered_names.append(kw['name']), MagicMock())[1]), \
                patch.object(webui_app, 'pin_on_change'):
            callbacks['ChaoszeroRogue_ChaoszeroRogue_RogueSlot1Member']('1003')
            gui._rogue_hidden_values['RogueSlot2Member'] = '1039'
            texts.clear()
            rendered_names.clear()
            callbacks['ChaoszeroRogue_ChaoszeroRogue_RogueRemoveMember'](2)

        slot_headers = [line for line in texts if 'Gui.Rogue.Slot' in line]
        self.assertEqual(len(slot_headers), 2)
        self.assertIn('Gui.Rogue.PriorityTag', slot_headers[0])
        self.assertIn('Gui.Rogue.Slot2', slot_headers[0])
        self.assertTrue(any(name.startswith('rogue_remove_card_') for name in rendered_names))
        self.assertFalse(any(name.startswith('rogue_spark_card_') for name in rendered_names))

    def test_neutral_spark_option_and_alias(self):
        gui = self._make_gui()
        gui._rogue_hidden_values['RogueSparkFilter'] = 'G和弦 = 中立'
        fake_pin = FakePin({'ChaoszeroRogue_ChaoszeroRogue_RogueSlot1Member': '1003'})
        rendered = []

        def fake_select(kw):
            rendered.append(kw)
            return MagicMock()

        with patch.object(webui_app, 'pin', fake_pin), \
                patch.object(webui_app.lang, 'LANG', 'zh-CN'), \
                patch.object(webui_app, 't', side_effect=lambda k, *_, **__: k), \
                patch.object(webui_app, 'use_scope'), \
                patch.object(webui_app, 'put_text'), \
                patch.object(webui_app, 'put_arg_select', side_effect=fake_select), \
                patch.object(webui_app, 'pin_on_change'):
            gui._render_rogue_spark_picker()
            spark_by_title = {
                item['title']: item
                for item in rendered if item['name'].startswith('rogue_spark_card_')
            }
            self.assertIn('6', spark_by_title['G和弦']['options'])
            self.assertIn('⑥ Gui.Rogue.SparkFormNeutral', spark_by_title['G和弦']['options_label'])
            self.assertEqual(spark_by_title['G和弦']['value'], '6')
            target_picker = next(item for item in rendered if item['name'] == 'rogue_spark_check_card')
            self.assertIn('G和弦', target_picker['options'])

            rendered.clear()
            gui._on_rogue_spark_card_change('慢板', '6')
            self.assertIn('慢板 = 6', gui._rogue_hidden_values['RogueSparkFilter'])
            spark_by_title = {
                item['title']: item
                for item in rendered if item['name'].startswith('rogue_spark_card_')
            }
            self.assertEqual(spark_by_title['慢板']['value'], '6')

    def test_set_group_deduplicates_shared_rogue_spark_picker_scope(self):
        gui = self._make_gui()
        gui._rogue_spark_active = False
        gui._render_rogue_pickers = MagicMock()
        settings = {
            'RogueSparkFilter': {'type': 'textarea', 'value': '劍之雨 = 2'},
            'RogueGodSparkFilter': {'type': 'textarea', 'value': '劍之雨 = 獲得AP1'},
            'RogueSparkCheckCard': {'type': 'select', 'value': '', 'option': ['']},
            'RogueDeleteFilter': {'type': 'textarea', 'value': ''},
        }
        config = {'ChaoszeroRogue': {'ChaoszeroRogue': {
            'RogueSparkFilter': '劍之雨 = 3',
            'RogueGodSparkFilter': '劍之雨 = 此卡牌費用減少1',
        }}}
        created_scopes = []

        def fake_put_scope(name, *_, **__):
            created_scopes.append(name)
            m = MagicMock()
            m.spec = {}
            return m

        with patch.object(webui_app, 'use_scope'), \
                patch.object(webui_app, 'put_scope', side_effect=fake_put_scope), \
                patch.object(webui_app, 'put_text'), \
                patch.object(webui_app, 'put_html'), \
                patch.object(webui_app, 't', side_effect=lambda k, *_, **__: k):
            gui.set_group(('ChaoszeroRogue',), settings, config, 'ChaoszeroRogue', section='Build')

        self.assertEqual(created_scopes, ['rogue_spark_picker', 'rogue_spark_check_picker', 'rogue_remove_picker'])
        self.assertEqual(gui._rogue_hidden_values['RogueSparkFilter'], '劍之雨 = 3')
        self.assertEqual(gui._rogue_hidden_values['RogueGodSparkFilter'], '劍之雨 = 此卡牌費用減少1')


if __name__ == '__main__':
    unittest.main()
