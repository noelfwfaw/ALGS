import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import cv2
import numpy as np

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
        task.rogue_primary_point = Mock(return_value=True)
        for name in ('rogue_story_appear', 'rogue_choice_appear', 'rogue_battle_appear',
                     'rogue_herald_appear', 'rogue_option_points', 'rogue_equip_appear',
                     'rogue_rest_appear', 'rogue_copy_appear', 'rogue_remove_appear', 'rogue_map_appear'):
            setattr(task, name, Mock(return_value=False))

        def replay(frames):
            for frame in frames:
                task.device.image = frame
                yield

        in_run = team * 0
        for entry in ([mode, team], [team]):
            with self.subTest(from_mode=len(entry) > 1):
                task.tap_point.reset_mock()
                task.loop = Mock(side_effect=[replay(entry), replay([team, in_run])])
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

    def test_route_plan_waits_for_preview_settle_before_reading_and_closing(self):
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.rogue_map_preview_appear = Mock(side_effect=[False, True])
        task.tap_point = Mock()
        task.wait_until_appear = Mock(return_value=True)
        task.wait_until_disappear = Mock(side_effect=[False, True])
        task.rogue_route_read = Mock(return_value=[])
        task.rogue_route_style = Mock(return_value=route.ROUTE_EVENT)
        task.rogue_route_state = Mock(return_value={})

        self.assertFalse(task.rogue_route_plan())
        task.wait_until_appear.assert_called_once_with(
            rogue.ROGUE_PREVIEW, offset=(10, 8), timeout=rogue.ROUTE_OPEN_TIMEOUT, settle=3)
        self.assertEqual(
            [c[1]['name'] for c in task.tap_point.call_args_list],
            ['ROGUE_ROUTE_OPEN', 'ROGUE_ROUTE_CLOSE', 'ROGUE_ROUTE_CLOSE'],
        )
        self.assertEqual(task.wait_until_disappear.call_count, 2)

    def test_empty_map_cards_presses_fallback_without_discarding_single_branch_plan(self):
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.tap_point = Mock()
        task.node_pending = None
        task.plan_index = 0
        # Single-choice planned node (e.g. mid-floor safe area rest): falls back at try 3
        task.route_plan = [[{'kind': 'rest', 'choices': ['rest']}]]
        for tries, tapped in ((1, False), (2, False), (3, True)):
            task.node_tries = tries
            self.assertEqual(task.rogue_map_fallback(), tapped)
        task.tap_point.assert_called_once_with(*rogue.NODE_FALLBACK, name='ROGUE_NODE')

        # Multi-branch planned node: waits 3 tries before falling back at try 4
        task.tap_point.reset_mock()
        task.route_plan = [[{'kind': 'event', 'choices': ['battle', 'event']}]]
        for tries, tapped in ((1, False), (2, False), (3, False), (4, True)):
            task.node_tries = tries
            self.assertEqual(task.rogue_map_fallback(), tapped)
        task.tap_point.assert_called_once_with(*rogue.NODE_FALLBACK, name='ROGUE_NODE')

    def test_dream_notice_ticks_hide_box_before_confirm(self):
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.appear = Mock(side_effect=lambda btn, **_: btn is rogue.ROGUE_DREAM_NOTICE)
        task.tap_point = Mock()
        task.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8), click=Mock())
        press = Mock()
        press.reached.return_value = True

        # Unchecked: ticks 一週內不再顯示 before clicking confirm
        self.assertTrue(task.rogue_handle_dream_notice(press))
        task.tap_point.assert_called_once_with(*rogue.DREAM_HIDE_POINT, name='ROGUE_DREAM_HIDE')
        task.device.click.assert_not_called()

        # Checked (orange box): closes with ROGUE_DREAM_OK
        task.tap_point.reset_mock()
        x1, y1, x2, y2 = rogue.DREAM_HIDE_BOX
        task.device.image[y1:y2, x1:x2] = (239, 130, 50)
        self.assertTrue(task.rogue_handle_dream_notice(press))
        task.tap_point.assert_not_called()
        task.device.click.assert_called_once_with(rogue.ROGUE_DREAM_OK)

    def test_dialog_confirm_ticks_hide_checkbox_once_before_confirming(self):
        for confirm_y in (454, 481, 488):
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            # Orange confirm button + grey 23x24 checkbox 71px above it
            frame[confirm_y - 25:confirm_y + 25, 680:1010] = (239, 130, 50)
            frame[confirm_y - 83:confirm_y - 59, 529:552] = (192, 192, 192)
            task = ChaoszeroRogue.__new__(ChaoszeroRogue)
            task.device = SimpleNamespace(image=frame)
            task.tap_point = Mock()
            pt = task.rogue_dialog_point()
            self.assertIsNotNone(pt)
            # First call checks the checkbox without confirming
            self.assertFalse(task.rogue_confirm_dialog(pt))
            cx, cy = task.tap_point.call_args[0]
            self.assertAlmostEqual(cx, 540, delta=2)
            self.assertAlmostEqual(cy, pt[1] - 71, delta=2)
            self.assertEqual(task.tap_point.call_args[1]['name'], 'ROGUE_DIALOG_HIDE')
            # Second call confirms at pt even if checkbox box stays grey (anti-toggle guard)
            task.tap_point.reset_mock()
            self.assertTrue(task.rogue_confirm_dialog(pt))
            task.tap_point.assert_called_once_with(pt[0], pt[1], name='ROGUE_DIALOG')

        # Tall white dialog (e.g. 治療中心「消除記憶」 at y=478..534, center ~504)
        cure_dlg = np.zeros((720, 1280, 3), dtype=np.uint8)
        cure_dlg[478:534, 649:1038] = (239, 130, 50)
        cure_task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        cure_task.device = SimpleNamespace(image=cure_dlg)
        self.assertEqual(cure_task.rogue_dialog_point(), (843, 505))

        # Fixture dialogs without checkboxes confirm immediately
        for fixture in (
            'rogue_equipment_refresh_confirm.png',
            'rogue_equipment_salvage_confirm.png',
            'rogue_equipment_spark_limit_confirm.png',
        ):
            task = ChaoszeroRogue.__new__(ChaoszeroRogue)
            task.device = SimpleNamespace(image=capture(fixture))
            task.tap_point = Mock()
            pt = task.rogue_dialog_point()
            self.assertIsNotNone(pt, fixture)
            self.assertIsNone(task.rogue_dialog_hide_point(pt), fixture)
            self.assertTrue(task.rogue_confirm_dialog(pt))
            task.tap_point.assert_called_once_with(pt[0], pt[1], name='ROGUE_DIALOG')

        # Tall white dialog (e.g. 治療中心「消除記憶」 at y=478..534, center ~504)
        cure_dlg = np.zeros((720, 1280, 3), dtype=np.uint8)
        cure_dlg[478:534, 649:1038] = (239, 130, 50)
        cure_task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        cure_task.device = SimpleNamespace(image=cure_dlg)
        self.assertEqual(cure_task.rogue_dialog_point(), (843, 505))

    def test_route_rejects_dimmed_nodes_plans_small_maps_and_resolves_unique_kind(self):
        image = capture('rogue_route_glowing_preview.png')
        # Simulate dimmed unreachable rest (dark orange V<=115) & elite (dark purple V<=115) in col 1.
        cv2.rectangle(image, (305, 130), (380, 180), (110, 62, 24), -1)
        cv2.rectangle(image, (305, 240), (380, 290), (85, 42, 112), -1)
        nodes = route.read_nodes(image)
        tier0 = [n for n in nodes if n.tier == 0]
        self.assertEqual(len(tier0), 3)

        # Edge check preserves real diagonal t4(476)->t5(584) and rejects absent diagonal t4(584)->t5(476).
        opening = capture('rogue_route_opening.png')
        op_nodes = route.read_nodes(opening)
        op_edges = set(route.read_edges(opening, op_nodes))
        t4_mid = min(range(len(op_nodes)), key=lambda i: abs(op_nodes[i].x - 997) + abs(op_nodes[i].y - 476))
        t4_bot = min(range(len(op_nodes)), key=lambda i: abs(op_nodes[i].x - 997) + abs(op_nodes[i].y - 584))
        t5_elite = min(range(len(op_nodes)), key=lambda i: abs(op_nodes[i].x - 1161) + abs(op_nodes[i].y - 476))
        t5_bot = min(range(len(op_nodes)), key=lambda i: abs(op_nodes[i].x - 1161) + abs(op_nodes[i].y - 584))
        self.assertIn((t4_mid, t5_bot), op_edges)
        self.assertNotIn((t4_bot, t5_elite), op_edges)

        # Small 2-node (1-edge) and 1-tier (0-edge) Floor 3 maps still produce valid plans.
        n0 = route.RouteNode(340, 370, route.KIND_EVENT)
        n1 = route.RouteNode(504, 370, route.KIND_REST)
        n0.tier, n1.tier = 0, 1
        two_plan = route.plan([n0, n1], style=route.ROUTE_EVENT, edges=[(0, 1)])
        self.assertEqual([e[0]['kind'] for e in two_plan], ['event', 'rest'])
        single_plan = route.plan([n0], style=route.ROUTE_EVENT, edges=[])
        self.assertEqual([e[0]['kind'] for e in single_plan], ['event'])

        # Unambiguous unique kind resolves when an extra branch differs, while ambiguous copies stay None.
        rest_card = route.RouteCard(970, 114, route.KIND_REST, 60, 100)
        ev_card = route.RouteCard(1150, 312, route.KIND_EVENT, 60, 100)
        entry = {'kind': route.KIND_REST, 'choices': [route.KIND_REST, route.KIND_REST, route.KIND_EVENT],
                 'choice_index': 0}
        self.assertIs(route.planned_card([rest_card, ev_card], entry), rest_card)

        # Platform glow bordering an orange rest card (308x247 merged) is opened away cleanly.
        glow = np.zeros((720, 1280, 3), dtype=np.uint8)
        glow[255:371, 1129:1175] = (230, 145, 50)
        glow[340:344, 860:1150] = (230, 145, 50)
        glow[340:470, 860:864] = (230, 145, 50)
        glow_cards = route.read_cards(glow)
        self.assertEqual([(c.kind, c.x, c.y) for c in glow_cards], [('rest', 1152, 312)])

        # Mismatch dump safely saves 2d/3d frames without KeyError on log_retention.
        with TemporaryDirectory() as folder:
            dump_task = ChaoszeroRogue.__new__(ChaoszeroRogue)
            dump_task.device = SimpleNamespace(image=glow)
            dump_task.route_last_preview = glow
            with patch.object(rogue, 'prune_diagnostics') as mock_prune:
                dump_task.rogue_dump_route_mismatch()
                mock_prune.assert_called_once()
            # Also call real prune_diagnostics on 'route' directly.
            rogue.prune_diagnostics(folder, 'route')

    def test_grid_recovers_top_left_event_under_cyan_highlight_strip(self):
        image = capture('rogue_route_glowing_preview.png')
        # Add a bright cyan event diamond at top-left (341, 152) merged into a vertical cyan highlight band,
        # plus a white connector from the pin (178, 473) -> (341, 152), mimicking live 041606/043751/233439.
        cv2.rectangle(image, (285, 92), (398, 225), (28, 128, 155), -1)
        diamond = np.array([[341, 130], [385, 152], [341, 174], [297, 152]], dtype=np.int32)
        cv2.fillConvexPoly(image, diamond, (42, 195, 225))
        cv2.putText(image, '?', (333, 162), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (245, 245, 245), 3)
        cv2.line(image, (178 + route.EDGE_TIP_X, 473 + route.EDGE_TIP_Y),
                 (341 - route.EDGE_TIP_X, 152 + route.EDGE_TIP_Y), (235, 235, 235), 2)

        nodes = route.read_nodes(image)
        tier0 = sorted((n for n in nodes if n.tier == 0), key=lambda n: n.y)
        self.assertEqual([(n.x, n.y, n.kind) for n in tier0], [
            (341, 152, route.KIND_EVENT),
            (341, 368, route.KIND_EVENT),
            (341, 476, route.KIND_ELITE),
            (341, 584, route.KIND_EVENT),
        ])

    def test_read_cards_distinguishes_beacon_from_rest_and_clipped_top_cards(self):
        rest_tpl = cv2.cvtColor(cv2.imread(route.ICON_REST_FILE), cv2.COLOR_BGR2RGB)
        beacon_tpl = cv2.cvtColor(cv2.imread(route.ICON_BEACON_FILE), cv2.COLOR_BGR2RGB)
        canvas = np.zeros((720, 1280, 3), dtype=np.uint8)

        # Clipped top-slot beacon card (y1=82..159 -> h=77) and full-height rest card at right slot.
        # Paint only bright icon pixels onto solid orange so the card area stays above CARD_AREA_MIN.
        canvas[82:159, 948:993] = (220, 125, 45)
        bmask = beacon_tpl > 165
        canvas[98:142, 949:993][bmask] = beacon_tpl[bmask]
        canvas[255:371, 1129:1175] = (220, 125, 45)
        rmask = rest_tpl > 165
        canvas[291:335, 1130:1174][rmask] = rest_tpl[rmask]

        cards = route.read_cards(canvas)
        self.assertEqual(
            [(c.kind, c.x) for c in sorted(cards, key=lambda c: c.y)],
            [(route.KIND_BEACON, 970), (route.KIND_REST, 1152)],
        )

    def test_route_mismatch_rereads_once_per_step_then_falls_back(self):
        task = ChaoszeroRogue.__new__(ChaoszeroRogue)
        task.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8))
        task.core_started = False
        task.route_step = 3
        task.plan_index = 0
        task.route_reads = 1
        task.route_mismatch = None
        task.route_reread_step = None
        task.route_plan = [[{'kind': route.KIND_EVENT, 'choices': [route.KIND_EVENT, route.KIND_EVENT],
                             'choice_index': 0}]]
        task.rogue_dump_route_mismatch = Mock()
        task.rogue_route_style = Mock(return_value=route.ROUTE_EVENT)
        task.rogue_route_state = Mock(return_value={})

        live = [
            route.RouteCard(971, 115, route.KIND_REST, 46, 116),
            route.RouteCard(1152, 311, route.KIND_BATTLE, 46, 116),
        ]

        # First sight records mismatch for 1-frame debounce.
        self.assertEqual(task.rogue_route_choose_card(live), (None, True))
        task.rogue_dump_route_mismatch.assert_not_called()

        # Second sight confirms mismatch, triggers ONE re-read for (core_started=False, route_step=3).
        self.assertEqual(task.rogue_route_choose_card(live), (None, True))
        task.rogue_dump_route_mismatch.assert_called_once()
        self.assertIsNone(task.route_plan)
        self.assertEqual(task.route_reread_step, (False, 3))

        # Suppose re-reading still produced a mismatched plan on the same step with route_reads < ROUTE_READS:
        # must NOT discard & re-read a second time in place — should fall back to best_card.
        task.route_plan = [[{'kind': route.KIND_EVENT, 'choices': [route.KIND_EVENT], 'choice_index': 0}]]
        self.assertEqual(task.rogue_route_choose_card(live), (None, True))  # 1-frame debounce
        chosen, reread = task.rogue_route_choose_card(live)
        self.assertFalse(reread)
        self.assertIs(chosen, live[0])
        self.assertIsNone(task.route_plan)


if __name__ == '__main__':
    unittest.main()
