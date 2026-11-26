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

    def test_starts_battle_with_wide_start_button(self):
        import os
        import numpy as np
        from PIL import Image
        from module.resonance import assets
        from module.resonance.operations import ResonanceOperations

        detail_wide = load_image(assets.OP_START_WIDE.file).copy()
        x1, y1, x2, y2 = assets.OP_DETAIL.area
        detail_wide[y1:y2, x1:x2] = load_image(assets.OP_DETAIL.file, assets.OP_DETAIL.area)
        team = load_image(assets.OP_TEAM.file) + load_image(assets.OP_TEAM_START.file)
        pause = load_image(assets.OP_PAUSE.file)

        task = ResonanceOperations.__new__(ResonanceOperations)
        task.device = Mock()
        task.interval_timer = {}
        frames = iter([detail_wide, team, pause])
        task.device.screenshot.side_effect = lambda: setattr(task.device, 'image', next(frames))
        with patch('module.base.timer.time', side_effect=count(100, 3.0)):
            task.start_battle()
        self.assertEqual(
            task.device.click.call_args_list,
            [call(assets.OP_START_WIDE), call(assets.OP_TEAM_START)],
        )

        shot = 'C:/Users/14494/Documents/MuMu共享文件夹/Screenshots/MuMu-20261126-141510-589.png'
        if os.path.exists(shot):
            im = np.array(Image.open(shot).convert('RGB'))
            self.assertTrue(assets.OP_DETAIL.match(im, offset=(5, 5)))
            self.assertFalse(assets.OP_START.match(im, offset=(5, 5)))
            self.assertTrue(assets.OP_START_WIDE.match(im, offset=(120, 15)))

    def test_operations_clarity_prompt_cancel_and_recover(self):
        from dev_tools.test_resonance_clarity import _blank_with, make_clarity_confirm_modal, make_clarity_recovery_screen
        from module.resonance import assets
        from module.resonance.operations import ResonanceOperations

        detail_wide = load_image(assets.OP_START_WIDE.file).copy()
        x1, y1, x2, y2 = assets.OP_DETAIL.area
        detail_wide[y1:y2, x1:x2] = load_image(assets.OP_DETAIL.file, assets.OP_DETAIL.area)
        prompt = _blank_with(assets.CLARITY_PROMPT, assets.CLARITY_PROMPT_CANCEL, assets.CLARITY_PROMPT_CONFIRM)
        page_full = make_clarity_recovery_screen(has_lollipop=True, has_gum=True, has_cactus=False)
        confirm = make_clarity_confirm_modal()
        team = load_image(assets.OP_TEAM.file) + load_image(assets.OP_TEAM_START.file)
        pause = load_image(assets.OP_PAUSE.file)

        # Case 1: UseClarityItem='none' -> cancels prompt and aborts run cleanly
        task1 = ResonanceOperations.__new__(ResonanceOperations)
        task1.device = Mock()
        task1.config = Mock()
        task1.config.ResonanceOperations_SiegeRuns = 1
        task1.config.ResonanceOperations_SiegeStage = 'Large'
        task1.config.ResonanceOperations_SupplyRuns = 0
        task1.config.ResonanceOperations_SupplyStage = 'Auto'
        task1.config.ResonanceOperations_WeeklyRuns = 0
        task1.config.ResonanceOperations_UseClarityItem = 'none'
        task1.interval_timer = {}
        task1.ui_ensure = Mock()
        task1.ui_goto_main = Mock()
        task1.select_category = Mock()
        task1.read_remaining = Mock(return_value=3)
        task1.find_stage = Mock(return_value=('Large', {'Large'}))
        task1.wait_for_victory = Mock()

        frames1 = iter([detail_wide, prompt, detail_wide])
        task1.device.screenshot.side_effect = lambda: setattr(task1.device, 'image', next(frames1))
        with patch('module.base.timer.time', side_effect=count(100, 3.0)):
            task1.run()
        clicked1 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task1.device.click.call_args_list]
        self.assertEqual(clicked1, ['OP_START_WIDE', 'CLARITY_PROMPT_CANCEL'])
        task1.wait_for_victory.assert_not_called()
        task1.ui_goto_main.assert_called_once()

        # Case 2: UseClarityItem='lollipop' -> uses item, retries start, enters battle
        task2 = ResonanceOperations.__new__(ResonanceOperations)
        task2.device = Mock()
        task2.config = Mock()
        task2.config.ResonanceOperations_UseClarityItem = 'lollipop'
        task2.interval_timer = {}
        frames2 = iter([detail_wide, prompt, page_full, confirm, page_full, detail_wide, detail_wide, team, pause])
        task2.device.screenshot.side_effect = lambda: setattr(task2.device, 'image', next(frames2))
        with patch('module.resonance.clarity.read_clarity_fraction', return_value=(17, 358)), \
             patch('module.resonance.clarity.CLARITY_CNT_OCR.ocr', side_effect=[['24'], ['40']]), \
             patch('module.resonance.clarity.FATIGUE_CONFIRM_QTY_OCR.ocr', return_value='1/10'), \
             patch('module.base.timer.time', side_effect=count(100, 3.0)):
            self.assertEqual(task2.start_battle(), 'started')
        clicked2 = [getattr(c[0][0], 'name', str(c[0][0])) for c in task2.device.click.call_args_list]
        self.assertEqual(
            clicked2,
            [
                'OP_START_WIDE', 'CLARITY_PROMPT_CONFIRM', 'CLARITY_ITEM_LOLLIPOP',
                'FATIGUE_CONFIRM_OK', 'OP_BACK', 'OP_START_WIDE', 'OP_TEAM_START',
            ],
        )
