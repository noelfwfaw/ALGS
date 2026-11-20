"""Offline replay of the first-floor spark checkpoint."""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from module.config.server import set_server

set_server('chaoszero')

from module.chaoszero import rogue
from module.webui.app import ROGUE_SECTIONS


class SparkCheckTest(unittest.TestCase):
    def replay(self, frames, enabled=True, fresh=True, rules='劍之雨 = 2', retreat=True,
               runs=0, core=False, target='劍之雨', member='30093', reward_image=None,
               human_takeover=False):
        task = rogue.ChaoszeroRogue.__new__(rogue.ChaoszeroRogue)
        task.config = SimpleNamespace(
            data={'ChaoszeroRogue': {'ChaoszeroRogue': {'RogueSparkFilter': rules}}},
            ChaoszeroRogue_RogueSparkCheck=enabled, ChaoszeroRogue_RogueSparkCheckCard=target,
            ChaoszeroRogue_RogueSlot1Member=member,
            ChaoszeroRogue_RogueCure=False,
            ChaoszeroRogue_RogueRuns=runs, ChaoszeroRogue_RogueLoop=False, task_delay=Mock(),
        )
        task.device = Mock(image=np.zeros((720, 1280, 3), dtype=np.uint8))
        frame = 'lobby'
        calls = []

        def replay_loop(**_):
            nonlocal frame
            task.route_step = rogue.LOOT_MIN_STEP
            for frame in frames:
                if frame == 'card_reward':
                    task.device.image = reward_image
                yield

        def quit_run(**_):
            nonlocal frame
            calls.append(('retreat', frame))
            if retreat:
                frame = 'team'
            return retreat

        def enter_run(**_):
            nonlocal frame
            calls.append(('enter', frame))
            frame = 'entry'
            return True

        task.loop = replay_loop
        task.rogue_quit = Mock(side_effect=quit_run)
        task.rogue_enter = Mock(side_effect=enter_run)
        task.ui_page_appear = lambda _: frame == 'lobby'
        task.appear = lambda button, **_: button is rogue.TEAM_TITLE and frame == 'team'
        task.rogue_team_appear = lambda: frame == 'team'
        task.rogue_state_load = lambda key, default: core if key == 'core_started' else default
        task.rogue_state_save = Mock()
        task.rogue_route_plan = lambda: calls.append(('walk', frame)) or True
        task.tap_point = Mock(side_effect=lambda *args, name: calls.append((name, frame)))
        for name in (
            'rogue_stuck_check', 'rogue_checkpoint_appear', 'rogue_resume_appear',
            'handle_rogue_remove', 'rogue_meditate_appear', 'rogue_detail_appear',
            'rogue_deck_appear', 'rogue_panel_appear', 'rogue_click_stuck',
            'rogue_copy_appear', 'rogue_card_reward_appear', 'rogue_flash_card_appear',
            'rogue_copy_card_appear', 'rogue_transform_appear', 'handle_rogue_fate',
            'rogue_story_appear', 'rogue_herald_appear', 'rogue_member_appear',
            'rogue_shop_appear', 'rogue_shop_sold_appear', 'rogue_rest_appear',
            'rogue_prompt_appear', 'rogue_god_pick', 'rogue_crash_appear',
            '_rogue_meditate_allows',
        ):
            setattr(task, name, Mock(return_value=False))
        task.rogue_item_appear = lambda: frame == 'reward'
        task.rogue_modal_appear = lambda: frame == 'modal'
        task.rogue_primary_point = lambda: (1, 1) if frame == 'loot' else None
        if reward_image is not None:
            task.appear = lambda button, **kwargs: (
                button is rogue.ROGUE_CARD_REWARD and button.match(task.device.image, **kwargs))
            task.rogue_card_reward_appear = rogue.ChaoszeroRogue.rogue_card_reward_appear.__get__(task)
            task.rogue_primary_point = rogue.ChaoszeroRogue.rogue_primary_point.__get__(task)
        task.rogue_dialog_point = lambda: (1, 1) if frame == 'confirm' else None
        task.rogue_purple_point = lambda: (1120, 662) if frame in ('save_unreadable', 'save', 'result') else None
        task.rogue_battle_appear = lambda: frame in ('battle', 'god_other_with_hud')
        task.handle_rogue_battle_settings = Mock(return_value=True)
        task.rogue_flash_appear = lambda: frame in ('flash', 'wrong')
        task.rogue_god_appear = lambda: frame in ('god', 'god_other', 'god_other_with_hud', 'god_unreadable')
        task.rogue_loot_appear = lambda: frame == 'loot'
        task.rogue_map_appear = lambda: frame in ('map', 'preview')
        task.rogue_map_preview_appear = lambda: frame == 'preview'
        task.rogue_card_page_record = Mock()
        forms, _ = rogue.rogue_cards.CardLibrary().forms('劍之雨')
        other_forms, _ = rogue.rogue_cards.CardLibrary().forms('展開極光')
        reader = Mock()
        reader.read_all.side_effect = lambda *_, **__: (
            ['', '', ''] if frame == 'god_unreadable'
            else other_forms[:3] if frame in ('god_other', 'god_other_with_hud')
            else [forms[i] for i in ([0, 2, 3] if frame == 'wrong' else [0, 1, 2])]
        )
        reader.read_name.side_effect = lambda *_: {'save': '存檔資料收集完成', 'result': '探索結果'}.get(frame, '')
        task.rogue_save_trash_visible = Mock(return_value=True)
        task.rogue_dump_unknown = Mock()
        timer = Mock()
        timer.start.return_value = timer
        with patch.object(rogue, 'Timer', return_value=timer), \
                patch.object(rogue.rogue_equipment, 'Equipment') as equipment, \
                patch.object(rogue.rogue_cards, 'CardReader', return_value=reader):
            equipment.return_value.handle.return_value = False
            if human_takeover:
                with self.assertRaises(rogue.RequestHumanTakeover):
                    task.run() if runs else task.rogue_run(fresh_run=fresh)
            elif runs:
                task.run()
            else:
                task.rogue_run(fresh_run=fresh)
        return task, calls

    def test_single_neutral_card_reward_skips_before_generic_confirm(self):
        fixture = Path(__file__).parent / 'fixtures' / 'chaoszero' / 'rogue_card_reward_neutral.png'
        image = cv2.cvtColor(cv2.imread(str(fixture)), cv2.COLOR_BGR2RGB)
        button = rogue.ROGUE_CARD_REWARD
        template = cv2.cvtColor(cv2.imread(button.file), cv2.COLOR_BGR2RGB)
        x1, y1, x2, y2 = button.area
        with patch.object(button, 'image', template[y1:y2, x1:x2]), patch.object(button, '_match_init', True):
            task, _ = self.replay(['card_reward'], reward_image=image)
            self.assertIsNotNone(task.rogue_primary_point())
            task.tap_point.assert_called_once_with(899, 669, name='ROGUE_SECONDARY')
            task.rogue_card_page_record.assert_called_once_with('reward')

            image[640:701, 790:1010] = 0
            task, _ = self.replay(['card_reward'], reward_image=image)
            self.assertIsNotNone(task.rogue_primary_point())
            task.tap_point.assert_not_called()

    def test_missed_or_wrong_target_restarts_after_rewards(self):
        for spark in ([], ['wrong', 'battle']):
            with self.subTest(spark=spark):
                task, calls = self.replay(['map'] + spark + ['loot', 'reward', 'map'])
                self.assertEqual(task.spark_obtained, set())
                self.assertEqual(calls[-3:], [
                    ('ROGUE_PRIMARY', 'loot'), ('ROGUE_ITEM', 'reward'), ('retreat', 'map'),
                ])
                self.assertEqual(calls[0], ('walk', 'map'))

    def test_both_choosers_and_existing_keyword_rules_count(self):
        for spark, rule in (('flash', '2'), ('god', '2'), ('flash', '不存在的詞,劍')):
            with self.subTest(spark=spark, rule=rule):
                task, calls = self.replay([spark, 'confirm', 'battle', 'loot', 'map'],
                                          rules='劍之雨 = ' + rule)
                task.rogue_quit.assert_not_called()
                self.assertEqual(task.spark_obtained, {'劍之雨'})
                self.assertEqual(calls[-1], ('walk', 'map'))

    def test_a_tap_and_dialog_are_not_acquisition(self):
        task, _ = self.replay(['god', 'confirm', 'god', 'modal'])
        self.assertEqual(task.spark_obtained, set())
        task.rogue_quit.assert_not_called()

    def test_next_god_chooser_confirms_previous_target_when_card_changes(self):
        for chooser in ('god_other', 'god_other_with_hud'):
            with self.subTest(chooser=chooser):
                task, calls = self.replay(['flash', 'confirm', 'god_unreadable', chooser,
                                           'battle', 'loot', 'map'])
                self.assertEqual(task.spark_obtained, {'劍之雨'})
                self.assertNotIn(('ROGUE_CARD', 'god_unreadable'), calls)
                self.assertIn(('ROGUE_CARD', chooser), calls)
                self.assertEqual(calls[-1], ('walk', 'map'))

    def test_normal_settlement_waits_for_a_recognized_title(self):
        _, calls = self.replay(['save_unreadable', 'save', 'result'])
        self.assertEqual(calls, [('ROGUE_SAVE_TRASH', 'save'), ('ROGUE_PURPLE', 'result')])

    def test_save_title_template_recognizes_page_without_ocr(self):
        task = rogue.ChaoszeroRogue.__new__(rogue.ChaoszeroRogue)
        button = rogue.ROGUE_SAVE_TITLE
        image = cv2.cvtColor(cv2.imread(button.file), cv2.COLOR_BGR2RGB)
        x1, y1, x2, y2 = button.area
        task.device = Mock(image=image)
        task.card_reader = Mock()
        task.appear = lambda button, **kwargs: button.match(task.device.image, **kwargs)
        with patch.object(button, 'image', image[y1:y2, x1:x2]), patch.object(button, '_match_init', True):
            self.assertEqual(task.rogue_settlement_page(), 'save')
        task.card_reader.read_name.assert_not_called()

    def test_unreadable_settlement_eventually_requests_human(self):
        task, calls = self.replay(['save_unreadable', 'save_unreadable'], human_takeover=True)
        self.assertEqual(calls, [])
        task.rogue_dump_unknown.assert_called_once()

    def test_preview_defers_checkpoint_until_after_reward_flash(self):
        task, calls = self.replay(['loot', 'reward', 'preview', 'flash', 'map'])
        task.rogue_quit.assert_not_called()
        self.assertEqual(task.spark_obtained, {'劍之雨'})
        self.assertEqual(calls[-3:], [
            ('ROGUE_ZOOM', 'preview'), ('ROGUE_CARD', 'flash'), ('walk', 'map'),
        ])

    def test_only_the_selected_card_controls_retreat(self):
        rules = '劍之雨 = 2\n展開極光 = 2'
        frames = ['flash', 'battle', 'loot', 'map']
        for target, action, obtained in (
            ('劍之雨', 'walk', {'劍之雨'}),
            ('展開極光', 'retreat', set()),
        ):
            with self.subTest(target=target):
                task, calls = self.replay(frames, rules=rules, target=target)
                self.assertIn(('ROGUE_CARD', 'flash'), calls)
                self.assertEqual(task.spark_obtained, obtained)
                self.assertEqual(calls[-1], (action, 'map'))

    def test_disabled_empty_resumed_or_later_boss_never_restarts(self):
        for args in ({'enabled': False}, {'fresh': False}, {'rules': ''}, {'core': True},
                     {'target': ''}, {'target': '展開極光'}, {'member': '1003'}, {'member': ''}):
            with self.subTest(args=args):
                task, calls = self.replay(['loot', 'reward', 'map'], **args)
                task.rogue_quit.assert_not_called()
                self.assertEqual(calls[-1], ('walk', 'map'))

    def test_spark_retry_decomposes_all_current_saves_before_leaving(self):
        explore = rogue.ROGUE_EXPLORE_RESULT
        level = rogue.ROGUE_REWARD_LEVEL
        confirm = rogue.RESULT_CONFIRM
        images = {button: cv2.cvtColor(cv2.imread(button.file), cv2.COLOR_BGR2RGB)
                  for button in (explore, level, confirm)}
        markers = {
            'title_only': (explore,),
            'explore': (explore,),
            'confirm_only': (confirm,),
            'level_only': (level,),
            'reward': (level, confirm),
        }
        for retry, discarded in ((True, (1, 2, 3)), (False, (1, 3))):
            with self.subTest(retry=retry):
                task = rogue.ChaoszeroRogue.__new__(rogue.ChaoszeroRogue)
                task.config = SimpleNamespace(ChaoszeroRogue_RogueSaveKeep=2)
                task.device = Mock()
                task.spark_boss_pending = True
                task.spark_targets, task.spark_obtained = {'劍之雨': ['2']}, set()
                current = None
                saves = set(rogue.SAVE_TRASH)
                next_point = (1120, 662)

                def replay(**_):
                    nonlocal current
                    frames = ['confirm', 'loading', 'title_only', 'explore', 'confirm_only',
                              'level_only', 'reward', 'unreadable']
                    for current in frames + ['save', 'popup'] * len(discarded) + ['save', 'team']:
                        yield

                def tap(x, y, *, name):
                    if name == 'ROGUE_SAVE_TRASH':
                        saves.remove((x, y))

                task.loop = replay
                task.ui_page_appear = Mock(return_value=False)

                def appear(button, **kwargs):
                    if button not in markers.get(current, ()):
                        return False
                    image = images[button]
                    x1, y1, x2, y2 = button.area
                    with patch.object(button, '_match_init', True), patch.object(button, 'image', image[y1:y2, x1:x2]):
                        return button.match(image, **kwargs)

                task.appear = appear
                task.rogue_team_appear = lambda: current == 'team'
                task.rogue_crash_appear = lambda: False
                task.rogue_dialog_point = lambda: (849, 454) if current == 'confirm' else None
                task.rogue_item_appear = lambda: current == 'popup'
                task.rogue_primary_point = Mock(return_value=None)
                task.rogue_purple_point = lambda: (
                    next_point if current in ('explore', 'confirm_only', 'level_only', 'reward', 'unreadable', 'save')
                    else None)
                task.card_reader = Mock()

                def read_title(*_):
                    if current != 'save':
                        raise ValueError('Temporary OCR failure')
                    return '存檔資料收集完成'

                task.card_reader.read_name.side_effect = read_title
                task.rogue_save_trash_visible = lambda slot: rogue.SAVE_TRASH[slot - 1] in saves
                task.tap_point = Mock(side_effect=tap)

                with patch.object(rogue, 'Timer') as timer:
                    timer.return_value.start.return_value.reached.return_value = False
                    self.assertTrue(task.rogue_spark_restart_on_core_map() if retry else task.rogue_quit())
                self.assertEqual(saves, set() if retry else {rogue.SAVE_TRASH[1]})
                self.assertEqual(task.config.ChaoszeroRogue_RogueSaveKeep, 2)
                self.assertEqual([call[1]['name'] for call in task.tap_point.call_args_list],
                                 ['ROGUE_DIALOG', 'ROGUE_PURPLE', 'ROGUE_PURPLE']
                                 + ['ROGUE_SAVE_TRASH', 'ROGUE_ITEM'] * len(discarded) + ['ROGUE_PURPLE'])

    def test_restarts_through_outer_loop_and_stops_on_failed_retreat(self):
        for retreat in (True, False):
            with self.subTest(retreat=retreat):
                task, calls = self.replay(['loot', 'map'], retreat=retreat, runs=2,
                                          human_takeover=not retreat)
                self.assertEqual(task.rogue_enter.call_count, 2 if retreat else 1)
                self.assertEqual(task.rogue_quit.call_count, task.rogue_enter.call_count)
                self.assertEqual(task.stopped_by_stuck, not retreat)
                self.assertFalse(any(action == 'walk' for action, _ in calls))
                if not retreat:
                    task.config.task_delay.assert_not_called()

    def test_single_build_checkbox_defaults_to_off(self):
        from module.config.config_generated import GeneratedConfig

        name = 'RogueSparkCheck'
        self.assertEqual(sum(names.count(name) for names in ROGUE_SECTIONS.values()), 1)
        self.assertIn(name, ROGUE_SECTIONS['Build'])
        path = Path(__file__).resolve().parents[1] / 'module/config/argument/args.json'
        option = json.loads(path.read_text(encoding='utf-8'))['ChaoszeroRogue']['ChaoszeroRogue'][name]
        self.assertEqual(option, {'type': 'checkbox', 'value': False})
        self.assertIs(GeneratedConfig.ChaoszeroRogue_RogueSparkCheck, False)


if __name__ == '__main__':
    unittest.main()
