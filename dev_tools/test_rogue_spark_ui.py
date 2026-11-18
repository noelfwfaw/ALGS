# -*- coding: utf-8 -*-
"""Unit tests for ChaoszeroRogue per-slot character and spark-form WebUI helpers."""

import queue
import unittest
from unittest.mock import MagicMock, patch

from module.chaoszero import rogue_spark_catalog as rogue_cards
from module.webui import app as webui_app


class RogueSparkCatalogTest(unittest.TestCase):
    def test_catalog_covers_all_39_characters_with_four_spark_cards_each(self):
        chars, by_char = rogue_cards.spark_catalog()
        self.assertEqual(len(chars), 39)
        self.assertEqual(len(by_char), 39)
        for entry in chars:
            cards = by_char[entry['id']]
            self.assertEqual(len(cards), 4)
            for card in cards:
                self.assertEqual([f['index'] for f in card['forms']], [1, 2, 3, 4, 5])

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
        self.assertEqual(len(deck), 39)
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
        self.assertEqual(len(options), 40)
        self.assertEqual(len(labels), 40)

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
                patch.object(webui_app, 'put_arg_select') as mock_select:
            gui._render_rogue_spark_picker()

        self.assertIn('Gui.Rogue.SparkPickerEmpty', texts)
        mock_select.assert_not_called()

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
            self.assertEqual(mock_watch.call_count, 22)
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


if __name__ == '__main__':
    unittest.main()
