import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import cv2

from module.config.server import set_server

set_server('chaoszero')
from module.chaoszero import chaoszero_ui as ui
from module.chaoszero import rogue
from module.chaoszero import rogue_route as route
from module.chaoszero.rogue import ChaoszeroRogue


FIXTURES = Path(__file__).parent / 'fixtures' / 'chaoszero'


def capture(name):
    return cv2.cvtColor(cv2.imread(str(FIXTURES / name)), cv2.COLOR_BGR2RGB)


class TestRogueEntry(unittest.TestCase):
    def boot_task(self, command, image):
        task = ui.ChaoszeroUI.__new__(ui.ChaoszeroUI)
        task.config = SimpleNamespace(task=SimpleNamespace(command=command))
        task.interval_timer = {}
        task.device = Mock(image=image, has_cached_image=True)
        task.device.screenshot.side_effect = AssertionError('Unexpected boot loop')
        return task

    def test_rogue_boot_hands_off_both_entry_pages_without_back_or_wake(self):
        for button in (rogue.ROGUE_TEAM_ENTER, ui.ROGUE_MODE_ENTRY):
            with self.subTest(page=button.name):
                frame = cv2.cvtColor(cv2.imread(button.file), cv2.COLOR_BGR2RGB)
                task = self.boot_task('ChaoszeroRogue', frame)
                task.app_start()
                task.device.click.assert_not_called()
                task.device.adb_shell.assert_not_called()
                task.device.screenshot.assert_not_called()

    def test_unlimited_runs_restart_from_dark_team_page_without_dream_switch(self):
        frame = cv2.cvtColor(cv2.imread(ui.TEAM_TITLE.file), cv2.COLOR_BGR2RGB)
        label = cv2.cvtColor(cv2.imread(ui.ROGUE_TEAM_MODE_DARK.file), cv2.COLOR_BGR2RGB)
        x1, y1, x2, y2 = ui.ROGUE_TEAM_MODE_DARK.area
        frame[y1:y2, x1:x2] = label[y1:y2, x1:x2]
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.config = Mock(ChaoszeroRogue_RogueRuns=0, ChaoszeroRogue_RogueLoop=True,
                           ChaoszeroRogue_RogueCure=False)
        task.device = Mock(image=frame)
        task.rogue_enter = Mock(return_value=True)
        task.rogue_state_save = Mock()
        task.stopped_by_beacon = False
        task.stopped_by_stuck = False

        def finish(fresh_run):
            self.assertTrue(fresh_run)
            if task.rogue_run.call_count == 2:
                task.stopped_by_beacon = True
                task.waypoints = 1

        task.rogue_run = Mock(side_effect=finish)
        self.assertFalse(task.appear(ui.ROGUE_DREAM_ON, offset=(20, 20), similarity=0.9))
        task.run()
        self.assertEqual(task.rogue_enter.call_count, 2)
        self.assertEqual(task.rogue_enter.call_args_list,
                         [call(reselect_world=True), call(reselect_world=False)])
        self.assertEqual(task.rogue_run.call_count, 2)
        task.config.task_delay.assert_called_once_with(minute=1)

    def test_same_entry_pages_finish_retreat_and_normal_run(self):
        for button, expected in (
            (ui.page_main.check_button, True), (ui.ROGUE_MODE_ENTRY, True),
            (rogue.ROGUE_TEAM_ENTER, True), (ui.TEAM_TITLE, False),
        ):
            with self.subTest(page=button.name):
                frame = cv2.cvtColor(cv2.imread(button.file), cv2.COLOR_BGR2RGB)
                task = ChaoszeroRogue.__new__(ChaoszeroRogue)
                task.config = SimpleNamespace(data={})
                task.device = Mock(image=frame)
                task.tap_point = Mock()
                task.loop = Mock(return_value=range(1))
                task.rogue_state_load = lambda key, default: default
                task.rogue_stuck_check = Mock(side_effect=AssertionError('Entry page handled as in-run'))

                self.assertEqual(task.rogue_outside_appear(), expected)
                self.assertEqual(task.rogue_quit(discard_saves=True), expected)
                task.rogue_run()
                self.assertEqual(task.stopped_by_stuck, not expected)
                task.device.click.assert_not_called()
                task.tap_point.assert_not_called()

    def test_boot_for_other_tasks_backs_out_of_mode_page(self):
        frame = cv2.cvtColor(cv2.imread(ui.ROGUE_MODE_ENTRY.file), cv2.COLOR_BGR2RGB)
        task = self.boot_task('ChaoszeroMain', frame)
        task.ui_page_appear = Mock(side_effect=[False, True])
        task.device.screenshot.side_effect = None
        task.app_start()
        task.device.click.assert_called_once_with(ui.CHAOSZERO_BACK)
        task.device.adb_shell.assert_not_called()

    def test_rogue_boot_backs_out_of_a_team_page_without_rogue_markers(self):
        frame = cv2.cvtColor(cv2.imread(ui.TEAM_TITLE.file), cv2.COLOR_BGR2RGB)
        task = self.boot_task('ChaoszeroRogue', frame)
        task.ui_page_appear = Mock(side_effect=[False, True])
        task.device.screenshot.side_effect = None
        task.app_start()
        task.device.adb_shell.assert_called_once_with(['input', 'keyevent', '4'])
        task.device.click.assert_not_called()

    def test_rogue_navigation_clicks_left_mode_card_then_enters_from_team(self):
        mode = cv2.cvtColor(cv2.imread(ui.ROGUE_MODE_ENTRY.file), cv2.COLOR_BGR2RGB)
        team = cv2.cvtColor(cv2.imread(rogue.ROGUE_TEAM_ENTER.file), cv2.COLOR_BGR2RGB)
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.config = SimpleNamespace(ChaoszeroRogue_RogueWorld='', ChaoszeroRogue_RogueDreamMode='')
        task.device = Mock()
        task.tap_point = Mock()
        task.rogue_resume_appear = Mock(return_value=False)
        task.rogue_primary_point = Mock(side_effect=[False, True])
        for name in ('rogue_story_appear', 'rogue_choice_appear', 'rogue_battle_appear',
                     'rogue_herald_appear', 'rogue_option_points', 'rogue_equip_appear',
                     'rogue_rest_appear', 'rogue_copy_appear', 'rogue_remove_appear', 'rogue_map_appear'):
            setattr(task, name, Mock(return_value=False))

        def replay(frames):
            for frame in frames:
                task.device.image = frame
                yield

        for entry in ([mode, team], [team]):
            with self.subTest(from_mode=len(entry) > 1):
                task.tap_point.reset_mock()
                task.loop = Mock(side_effect=[replay(entry), replay([team, team])])
                task.rogue_primary_point.side_effect = [False, True]
                with patch.object(rogue, 'Timer'):
                    self.assertTrue(task.rogue_enter())
                names = [call[1]['name'] for call in task.tap_point.call_args_list]
                self.assertEqual(names, ['ROGUE_MODE', 'ROGUE_TEAM_ENTER']
                                 if len(entry) > 1 else ['ROGUE_TEAM_ENTER'])

    def test_rogue_reselects_configured_world_before_accepting_team_page(self):
        team = capture(Path(rogue.ROGUE_TEAM_ENTER.file).resolve())
        detail = capture(Path(rogue.ROGUE_WORLD_ENTER.file).resolve())
        world_list = capture(Path(rogue.ROGUE_WORLD_LANHU.file).resolve())
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.config = SimpleNamespace(ChaoszeroRogue_RogueWorld='藍壺', ChaoszeroRogue_RogueDreamMode='開啟')
        task.device = Mock()
        task.rogue_resume_appear = Mock(return_value=False)
        actions = Mock()
        task.tap_point = actions.tap
        task.device.click = actions.click
        task.rogue_dream_set = actions.dream

        def replay(frames):
            for frame in frames:
                task.device.image = frame
                yield

        task.loop = Mock(side_effect=[replay((team, detail, world_list, detail, team)),
                                     replay((world_list, detail))])
        with patch.object(rogue, 'Timer'):
            self.assertTrue(task.rogue_enter_team())
        self.assertEqual(actions.mock_calls, [
            call.tap(*rogue.WORLD_BACK_POINT, name='ROGUE_WORLD_BACK'),
            call.tap(*rogue.WORLD_BACK_POINT, name='ROGUE_WORLD_BACK'),
            call.tap(147, 485, name='ROGUE_WORLD_PICK'),
            call.click(rogue.ROGUE_WORLD_ENTER),
            call.dream(True),
        ])

    def test_next_run_keeps_the_world_the_game_remembers(self):
        team = capture(Path(rogue.ROGUE_TEAM_ENTER.file).resolve())
        detail = capture(Path(rogue.ROGUE_WORLD_ENTER.file).resolve())
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.config = SimpleNamespace(ChaoszeroRogue_RogueWorld='藍壺', ChaoszeroRogue_RogueDreamMode='開啟')
        task.device = Mock()
        task.rogue_resume_appear = Mock(return_value=False)
        actions = Mock()
        task.tap_point = actions.tap
        task.device.click = actions.click
        task.rogue_dream_set = actions.dream

        def replay(frames):
            for frame in frames:
                task.device.image = frame
                yield

        # 刚打完一局的下一轮：队伍页 / 世界详情页都直接沿用，不退回列表重选。
        for frames, expected in (
            ((team,), [call.dream(True)]),
            ((detail, team), [call.click(rogue.ROGUE_WORLD_ENTER), call.dream(True)]),
        ):
            with self.subTest(frames=len(frames)):
                actions.reset_mock()
                task.loop = Mock(side_effect=[replay(frames)])
                with patch.object(rogue, 'Timer'):
                    self.assertTrue(task.rogue_enter_team(reselect_world=False))
                self.assertEqual(actions.mock_calls, expected)


class TestRogueState(unittest.TestCase):
    def test_run_state_is_profile_specific_and_leaves_legacy_state_alone(self):
        first = ChaoszeroRogue.__new__(ChaoszeroRogue)
        second = ChaoszeroRogue.__new__(ChaoszeroRogue)
        first.config = SimpleNamespace(config_name='profile-a')
        second.config = SimpleNamespace(config_name='profile-b')

        with TemporaryDirectory() as folder, patch.object(rogue, 'ROGUE_STATE_DIR', folder):
            legacy = Path(folder) / 'rogue_state.json'
            old_state = '{"remove_done": 99, "core_started": true}'
            legacy.write_text(old_state, encoding='utf-8-sig')
            self.assertEqual(first.rogue_state_load('remove_done', 0), 0)
            self.assertFalse(second.rogue_state_load('core_started', False))

            first.rogue_state_save(remove_done=3)
            first.rogue_state_save(core_started=True)
            second.rogue_state_save(remove_done=0, core_started=False)
            self.assertEqual(first.rogue_state_load('remove_done'), 3)
            self.assertTrue(first.rogue_state_load('core_started'))
            self.assertEqual(second.rogue_state_load('remove_done'), 0)
            self.assertFalse(second.rogue_state_load('core_started'))
            self.assertEqual(legacy.read_text(encoding='utf-8-sig'), old_state)


class TestRoute(unittest.TestCase):
    def test_beacon_uses_title_and_requires_confirmation_arrow(self):
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.device = Mock()
        collapsed = capture(Path(rogue.ROGUE_BEACON_PROMPT.file).resolve())
        expanded = capture(Path(rogue.ROGUE_BEACON_PROMPT2.file).resolve())
        # Equipment art and text can change independently of the waypoint title.
        collapsed[591:617, 499:790] = 40
        expanded[547:573, 499:790] = 40
        for expected, image in ((1, collapsed), (2, expanded), (0, capture('rogue_route_opening.png'))):
            with self.subTest(stage=expected):
                task.device.image = image
                self.assertEqual(task.rogue_beacon_stage(), expected)
        expanded[660:706, 615:665] = 40
        task.device.image = expanded
        self.assertEqual(task.rogue_beacon_stage(), 0)

    def test_grey_start_keeps_first_column_and_selects_top_branch(self):
        image = capture('rogue_route_opening.png')
        nodes = route.read_nodes(image)
        self.assertEqual(route.LAST_PIN_X, 178)
        first = [node for node in nodes if node.tier == 0]
        self.assertEqual([(node.x, node.kind) for node in first], [(341, 'battle')] * 3)
        plan = route.plan(nodes, edges=route.read_edges(image, nodes))
        self.assertEqual([entry[0]['kind'] for entry in plan],
                         ['battle', 'event', 'rest', 'battle', 'event', 'battle'])
        cards = route.read_cards(capture('rogue_route_platforms.png'))
        self.assertIs(route.planned_card(cards, plan[0][0]), min(cards, key=lambda card: card.y))
        self.assertIsNone(route.planned_card(cards[:2], plan[0][0]))
        self.assertEqual(plan[1][0]['choices'], ['event', 'event'])

    def test_missing_pin_does_not_guess_first_column(self):
        image = capture('rogue_route_opening.png')
        image[310:355, 155:201] = 0
        self.assertEqual(route.read_nodes(image), [])
        self.assertIsNone(route.LAST_PIN_X)

    def test_neighboring_horizontal_line_is_not_a_diagonal_edge(self):
        image = capture('rogue_route_opening.png')
        nodes = route.read_nodes(image)
        edges = set(route.read_edges(image, nodes))
        middle_event = min(range(len(nodes)), key=lambda i: abs(nodes[i].x - 505) + abs(nodes[i].y - 258))
        lower_event = min(range(len(nodes)), key=lambda i: abs(nodes[i].x - 505) + abs(nodes[i].y - 366))
        rest = min(range(len(nodes)), key=lambda i: abs(nodes[i].x - 669) + abs(nodes[i].y - 258))
        self.assertIn((middle_event, rest), edges)
        self.assertNotIn((lower_event, rest), edges)

    def test_glow_does_not_hide_the_event_diamond_or_elite_platform(self):
        image = capture('rogue_route_glowing_preview.png')
        nodes = route.read_nodes(image)
        entry = route.plan(nodes, state={'avoid_elite': True},
                           edges=route.read_edges(image, nodes))[0][0]
        self.assertEqual(entry['choices'], ['event', 'elite', 'event'])
        cards = route.read_cards(capture('rogue_route_glowing_platforms.png'))
        self.assertEqual([card.kind for card in sorted(cards, key=lambda card: card.y)],
                         entry['choices'])
        self.assertIs(route.planned_card(cards, entry), max(cards, key=lambda card: card.y))

    def test_only_confirmed_entry_advances_counters_once(self):
        task = Mock(spec=ChaoszeroRogue)
        task.node_pending = object()
        task.route_step, task.plan_index = 7, 2
        task.event_visit = {'old': 1}
        for name in (
                'rogue_map_appear', 'rogue_map_preview_appear', 'rogue_battle_appear',
                'rogue_prompt_appear', 'rogue_rest_appear', 'rogue_story_appear',
                'rogue_choice_appear', 'rogue_beacon_stage', 'rogue_treasure_card_appear',
                'rogue_dice_appear', 'rogue_dice_result_appear', 'rogue_card_reward_appear',
                'rogue_flash_appear', 'rogue_god_appear', 'rogue_option_points',
                'rogue_primary_point'):
            getattr(task, name).return_value = False
        confirm = lambda: ChaoszeroRogue.rogue_route_confirm_move(task)
        task.rogue_battle_appear.return_value = True
        task.rogue_map_appear.return_value = True
        self.assertFalse(confirm())
        self.assertFalse(confirm())
        task.rogue_map_appear.return_value = False
        task.rogue_map_preview_appear.return_value = True
        self.assertFalse(confirm())
        task.rogue_map_preview_appear.return_value = False
        task.rogue_battle_appear.return_value = False
        self.assertFalse(confirm())
        task.rogue_prompt_appear.return_value = True
        task.rogue_primary_point.return_value = True
        self.assertFalse(confirm())
        task.rogue_prompt_appear.return_value = False
        task.rogue_primary_point.return_value = False
        self.assertEqual((task.route_step, task.plan_index), (7, 2))
        self.assertEqual(task.event_visit, {'old': 1})
        task.rogue_rest_appear.return_value = True
        self.assertTrue(confirm())
        self.assertFalse(confirm())
        self.assertEqual((task.route_step, task.plan_index), (8, 3))
        self.assertEqual(task.event_visit, {})


if __name__ == '__main__':
    unittest.main()
