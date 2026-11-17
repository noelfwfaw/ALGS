"""Event classifications come from the source, not from flattened option counts."""
import json
import gzip
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from dev_tools import gen_chaoszero_rogue_db as generator
from dev_tools import gen_chaoszero_rogue_db_inline as inline
from dev_tools.gen_chaoszero_rogue_db import parse_option, parse_encounter
from dev_tools.gen_chaoszero_rogue_db_inline import classify_selector


class EventDataTest(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).parent / 'fixtures' / 'chaoszero' / 'rogue_residue.json'
        self.raw = json.loads(source.read_text(encoding='utf-8'))

    def test_residue_has_three_visible_choices_and_separate_attack(self):
        record = parse_encounter(self.raw)
        self.assertEqual((record['option_count'], record['option_count_max']), (3, 3))
        self.assertEqual(len(record['options']), 5)
        self.assertEqual([o['select_type'] for o in record['options']],
                         ['RANDOM', 'DEFAULT', 'DEFAULT', 'RANDOM', 'ATTACK'])
        flower, _, _, comfort, attack = record['options']
        self.assertEqual(flower['appear_conditions'], ['cn_have_equ_nih_01'])
        self.assertEqual(comfort['appear_conditions'], ['!cn_have_equ_nih_01'])
        self.assertEqual(attack['option_type'], 'ATTACK')
        self.assertEqual(attack['order'], 9999)
        self.assertEqual(attack['flavor'], '')
        self.assertEqual(flower['id'], 'uk_904_s01_06b_s1')
        self.assertEqual(flower['exclusive_with'], [comfort['id']])
        self.assertEqual(comfort['exclusive_with'], [flower['id']])
        self.assertEqual(attack['exclusive_with'], [])

    def test_condition_fields_do_not_lose_expressions_or_selection_limits(self):
        raw = dict(self.raw['options'][1], select_type='RANDOM_1',
                   appear_link_encounter_trigger_id=['a&!b', '!link@previous'],
                   select_link_encounter_trigger_id=['can_pay'],
                   select_link_nb_condition_id=['condition_1'],
                   select_link_nb_conditions=[{'encounter_option_tooltip': '需要信用點'}])
        option = parse_option(raw)
        self.assertEqual(option['select_type'], 'RANDOM_1')
        self.assertEqual(option['appear_conditions'], ['a&!b', '!link@previous'])
        self.assertEqual(option['select_conditions'], ['can_pay'])
        self.assertEqual(option['condition_ids'], ['condition_1'])
        self.assertEqual(option['conditions'], ['需要信用點'])
        self.assertEqual(option['order'], 2)

    def test_complex_conditions_are_preserved_without_guessing_exclusive_groups(self):
        self.raw['options'][0]['appear_link_encounter_trigger_id'] = ['a&!b']
        self.raw['options'][3]['appear_link_encounter_trigger_id'] = ['!a&b']
        record = parse_encounter(self.raw)
        self.assertEqual(record['options'][0]['exclusive_with'], [])
        self.assertEqual(record['options'][3]['exclusive_with'], [])

    def test_selector_classifies_nested_nodes_and_labels_attack_without_reordering(self):
        node = {'id': self.raw['id'], 'options': [
            {'order': o['order'], 'text': o['simple_flavor_text']}
            for o in self.raw['options']]}
        nested = json.loads(json.dumps(node))
        root = {'id': 'other', 'options': [{'nextDetail': node}, {'next': nested}]}
        classify_selector(root, {self.raw['id']: self.raw})
        for record in (node, nested):
            self.assertEqual(record['option_count_max'], 3)
            self.assertEqual(record['options'][0]['select_type'], 'RANDOM')
            self.assertEqual(record['options'][3]['appear_conditions'], ['!cn_have_equ_nih_01'])
            self.assertEqual(record['options'][-1]['text'], '攻击')
            self.assertEqual([o['order'] for o in record['options']], [1, 2, 3, 4, 9999])

    def test_selector_rejects_changed_option_order_instead_of_mislabeling(self):
        node = {'id': self.raw['id'], 'options': [{'order': 3}]}
        with self.assertRaises(ValueError):
            classify_selector(node, {self.raw['id']: self.raw})

    def test_truncated_recursive_selector_link_stays_unexpanded(self):
        node = {'id': self.raw['id'], 'options': []}
        classify_selector(node, {self.raw['id']: self.raw})
        self.assertEqual(node, {'id': self.raw['id'], 'options': []})

    def test_old_flattened_cache_fetches_missing_source_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            output = str(Path(directory) / 'events.json.gz')
            with gzip.open(output, 'wt', encoding='utf-8') as handle:
                json.dump({self.raw['id']: {'name': '殘留物', 'options': [{'order': 1}]}}, handle)
            with patch.object(generator, 'OUTPUT', output), redirect_stdout(io.StringIO()):
                with patch.object(generator, 'get', side_effect=[{'data': [self.raw]},
                                                                 {'data': self.raw}]) as get:
                    generator.main()
            self.assertEqual(get.call_args_list[-1][0], ('/encounters/' + self.raw['id'],))
            with gzip.open(output, 'rt', encoding='utf-8') as handle:
                record = json.load(handle)[self.raw['id']]
            self.assertEqual(record['options'][0]['select_type'], 'RANDOM')

    def test_classified_cache_does_not_need_a_detail_request(self):
        with tempfile.TemporaryDirectory() as directory:
            output = str(Path(directory) / 'events.json.gz')
            with gzip.open(output, 'wt', encoding='utf-8') as handle:
                json.dump({self.raw['id']: parse_encounter(self.raw)}, handle)
            with patch.object(generator, 'OUTPUT', output), redirect_stdout(io.StringIO()):
                with patch.object(generator, 'get', return_value={'data': [self.raw]}) as get:
                    generator.main()
            get.assert_called_once_with('/encounters/list')

    def test_inline_stub_cannot_erase_a_populated_event(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.json'
            stub = {'id': self.raw['id'], 'options': None}
            parent = {'id': 'parent', 'options': [
                {'success_link_encounter_option_eff': {'next_encounter': stub}}]}
            source.write_text(json.dumps({'parent': parent, self.raw['id']: self.raw}), encoding='utf-8')
            output = str(root / 'events.json.gz')
            with patch.object(inline, 'ROOT', directory), patch.object(inline, 'OUTPUT', output), \
                    patch('sys.argv', ['test', '--source', str(source)]), redirect_stdout(io.StringIO()):
                self.assertEqual(inline.main(), 0)
            with gzip.open(output, 'rt', encoding='utf-8') as handle:
                record = json.load(handle)[self.raw['id']]
            self.assertEqual(len(record['options']), 5)
            self.assertEqual(record['options'][0]['select_type'], 'RANDOM')


if __name__ == '__main__':
    unittest.main()
