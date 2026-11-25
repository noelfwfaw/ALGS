"""ChaoszeroSimulation config option, Challenge weekly handling, and stage name resolution tests."""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from module.config.server import set_server

set_server('chaoszero')

from module.chaoszero import simulation as sim
from module.config.config_updater import ConfigUpdater


class SimulationConfigTests(unittest.TestCase):
    def test_args_schema_uses_single_stamina_target_and_challenge_selects(self):
        args = json.loads(Path('module/config/argument/args.json').read_text(encoding='utf-8'))
        group = args['ChaoszeroSimulation']['ChaoszeroSimulation']
        self.assertEqual(set(group), {
            'TrainingTarget', 'TrainingChallenge', 'TrainingDifficulty', 'TrainingEfficiency', 'TrainingTimes',
        })

        expected_stamina = [
            sim.SIM_NONE,
            *(stage for key, _, _ in sim.SIM_TABS if key != 'TrainingChallenge' for stage in sim.SIM_TAB_STAGES[key]),
        ]
        self.assertEqual(group['TrainingTarget']['type'], 'select')
        self.assertEqual(group['TrainingTarget']['option'], expected_stamina)
        self.assertEqual(group['TrainingChallenge']['type'], 'select')
        self.assertEqual(group['TrainingChallenge']['option'], [sim.SIM_NONE, *sim.SIM_TAB_STAGES['TrainingChallenge']])

        for key, expected_options in (
            ('TrainingDifficulty', [0, 1, 2, 3, 4, 5, 6]),
            ('TrainingEfficiency', [0, 1, 2, 3, 4, 5, 6]),
            ('TrainingTimes', [0, 1, 2, 3, 4, 5, 6, 8, 10]),
        ):
            self.assertEqual(group[key]['type'], 'select', key)
            self.assertEqual(group[key]['option'], expected_options, key)

    def test_planned_targets_runs_challenge_first_and_maps_all_stages(self):
        task = sim.ChaoszeroSimulation.__new__(sim.ChaoszeroSimulation)
        task.config = SimpleNamespace(
            ChaoszeroSimulation_TrainingTarget='屍體與工具',
            ChaoszeroSimulation_TrainingChallenge='面對的恐懼',
        )
        self.assertEqual(task.sim_planned_targets(), [
            ('挑戰', 521, 2, '面對的恐懼'),
            ('記憶碎片', 439, 11, '屍體與工具'),
        ])

        task.config.ChaoszeroSimulation_TrainingChallenge = '不刷'
        task.config.ChaoszeroSimulation_TrainingTarget = '潛力材料—本能'
        self.assertEqual(task.sim_planned_targets(), [('潛力', 360, 3, '潛力材料—本能')])

        task.config.ChaoszeroSimulation_TrainingTarget = '不刷'
        self.assertEqual(task.sim_planned_targets(), [])

    def test_challenge_ignores_stamina_and_caps_by_weekly_attempts(self):
        task = sim.ChaoszeroSimulation.__new__(sim.ChaoszeroSimulation)
        task.config = SimpleNamespace(ChaoszeroSimulation_TrainingEfficiency=6, ChaoszeroSimulation_TrainingTimes=0)
        task.sim_stamina_left = Mock(return_value=5)
        task.sim_set_efficiency = Mock()

        # Challenge skips stamina checks & slider even with low stamina (<20).
        self.assertTrue(task.sim_apply_efficiency('挑戰'))
        task.sim_stamina_left.assert_not_called()
        task.sim_set_efficiency.assert_not_called()

        # 記憶碎片 checks >=60 stamina and skips slider drag.
        self.assertFalse(task.sim_apply_efficiency('記憶碎片'))
        task.sim_stamina_left.return_value = 60
        self.assertTrue(task.sim_apply_efficiency('記憶碎片'))
        task.sim_set_efficiency.assert_not_called()

        # 0 weekly attempts left skips without entering stage; 2 attempts caps fight loop at 2.
        task.sim_switch_tab = Mock(return_value=True)
        task.sim_training_appear = Mock(return_value=True)
        task.sim_open_stage = Mock(return_value=True)
        task.sim_configure = Mock()
        task.sim_fight = Mock(return_value=2)
        task.wait_until_appear = Mock(return_value=True)
        task.device = SimpleNamespace(adb_shell=Mock())

        task.sim_challenge_remaining = Mock(return_value=0)
        self.assertEqual(task.sim_run_tab('挑戰', 521, stage=1), 0)
        task.sim_open_stage.assert_not_called()

        task.sim_challenge_remaining = Mock(return_value=2)
        self.assertEqual(task.sim_run_tab('挑戰', 521, stage=1), 2)
        task.sim_fight.assert_called_once_with('挑戰', max_rounds=2)

    def test_config_updater_migrates_legacy_booleans_and_five_tabs(self):
        legacy_bool = {
            'ChaoszeroSimulation': {
                'ChaoszeroSimulation': {
                    'TrainingGrowth': False,
                    'TrainingMember': False,
                    'TrainingPartner': False,
                    'TrainingPotential': True,
                    'TrainingMemory': False,
                    'TrainingChallenge': False,
                    'TrainingStage': 4,
                    'TrainingDifficulty': 6,
                    'TrainingEfficiency': 6,
                    'TrainingTimes': 0,
                }
            }
        }
        migrated = ConfigUpdater().config_update(legacy_bool)['ChaoszeroSimulation']['ChaoszeroSimulation']
        self.assertEqual(migrated['TrainingTarget'], '潛力材料—虛無')
        self.assertEqual(migrated['TrainingChallenge'], '不刷')
        self.assertEqual(migrated['TrainingDifficulty'], 6)

        legacy_multi = {
            'ChaoszeroSimulation': {
                'ChaoszeroSimulation': {
                    'TrainingGrowth': '不刷',
                    'TrainingPotential': '潛力材料—本能',
                    'TrainingChallenge': '嚎叫浪子',
                }
            }
        }
        migrated2 = ConfigUpdater().config_update(legacy_multi)['ChaoszeroSimulation']['ChaoszeroSimulation']
        self.assertEqual(migrated2['TrainingTarget'], '潛力材料—本能')
        self.assertEqual(migrated2['TrainingChallenge'], '嚎叫浪子')


if __name__ == '__main__':
    unittest.main()
