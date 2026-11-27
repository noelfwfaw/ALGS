import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, call, patch

import numpy as np
from PIL import Image

from module.config import server


SCREENSHOT_DIR = os.environ.get('RESONANCE_WILDERNESS_RECYCLE_SCREENSHOT_DIR')
SCREENSHOT_NAMES = (
    'MuMu-20261127-134944-873.png',
    'MuMu-20261127-135009-014.png',
    'MuMu-20261127-135015-109.png',
    'MuMu-20261127-135020-127.png',
)


class TestWildernessRecyclePersistence(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')
        global wilderness_recycle
        from module.resonance import wilderness_recycle

    def test_state_is_isolated_by_config_and_resets_at_five(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'state.json')
            before_reset = datetime(2026, 11, 27, 4, 59, 59)
            after_reset = datetime(2026, 11, 27, 5, 0, 0)

            wilderness_recycle.mark_garbage_cleaned('config-a', path=path, now=before_reset)
            self.assertTrue(wilderness_recycle.is_garbage_cleaned_today(
                'config-a', path=path, now=after_reset - timedelta(seconds=1)))
            self.assertFalse(wilderness_recycle.is_garbage_cleaned_today(
                'config-a', path=path, now=after_reset))
            self.assertFalse(wilderness_recycle.is_garbage_cleaned_today(
                'config-b', path=path, now=before_reset))

            wilderness_recycle.mark_garbage_cleaned('config-b', path=path, now=after_reset)
            self.assertTrue(wilderness_recycle.is_garbage_cleaned_today(
                'config-b', path=path, now=after_reset))
            self.assertFalse(wilderness_recycle.is_garbage_cleaned_today(
                'config-a', path=path, now=after_reset))

    def test_corrupt_state_is_not_a_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'state.json')
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write('{broken')
            self.assertFalse(wilderness_recycle.is_garbage_cleaned_today('config-a', path=path))
            wilderness_recycle.mark_garbage_cleaned('config-a', path=path)
            self.assertTrue(wilderness_recycle.is_garbage_cleaned_today('config-a', path=path))


class TestWildernessRecycleFlow(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')
        global wilderness_recycle
        from module.resonance import wilderness_recycle
        reward_match = patch.object(wilderness_recycle.assets.LOGIN_REWARD, 'match',
                                    side_effect=lambda image, **kwargs: image == 'reward')
        reward_match.start()
        self.addCleanup(reward_match.stop)

    def make_task(self, initial='main', loop_count=12, npc_visible=True, quantity=317,
                  city_ready=True, dialog_ready=True, npc_transition=False):
        task = wilderness_recycle.ResonanceWildernessRecycle.__new__(
            wilderness_recycle.ResonanceWildernessRecycle)
        state = {'image': initial}
        task.device = Mock()
        task.device.image = state['image']
        task.ui_ensure = Mock()
        task.interval_reset = Mock()

        def frames():
            transition_seen = False
            for _ in range(loop_count):
                if npc_transition and state['image'] == 'city_transition':
                    if transition_seen:
                        state['image'] = 'menu'
                        task.device.image = 'menu'
                    transition_seen = True
                yield None

        task.loop = Mock(side_effect=[frames(), frames()])
        task.handle_reward_popup = Mock(side_effect=lambda: self._change_state(
            state, task, 'reward', 'panel', True))
        task.appear = Mock(side_effect=lambda button, **kwargs: self._appear(state['image'], button))
        task.ui_page_appear = Mock(side_effect=lambda page, **kwargs: (
            (page is wilderness_recycle.page_main and state['image'] == 'main')
            or (page is wilderness_recycle.page_resonance_city
                and state['image'] in ('city', 'city_transition'))))
        task.image_color_count = Mock(side_effect=lambda button, *args, **kwargs: (
            (button is wilderness_recycle.CITY_GARBAGE_NPC_CHECK and npc_visible)
            or button is wilderness_recycle.RECYCLE_ALL_CHECK))

        def click(button):
            target = {
                wilderness_recycle.CITY_GARBAGE_NPC: 'city_transition' if npc_transition else 'menu',
                wilderness_recycle.RECYCLE_OPTION: 'panel',
                wilderness_recycle.RECYCLE_ALL: 'reward',
            }[button]
            self._change_state(state, task, None, target, False)

        def navigate(button, **kwargs):
            target = {
                wilderness_recycle.assets.MAIN_VISIT_CITY: 'city',
                wilderness_recycle.assets.DAILY_HOME: 'main',
                wilderness_recycle.assets.OP_BACK: 'menu' if state['image'] == 'panel' else 'city',
            }[button]
            self._change_state(state, task, None, target, True)

        task.device.click = Mock(side_effect=click)
        task.appear_then_click = Mock(side_effect=navigate)
        task._garbage_npc_visible = Mock(return_value=npc_visible)
        task._is_wilderness_city = Mock(side_effect=lambda image: city_ready and image == 'city')
        task._is_recycle_dialog = Mock(side_effect=lambda image: dialog_ready and image == 'menu')
        task._is_recycle_dialog_layout = Mock(return_value=False)
        task._recycle_panel_quantity = Mock(side_effect=lambda image: quantity if image == 'panel' else None)
        return task

    @staticmethod
    def _change_state(state, task, current, target, handled):
        same = current is None or state['image'] is current
        if not same and not isinstance(current, np.ndarray) and not isinstance(state['image'], np.ndarray):
            same = state['image'] == current
        if same:
            state['image'] = target
            task.device.image = target
            return handled
        return False

    @staticmethod
    def _appear(image, button):
        if button is wilderness_recycle.assets.LOGIN_REWARD:
            return image == 'reward'
        if button is wilderness_recycle.assets.MAIN_VISIT_CITY:
            return image == 'main'
        if button is wilderness_recycle.assets.DAILY_HOME:
            return image == 'city'
        if button is wilderness_recycle.assets.OP_BACK:
            return image in ('city', 'menu', 'panel')
        return False

    def read_digits(self, ocr, image):
        if ocr is wilderness_recycle.POPUP_REWARD_OCR:
            return 79250
        if ocr is wilderness_recycle.PANEL_REWARD_OCR:
            return 79250
        return None

    def test_reward_confirmation_returns_true_only_after_main(self):
        task = self.make_task()
        with patch.object(wilderness_recycle, '_read_digits', side_effect=self.read_digits):
            self.assertTrue(task.recycle_wilderness_garbage())
        self.assertEqual(task.device.click.call_args_list, [
            call(wilderness_recycle.CITY_GARBAGE_NPC),
            call(wilderness_recycle.RECYCLE_OPTION),
            call(wilderness_recycle.RECYCLE_ALL),
        ])
        self.assertEqual(task.appear_then_click.call_args_list, [
            call(wilderness_recycle.assets.MAIN_VISIT_CITY, offset=wilderness_recycle.OFFSET, interval=2),
            call(wilderness_recycle.assets.OP_BACK, offset=wilderness_recycle.OFFSET, interval=2),
            call(wilderness_recycle.assets.OP_BACK, offset=wilderness_recycle.OFFSET, interval=2),
            call(wilderness_recycle.assets.DAILY_HOME, offset=wilderness_recycle.OFFSET, interval=2),
        ])

    def test_city_residual_after_npc_waits_for_recycle_menu(self):
        task = self.make_task(npc_transition=True)
        with patch.object(wilderness_recycle, '_read_digits', side_effect=self.read_digits):
            self.assertTrue(task.recycle_wilderness_garbage())
        self.assertEqual(task.device.click.call_args_list, [
            call(wilderness_recycle.CITY_GARBAGE_NPC),
            call(wilderness_recycle.RECYCLE_OPTION),
            call(wilderness_recycle.RECYCLE_ALL),
        ])
        self.assertEqual(task.device.click.call_args_list.count(call(wilderness_recycle.RECYCLE_ALL)), 1)
        self.assertEqual(task._is_wilderness_city.call_args_list, [call('city')])
        self.assertIn(call('city_transition'), task._is_recycle_dialog.call_args_list)

    def test_zero_inventory_is_confirmed_without_recycle_click(self):
        task = self.make_task(quantity=0)
        self.assertTrue(task.recycle_wilderness_garbage())
        self.assertEqual(task.device.click.call_args_list, [
            call(wilderness_recycle.CITY_GARBAGE_NPC),
            call(wilderness_recycle.RECYCLE_OPTION),
        ])

    def test_missing_npc_times_out_without_clicking_other_objects(self):
        task = self.make_task(loop_count=2, npc_visible=False)
        self.assertFalse(task.recycle_wilderness_garbage())
        task.device.click.assert_not_called()
        self.assertEqual(task.appear_then_click.call_args_list, [
            call(wilderness_recycle.assets.MAIN_VISIT_CITY, offset=wilderness_recycle.OFFSET, interval=2),
            call(wilderness_recycle.assets.DAILY_HOME, offset=wilderness_recycle.OFFSET, interval=2),
        ])

    def test_wrong_city_returns_false_without_entering_recycle(self):
        task = self.make_task(city_ready=False)
        self.assertFalse(task.recycle_wilderness_garbage())
        task.device.click.assert_not_called()

    def test_unconfirmed_reward_does_not_resubmit(self):
        task = self.make_task(loop_count=5)

        def read_digits(ocr, image):
            if ocr is wilderness_recycle.POPUP_REWARD_OCR:
                return None
            return self.read_digits(ocr, image)

        with patch.object(wilderness_recycle, '_read_digits', side_effect=read_digits):
            self.assertFalse(task.recycle_wilderness_garbage())
        self.assertEqual(task.device.click.call_args_list.count(call(wilderness_recycle.RECYCLE_ALL)), 1)

    def test_unrecognized_screen_raises_instead_of_blindly_navigating(self):
        task = self.make_task(initial='unknown', loop_count=1)
        with self.assertRaises(wilderness_recycle.GamePageUnknownError):
            task.recycle_wilderness_garbage()
        task.device.click.assert_not_called()
        task.appear_then_click.assert_not_called()

    def test_empty_or_non_digit_ocr_is_unknown_not_zero(self):
        task = wilderness_recycle.ResonanceWildernessRecycle.__new__(
            wilderness_recycle.ResonanceWildernessRecycle)
        with patch.object(wilderness_recycle.PANEL_LABEL_OCR, 'ocr', return_value='当前垃圾数量'), \
                patch.object(wilderness_recycle.GARBAGE_COUNT_OCR, 'ocr') as count:
            for raw in ('', 'O', '-', '?', '12x'):
                with self.subTest(raw=raw):
                    count.return_value = raw
                    self.assertIsNone(task._recycle_panel_quantity(object()))
            count.return_value = '0'
            self.assertEqual(task._recycle_panel_quantity(object()), 0)


class TestWildernessRecycleReplay(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')
        global wilderness_recycle
        from module.resonance import wilderness_recycle

    def screens(self):
        if not SCREENSHOT_DIR or not os.path.isdir(SCREENSHOT_DIR):
            self.skipTest('Set RESONANCE_WILDERNESS_RECYCLE_SCREENSHOT_DIR to replay the original screenshots')
        try:
            return tuple(np.asarray(Image.open(os.path.join(SCREENSHOT_DIR, name)).convert('RGB'))
                         for name in SCREENSHOT_NAMES)
        except FileNotFoundError:
            self.skipTest('Original wilderness recycle screenshots are unavailable')

    def test_original_screens_identify_each_gate_and_amount(self):
        city, menu, panel, reward = self.screens()
        task = wilderness_recycle.ResonanceWildernessRecycle.__new__(
            wilderness_recycle.ResonanceWildernessRecycle)
        task.device = Mock(image=city)
        click_area = wilderness_recycle.CITY_GARBAGE_NPC.button
        click_center = ((click_area[0] + click_area[2]) // 2, (click_area[1] + click_area[3]) // 2)
        self.assertEqual(click_center, (326, 115))
        self.assertTrue(task._garbage_npc_visible())
        for image in (menu, panel, reward):
            task.device.image = image
            self.assertFalse(task._garbage_npc_visible())
        self.assertTrue(task._is_wilderness_city(city))
        self.assertTrue(task._is_recycle_dialog(menu))
        task.device.image = panel
        self.assertEqual(task._recycle_panel_quantity(panel), 317)
        self.assertEqual(wilderness_recycle._read_digits(wilderness_recycle.PANEL_REWARD_OCR, panel), 79250)
        self.assertEqual(wilderness_recycle._read_digits(wilderness_recycle.POPUP_REWARD_OCR, reward), 79250)
        self.assertTrue(wilderness_recycle.assets.LOGIN_REWARD.match(reward, offset=wilderness_recycle.OFFSET))
        self.assertFalse(wilderness_recycle.assets.LOGIN_REWARD.match(city, offset=wilderness_recycle.OFFSET))

    def test_original_screen_replay_completes_without_resubmission(self):
        city, menu, panel, reward = self.screens()
        main = np.zeros((720, 1280, 3), dtype=np.uint8)
        task = wilderness_recycle.ResonanceWildernessRecycle.__new__(
            wilderness_recycle.ResonanceWildernessRecycle)
        state = {'image': main}
        task.device = Mock()
        task.device.image = state['image']
        task.ui_ensure = Mock()
        task.interval_reset = Mock()
        task.loop = Mock(return_value=iter(range(20)))
        task.appear = Mock(side_effect=lambda button, **kwargs: (
            (button is wilderness_recycle.assets.LOGIN_REWARD and state['image'] is reward)
            or (button is wilderness_recycle.assets.MAIN_VISIT_CITY and state['image'] is main)
            or (button is wilderness_recycle.assets.DAILY_HOME and state['image'] is city)
            or (button is wilderness_recycle.assets.OP_BACK
                and any(state['image'] is frame for frame in (city, menu, panel)))))
        task.ui_page_appear = Mock(side_effect=lambda page, **kwargs: (
            (page is wilderness_recycle.page_main and state['image'] is main)
            or (page is wilderness_recycle.page_resonance_city and state['image'] is city)))
        def click(button):
            target = {
                wilderness_recycle.CITY_GARBAGE_NPC: menu,
                wilderness_recycle.RECYCLE_OPTION: panel,
                wilderness_recycle.RECYCLE_ALL: reward,
                wilderness_recycle.assets.LOGIN_REWARD: panel,
            }[button]
            TestWildernessRecycleFlow._change_state(state, task, None, target, False)

        def navigate(button, **kwargs):
            if button is wilderness_recycle.assets.LOGIN_REWARD:
                matched = wilderness_recycle.assets.LOGIN_REWARD.match(
                    state['image'], offset=kwargs.get('offset', wilderness_recycle.OFFSET))
                if not matched:
                    return False
                task.device.click(button)
                return True
            if button is wilderness_recycle.assets.MAIN_VISIT_CITY:
                target = city
            elif button is wilderness_recycle.assets.OP_BACK:
                target = menu if state['image'] is panel else city
            else:
                target = main
            TestWildernessRecycleFlow._change_state(state, task, None, target, True)

        task.device.click = Mock(side_effect=click)
        task.appear_then_click = Mock(side_effect=navigate)
        self.assertTrue(task.recycle_wilderness_garbage())
        self.assertEqual(task.device.click.call_args_list, [
            call(wilderness_recycle.CITY_GARBAGE_NPC),
            call(wilderness_recycle.RECYCLE_OPTION),
            call(wilderness_recycle.RECYCLE_ALL),
            call(wilderness_recycle.assets.LOGIN_REWARD),
        ])
        for args, kwargs in task.appear.call_args_list:
            if args and args[0] is wilderness_recycle.assets.LOGIN_REWARD:
                self.assertNotEqual(kwargs.get('offset'), wilderness_recycle.OFFSET)


if __name__ == '__main__':
    unittest.main()
