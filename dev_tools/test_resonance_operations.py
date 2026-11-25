import unittest
from itertools import count
from unittest.mock import Mock, call, patch

from module.base.utils import load_image
from module.config import server
from module.exception import GameStuckError


class TestResonanceOperations(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def test_supply_selects_configured_open_card(self):
        from module.resonance import assets
        from module.resonance.operations import ResonanceOperations

        task = ResonanceOperations.__new__(ResonanceOperations)
        task.device = Mock()
        frame = load_image(assets.OP_HUB.file)
        frame[403:431, 447:572] = assets.TEMPLATE_OP_ELEGANT.image
        frame[403:431, 721:844] = assets.TEMPLATE_OP_STANDARD.image
        frame[403:431, 991:1117] = assets.TEMPLATE_OP_SALVATION.image
        frame[581:618, 445:565] = assets.TEMPLATE_OP_ENTER.image
        frame[581:618, 718:838] = assets.TEMPLATE_OP_ENTER.image
        task.device.image = frame

        chosen, seen = task.find_stage('supply', 'Standard')
        self.assertEqual(chosen, 'Standard')
        self.assertEqual(seen, {'Elegant', 'Standard'})
        self.assertEqual(task.device.click.call_args[0][0].button, (718, 581, 838, 618))
        task.device.swipe.assert_not_called()

    def test_starts_real_battle_and_enables_auto_only_if_off(self):
        from module.resonance import assets
        from module.resonance.operations import ResonanceOperations

        detail = load_image(assets.OP_DETAIL.file) + load_image(assets.OP_START.file)
        team = load_image(assets.OP_TEAM.file) + load_image(assets.OP_TEAM_START.file)
        off = load_image(assets.OP_PAUSE.file) + load_image(assets.OP_AUTO_OFF.file)
        on = load_image(assets.OP_PAUSE.file) + load_image(assets.OP_AUTO_ON.file)
        fading_auto = load_image(assets.OP_PAUSE.file) + load_image(assets.OP_AUTO_ON.file) // 2
        dimmed_next = load_image(assets.OP_NEXT.file) // 7
        self.assertTrue(assets.OP_NEXT.match(dimmed_next, offset=(6, 6)))
        victory = load_image(assets.OP_WIN.file) + load_image(assets.OP_NEXT.file)
        for combat, clicks in (
            ([off, off, off, on], [assets.OP_AUTO_OFF]),
            ([on], []),
        ):
            with self.subTest(auto_initially_off=bool(clicks)):
                task = ResonanceOperations.__new__(ResonanceOperations)
                task.device = Mock()
                task.interval_timer = {}
                frames = iter([detail, team] + combat + [fading_auto] * 4 + [dimmed_next, victory // 7, victory])

                def screenshot():
                    task.device.image = next(frames)

                task.device.screenshot.side_effect = screenshot
                with patch('module.base.timer.time', side_effect=count(100, 0.6)):
                    task.start_battle()
                    task.wait_for_victory()
                    self.assertTrue(task.handle_operation_victory())
                self.assertIs(task.device.image, victory)
                self.assertEqual(task.device.click.call_args_list, [
                    call(button) for button in [assets.OP_START, assets.OP_TEAM_START] + clicks + [assets.OP_NEXT]
                ])

    def test_uses_remaining_attempts_as_weekly_budget(self):
        from module.resonance.operations import ResonanceOperations

        task = ResonanceOperations.__new__(ResonanceOperations)
        task.select_category = Mock()
        task.ui_ensure = Mock()
        task.find_stage = Mock(return_value=('Blind_Box', {'Blind_Box'}))
        task.start_battle = Mock()
        task.wait_for_victory = Mock()
        task.read_remaining = Mock(return_value=2)
        task.run_category('weekly', 1, 'Blind_Box')
        task.start_battle.assert_not_called()
        task.read_remaining.side_effect = [2, 1]
        task.run_category('weekly', 2, 'Blind_Box')
        task.start_battle.assert_called_once_with()
        task.read_remaining.side_effect = [2, 2]
        with self.assertRaises(GameStuckError):
            task.run_category('weekly', 3, 'Blind_Box')
        self.assertEqual(task.start_battle.call_count, 2)

    def test_supply_uses_the_only_open_stage_when_preference_is_closed(self):
        from module.resonance.operations import ResonanceOperations

        task = ResonanceOperations.__new__(ResonanceOperations)
        task.select_category = Mock()
        task.ui_ensure = Mock()
        task.start_battle = Mock()
        task.wait_for_victory = Mock()
        task.read_remaining = Mock(side_effect=[3, 2])
        task.find_stage = Mock(side_effect=[(None, {'Elegant'}), ('Elegant', {'Elegant'})])
        task.run_category('supply', 1, 'Magic')
        self.assertEqual(task.find_stage.call_args_list, [call('supply', 'Magic'), call('supply', 'Elegant')])
        task.start_battle.assert_called_once_with()
