"""Removal regressions. Run: toolkit/python.exe -m unittest dev_tools.test_rogue_remove."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
from PIL import Image

from module.config.server import set_server

set_server('chaoszero')

from module.base.timer import Timer
from module.chaoszero.assets import ROGUE_FLASH_DETAIL, ROGUE_REMOVE_DONE, ROGUE_REMOVE_SKIP
from module.chaoszero.rogue import (ChaoszeroRogue, REMOVE_CARD_WIDTH, REMOVE_GRID_COLS,
                                     REMOVE_MAX_TRIES, REMOVE_SCROLL_TIMES,
                                     REMOVE_STILL_THRESHOLD)
from module.chaoszero.rogue_cards import CardReader
from module.exception import TaskFailed


def make_task():
    task = ChaoszeroRogue.__new__(ChaoszeroRogue)
    task.device = SimpleNamespace(image=np.zeros((720, 1280, 3), dtype=np.uint8),
                                  stuck_record_add=Mock(), drag=Mock(),
                                  click_record_clear=Mock())
    task.card_reader = None
    task.rogue_remove_appear = Mock(return_value=True)
    task.wait_until_still = Mock(return_value=True)
    task.remove_stage = 0
    task.remove_target = None
    task.remove_tries = 0
    task.remove_cancel_tries = 0
    task.remove_done = 0
    task.remove_skip_node = None
    task.core_started = False
    task.route_step = 4
    task.remove_wait = Timer(6, count=1)
    task.tap_point = Mock()
    task.rogue_state_save = Mock()
    task.rogue_card_page_record = Mock()
    task.rogue_dump_unknown = Mock()
    task.rogue_detail_appear = Mock(return_value=False)
    task.rogue_delete_times = Mock(return_value=3)
    return task


def expire(task):
    task.remove_wait._start = 1
    task.remove_wait._access = task.remove_wait.count + 1


class RemovalPriorityTest(unittest.TestCase):
    def pick(self, texts):
        task = make_task()
        points = [(450 + i * 210, 220, 82, 360 + i * 210, 188, 280)
                  for i in range(len(texts))]
        task.rogue_flash_card_points = Mock(return_value=points)
        # The grid keeps the same cards after a scroll, so repeat the last read.
        reads = iter(texts)
        task.card_reader = SimpleNamespace(
            read_name=Mock(side_effect=lambda *args, **kwargs: next(reads, texts[-1] if texts else '')))
        result = task.rogue_remove_pick()
        if result is not None:
            # A hit on the first screen reads each box exactly once.
            self.assertEqual(task.card_reader.read_name.call_count, len(texts))
        return result

    def test_lower_score_sword_curtain_beats_first_two_sword_lights(self):
        result = self.pick(['劍光', '劍光', '劍幕工社作會', '劍之雨'])
        self.assertEqual(result[:2], ((870, 220), '劍幕'))

    def test_priority_does_not_depend_on_card_order(self):
        for texts, index in ((['劍光', '劍幕'], 1), (['劍幕', '劍光'], 0)):
            with self.subTest(texts=texts):
                self.assertEqual(self.pick(texts)[:2], ((450 + index * 210, 220), '劍幕'))

    def test_sword_light_only_when_no_sword_curtain_is_recognized(self):
        self.assertEqual(self.pick(['劍之雨', '劍光'])[:2], ((660, 220), '劍光'))

    def test_similar_incomplete_names_are_never_deleted(self):
        self.assertIsNone(self.pick(['劍市', '一縷光芒', '劍之雨', '劍', '']))

    def test_no_detected_boxes_has_no_fixed_slot_fallback(self):
        self.assertIsNone(self.pick([]))


class RemovalScrollTest(unittest.TestCase):
    POINT = (450, 220, 82, 360, 188, 280)

    def pick(self, pages):
        task = make_task()
        task.rogue_flash_card_points = Mock(return_value=[self.POINT])
        task.card_reader = SimpleNamespace(
            read_name=Mock(side_effect=[text for page in pages for text in page]))
        return task, task.rogue_remove_pick()

    def test_target_below_first_screen_is_found_after_one_scroll(self):
        task, picked = self.pick([['一縷光芒'], ['劍幕']])
        self.assertEqual(picked[:2], ((450, 220), '劍幕'))
        self.assertEqual(task.device.drag.call_count, 1)
        self.assertEqual(task.device.drag.call_args[1]['name'], 'ROGUE_REMOVE_SCROLL')
        task.device.click_record_clear.assert_called_once()

    def test_missing_target_has_bounded_scrolls(self):
        task, picked = self.pick([['一縷光芒'], ['展開極光'], ['萬人的英雄'], ['水之根源']])
        self.assertIsNone(picked)
        self.assertEqual(task.device.drag.call_count, REMOVE_SCROLL_TIMES)

    def test_page_gone_or_still_moving_after_scroll_is_not_clicked(self):
        for attribute in ('rogue_remove_appear', 'wait_until_still'):
            with self.subTest(attribute=attribute):
                task = make_task()
                task.rogue_flash_card_points = Mock(return_value=[self.POINT])
                task.card_reader = SimpleNamespace(read_name=Mock(return_value='一縷光芒'))
                setattr(task, attribute, Mock(return_value=False))
                self.assertIsNone(task.rogue_remove_pick())
                self.assertEqual(task.device.drag.call_count, 1)
                task.tap_point.assert_not_called()


class RemovalFlowTest(unittest.TestCase):
    def test_cancel_skips_only_this_shop_node_without_consuming_quota(self):
        task = make_task()
        task.remove_done = 1
        self.assertTrue(task.rogue_shop_remove_needed())
        task.rogue_remove_cancel()
        self.assertEqual(task.remove_done, 1)
        self.assertFalse(task.rogue_shop_remove_needed())
        task.rogue_state_save.assert_not_called()
        task.rogue_remove_reset()
        self.assertFalse(task.rogue_shop_remove_needed())
        task.core_started = True
        self.assertTrue(task.rogue_shop_remove_needed())
        task.core_started = False
        task.route_step += 1
        self.assertTrue(task.rogue_shop_remove_needed())
        task.remove_done = 3
        self.assertFalse(task.rogue_shop_remove_needed())

    def setUp(self):
        self.task = make_task()
        self.task.appear = Mock(return_value=False)
        self.task.rogue_remove_appear = Mock(return_value=True)
        self.task.rogue_remove_ready = Mock(return_value=None)
        self.target = ((877, 218), '劍幕', 0.75, '劍幕工社作會')
        self.task.rogue_remove_pick = Mock(return_value=self.target)

    def step(self):
        return self.task.handle_rogue_remove(Timer(0))

    def select(self):
        self.assertTrue(self.step())
        self.task.tap_point.assert_called_once_with(877, 218, name='ROGUE_REMOVE_CARD')
        self.assertEqual(self.task.remove_done, 0)
        self.task.tap_point.reset_mock()

    def submit(self):
        self.select()
        self.task.rogue_remove_ready.return_value = (1154, 671)
        self.assertTrue(self.step())
        self.task.tap_point.assert_called_once_with(1154, 671, name='ROGUE_REMOVE_OK')
        self.assertEqual(self.task.remove_done, 0)
        self.task.rogue_state_save.assert_not_called()
        self.task.tap_point.reset_mock()

    def test_dark_transition_is_consumed_without_generic_clicks(self):
        self.select()
        self.task.rogue_remove_appear.return_value = False
        self.assertTrue(self.step())
        self.task.tap_point.assert_not_called()
        self.assertEqual(self.task.remove_stage, 1)

    def test_detected_button_submits_even_if_title_is_dimmed(self):
        self.select()
        self.task.rogue_remove_appear.return_value = False
        self.task.rogue_remove_ready.return_value = (1154, 671)
        self.assertTrue(self.step())
        self.task.tap_point.assert_called_once_with(1154, 671, name='ROGUE_REMOVE_OK')
        self.assertEqual(self.task.remove_done, 0)

    def test_unknown_frame_after_selection_timeout_never_reaches_generic_clicks(self):
        self.select()
        self.task.rogue_remove_appear.return_value = False
        expire(self.task)
        self.assertTrue(self.step())
        self.task.tap_point.assert_not_called()
        self.task.rogue_dump_unknown.assert_called_once()

    def test_recognized_detail_popup_is_closed_instead_of_submitted(self):
        self.select()
        self.task.appear.side_effect = lambda button, **kwargs: button is ROGUE_FLASH_DETAIL
        self.task.rogue_remove_ready.return_value = (1150, 670)
        self.assertTrue(self.step())
        self.task.tap_point.assert_called_once_with(200, 400, name='ROGUE_REMOVE_DETAIL_CLOSE')
        self.assertEqual(self.task.remove_done, 0)

    def test_count_only_explicit_completion_and_only_once(self):
        self.submit()
        self.task.appear.return_value = True
        self.step()
        self.step()
        self.assertEqual(self.task.remove_done, 1)
        self.assertEqual(self.task.remove_counts, {'劍幕': 1})
        self.task.rogue_state_save.assert_called_once_with(
            remove_done=1, remove_counts={'劍幕': 1})
        self.assertEqual(self.task.tap_point.call_count, 2)
        self.task.tap_point.assert_called_with(640, 300, name='ROGUE_REMOVE_DONE')

    def test_restart_at_completion_closes_it_without_counting_again(self):
        self.task.remove_done = 1
        self.task.appear.return_value = True
        self.step()
        self.assertEqual(self.task.remove_done, 1)
        self.task.rogue_state_save.assert_not_called()
        self.task.tap_point.assert_called_once_with(640, 300, name='ROGUE_REMOVE_DONE')

    def test_unconfirmed_submission_stops_without_counting_or_selecting_again(self):
        self.submit()
        self.task.rogue_remove_appear.return_value = False
        self.task.rogue_remove_ready.return_value = None
        expire(self.task)
        with self.assertRaises(TaskFailed):
            self.step()
        self.assertEqual(self.task.remove_done, 0)
        self.task.tap_point.assert_not_called()
        self.task.rogue_state_save.assert_not_called()

    def test_repeated_submit_is_bounded_and_does_not_consume_quota(self):
        self.submit()
        for _ in range(REMOVE_MAX_TRIES):
            expire(self.task)
            if self.task.remove_tries < REMOVE_MAX_TRIES:
                self.step()
            else:
                with self.assertRaises(TaskFailed):
                    self.step()
        self.assertEqual(self.task.remove_done, 0)
        self.task.rogue_state_save.assert_not_called()

    def test_recognition_failure_retries_then_cancels_without_consuming_quota(self):
        self.task.rogue_remove_pick.return_value = None
        for _ in range(REMOVE_MAX_TRIES):
            self.assertTrue(self.step())
        self.task.tap_point.assert_not_called()
        self.step()
        self.task.tap_point.assert_called_once_with(913, 673, name='ROGUE_REMOVE_CANCEL')
        self.assertEqual(self.task.remove_done, 0)
        self.task.rogue_state_save.assert_not_called()
        self.task.rogue_remove_appear.return_value = False
        expire(self.task)
        self.assertFalse(self.step())
        self.task.rogue_remove_appear.return_value = True
        self.task.rogue_remove_pick.return_value = self.target
        self.assertTrue(self.step())
        self.task.tap_point.assert_called_with(877, 218, name='ROGUE_REMOVE_CARD')

    def test_unknown_page_without_removal_context_is_not_consumed_or_clicked(self):
        self.task.rogue_remove_appear.return_value = False
        self.assertFalse(self.step())
        self.task.tap_point.assert_not_called()

    def test_externally_selected_card_is_not_submitted(self):
        self.task.rogue_remove_ready.return_value = (1150, 670)
        self.step()
        self.task.tap_point.assert_called_once_with(913, 673, name='ROGUE_REMOVE_CANCEL')
        self.task.rogue_remove_pick.assert_not_called()

    def test_quota_reached_cancels_without_selecting(self):
        self.task.remove_done = 3
        self.step()
        self.task.tap_point.assert_called_once_with(913, 673, name='ROGUE_REMOVE_CANCEL')
        self.task.rogue_remove_pick.assert_not_called()

    def test_skip_confirmation_is_handled_instead_of_clicking_covered_bottom_button(self):
        self.task.remove_done = 3
        self.task.remove_stage = 3
        self.task.appear.side_effect = lambda button, **kwargs: button is ROGUE_REMOVE_SKIP
        self.task.rogue_dialog_point = Mock(return_value=(849, 454))
        self.step()
        self.task.tap_point.assert_called_once_with(849, 454, name='ROGUE_REMOVE_SKIP_CONFIRM')
        self.assertEqual(self.task.remove_done, 3)
        self.task.rogue_state_save.assert_not_called()
        self.task.rogue_remove_pick.assert_not_called()

    def test_restart_at_skip_confirmation_preserves_quota(self):
        self.task.remove_done = 3
        self.task.appear.side_effect = lambda button, **kwargs: button is ROGUE_REMOVE_SKIP
        self.task.rogue_dialog_point = Mock(return_value=(849, 454))
        self.step()
        self.task.tap_point.assert_called_once_with(849, 454, name='ROGUE_REMOVE_SKIP_CONFIRM')
        self.assertEqual(self.task.remove_done, 3)

    def test_unresponsive_skip_button_stops_before_the_click_watchdog(self):
        self.task.remove_stage = 3
        self.task.remove_cancel_tries = REMOVE_MAX_TRIES
        expire(self.task)
        with self.assertRaises(TaskFailed):
            self.step()
        self.task.tap_point.assert_not_called()

    def test_unselected_card_timeout_retries_recognition(self):
        self.select()
        expire(self.task)
        self.step()
        self.assertEqual(self.task.remove_stage, 0)
        self.step()
        self.task.tap_point.assert_called_once_with(877, 218, name='ROGUE_REMOVE_CARD')
        self.assertEqual(self.task.remove_done, 0)

    def test_missed_scan_rehomes_before_retrying(self):
        self.task.rogue_remove_to_top = Mock()
        self.task.rogue_remove_pick.side_effect = [None, self.target]
        self.assertTrue(self.step())
        self.assertTrue(self.step())
        self.assertEqual(self.task.rogue_remove_to_top.call_count, 2)
        self.task.tap_point.assert_called_once_with(877, 218, name='ROGUE_REMOVE_CARD')

    def test_remove_card_points_handles_dark_and_clipped_cards_by_left_border(self):
        task = make_task()
        image = task.device.image
        image[:] = 28
        # Top-clipped partial row (header scrolled off) should be ignored.
        for left in REMOVE_GRID_COLS[:3]:
            image[69:270, left:left + 4] = (230, 80, 140)
        # Full row including a dark-art card (body stays dark) at col 2.
        for left in REMOVE_GRID_COLS:
            image[294:572, left:left + 4] = (230, 80, 140)
        image[294:572, REMOVE_GRID_COLS[0]:REMOVE_GRID_COLS[0] + REMOVE_CARD_WIDTH] = 220
        points = task.rogue_remove_card_points()
        self.assertEqual([(pt[2], pt[3]) for pt in points],
                         [(293, left) for left in REMOVE_GRID_COLS])

    def test_scroll_wait_uses_relaxed_still_threshold_for_card_glow(self):
        task = make_task()
        task.rogue_flash_card_points = Mock(return_value=[(450, 220, 82, 360, 188, 280)])
        task.card_reader = SimpleNamespace(read_name=Mock(side_effect=['一縷光芒', '劍幕']))
        task.rogue_remove_pick()
        self.assertEqual(task.wait_until_still.call_args[1]['threshold'], REMOVE_STILL_THRESHOLD)


SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                          'log', 'rogue_card_pages', 'remove')


@unittest.skipUnless(os.path.exists(os.path.join(SAMPLE_DIR, '091358.png')),
                     'Local removal captures are not available')
class RemovalCaptureTest(unittest.TestCase):
    def load_capture(self, stem):
        path = os.path.join(SAMPLE_DIR, stem + '.png')
        if not os.path.exists(path):
            self.skipTest('Local capture was evicted by the recorder: ' + stem)
        return np.array(Image.open(path))

    def test_actual_reader_picks_sword_curtain_at_third_and_second_positions(self):
        task = make_task()
        task.card_reader = CardReader()
        for stem, expected in (('070435', (876, 215)), ('090926', (876, 215)),
                               ('091358', (665, 215)), ('044408', (663, 222)),
                               ('204838', (876, 215))):
            with self.subTest(stem=stem):
                task.device.image = self.load_capture(stem)
                self.assertEqual(task.rogue_remove_pick()[:2], (expected, '劍幕'))

    def test_all_previously_wrong_light_picks_now_find_curtain(self):
        task = make_task()
        task.card_reader = CardReader()
        for stem in ('044408', '061845', '194612', '194613', '204838'):
            with self.subTest(stem=stem):
                task.device.image = self.load_capture(stem)
                self.assertEqual(task.rogue_remove_pick()[1], '劍幕')

    def test_capture_without_sword_curtain_can_pick_light(self):
        task = make_task()
        task.card_reader = CardReader()
        task.device.image = self.load_capture('080437')
        self.assertEqual(task.rogue_remove_pick()[1], '劍光')

    def test_completion_template_only_matches_the_completion_capture(self):
        task = make_task()
        for stem in ('070435', '090926', '090931', '091358', '091401', '091404', '091653'):
            with self.subTest(stem=stem):
                task.device.image = self.load_capture(stem)
                self.assertEqual(task.appear(ROGUE_REMOVE_DONE, offset=(12, 8), similarity=0.85),
                                 stem == '091401')

    def test_actual_skip_confirmation_can_resume_without_deleting_another_card(self):
        task = make_task()
        task.remove_done = 3
        task.device.image = self.load_capture('113935')
        self.assertTrue(task.handle_rogue_remove(Timer(0)))
        task.tap_point.assert_called_once_with(849, 454, name='ROGUE_REMOVE_SKIP_CONFIRM')
        self.assertEqual(task.remove_done, 3)
        task.rogue_state_save.assert_not_called()


@unittest.skipUnless(os.path.exists(os.path.join(SAMPLE_DIR, '003508.png')),
                     'Latest removal captures are not available')
class LiveRemovalCaptureRegressionTest(unittest.TestCase):
    def test_live_captures_find_dark_rapid_fire_and_merged_sword_light(self):
        task = make_task()
        del task.rogue_delete_times
        task.card_reader = CardReader()
        node = {'RogueDeleteFilter': '劍光 = 2\n劍幕 = 1\n速射彈 = 2\n山茶花幻象 = 1\n水箭 = 1'}
        task.config = SimpleNamespace(
            data={'ChaoszeroRogue': {'ChaoszeroRogue': node}},
            ChaoszeroRogue_RogueDeleteFilter=node['RogueDeleteFilter'],
        )
        task.remove_counts = {}
        task.device.image = np.array(Image.open(os.path.join(SAMPLE_DIR, '001531.png')))
        self.assertEqual(len(task.rogue_remove_card_points()), 8)
        self.assertEqual(task.rogue_remove_pick()[:2], ((454, 222), '劍光'))

        task.remove_counts = {'劍光': 2, '劍幕': 1}
        task.device.image = np.array(Image.open(os.path.join(SAMPLE_DIR, '003508.png')))
        self.assertEqual(len(task.rogue_remove_card_points()), 4)
        self.assertEqual(task.rogue_remove_pick()[:2], ((454, 433), '速射彈'))

        task.device.image = np.array(Image.open(os.path.join(SAMPLE_DIR, '003459.png')))
        self.assertEqual(len(task.rogue_remove_card_points()), 7)

        task.device.image = np.array(Image.open(os.path.join(SAMPLE_DIR, '003513.png')))
        self.assertEqual(len(task.rogue_remove_card_points()), 8)


class ConfiguredRemovalTest(unittest.TestCase):
    def _configured_task(self, delete_filter, remove_counts=None):
        task = make_task()
        del task.rogue_delete_times
        task.remove_counts = dict(remove_counts or {})
        task.config = SimpleNamespace(
            data={'ChaoszeroRogue': {'ChaoszeroRogue': {'RogueDeleteFilter': delete_filter}}},
            ChaoszeroRogue_RogueDeleteFilter=delete_filter,
        )
        return task

    def test_custom_character_cards_ascii_and_per_card_quota(self):
        task = self._configured_task('水護盾 = 2\nS.S.S = 1')
        self.assertEqual(task.rogue_delete_times(), 3)
        points = [(450 + i * 210, 220, 82, 360 + i * 210, 188, 280) for i in range(3)]
        task.rogue_flash_card_points = Mock(return_value=points)
        task.card_reader = SimpleNamespace(read_name=Mock(side_effect=['劍光', 'S.S.S', '水護盾']))
        picked = task.rogue_remove_pick()
        self.assertEqual(picked[:2], ((870, 220), '水護盾'))

        task.remove_counts['水護盾'] = 2
        task.card_reader = SimpleNamespace(read_name=Mock(side_effect=['劍光', 'S.S.S', '水護盾']))
        picked2 = task.rogue_remove_pick()
        self.assertEqual(picked2[:2], ((660, 220), 'S.S.S'))

    def test_empty_delete_filter_disables_removal(self):
        task = self._configured_task('')
        self.assertEqual(task.rogue_delete_times(), 0)
        self.assertEqual(task.rogue_remove_targets(), [])
        self.assertIsNone(task.rogue_remove_pick())

    def test_preferred_remove_slot_prioritizes_that_character_cards(self):
        task = make_task()
        del task.rogue_delete_times
        task.remove_counts = {}
        node = {
            'RogueDeleteFilter': '劍幕 = 1\n水護盾 = 1',
            'RogueSlot1Member': '30093',
            'RogueSlot2Member': '1039',
            'RogueSlot3Member': '',
            'RogueRemoveMember': 2,
        }
        task.config = SimpleNamespace(
            data={'ChaoszeroRogue': {'ChaoszeroRogue': node}},
            **{f'ChaoszeroRogue_{k}': v for k, v in node.items()},
        )
        self.assertEqual(task.rogue_remove_targets(), ['水護盾', '劍幕'])
        points = [(450 + i * 210, 220, 82, 360 + i * 210, 188, 280) for i in range(2)]
        task.rogue_flash_card_points = Mock(return_value=points)
        task.card_reader = SimpleNamespace(read_name=Mock(side_effect=['劍幕', '水護盾']))
        picked = task.rogue_remove_pick()
        self.assertEqual(picked[:2], ((660, 220), '水護盾'))

    def test_two_card_removal_selects_two_submits_and_counts_both(self):
        task = self._configured_task('劍幕 = 1\n劍光 = 1')
        task.rogue_remove_to_top = Mock()
        task.rogue_remove_ready = Mock(side_effect=[None, None, (1154, 671)])
        task.rogue_remove_required = Mock(return_value=2)
        task.rogue_flash_card_points = Mock(return_value=[
            (454, 222, 83, 360, 188, 276),
            (667, 222, 83, 573, 188, 276),
        ])
        task.card_reader = SimpleNamespace(read_name=Mock(side_effect=['劍光', '劍幕']))

        # Step 1: picks 劍幕 (higher priority) and 劍光, taps 劍幕 first.
        self.assertTrue(task.handle_rogue_remove(Timer(0)))
        task.tap_point.assert_called_once_with(667, 222, name='ROGUE_REMOVE_CARD')
        task.tap_point.reset_mock()

        # Step 2: ready is still None (1/2 selected), taps 劍光 second.
        self.assertTrue(task.handle_rogue_remove(Timer(0)))
        task.tap_point.assert_called_once_with(454, 222, name='ROGUE_REMOVE_CARD')
        task.tap_point.reset_mock()

        # Step 3: ready lights up (2/2 selected), presses 移除.
        self.assertTrue(task.handle_rogue_remove(Timer(0)))
        task.tap_point.assert_called_once_with(1154, 671, name='ROGUE_REMOVE_OK')
        task.tap_point.reset_mock()

        # Step 4: completion banner confirms 2 removals across both card names.
        task.appear = Mock(side_effect=lambda button, **kwargs: button is ROGUE_REMOVE_DONE)
        self.assertTrue(task.handle_rogue_remove(Timer(0)))
        self.assertEqual(task.remove_done, 2)
        self.assertEqual(task.remove_counts, {'劍幕': 1, '劍光': 1})
        task.rogue_state_save.assert_called_once_with(
            remove_done=2, remove_counts={'劍幕': 1, '劍光': 1})

    def test_two_card_removal_skips_when_remaining_quota_is_one(self):
        task = self._configured_task('劍幕 = 1\n劍光 = 1', remove_counts={'劍幕': 1})
        task.remove_done = 1
        task.rogue_remove_ready = Mock(return_value=None)
        task.rogue_remove_required = Mock(return_value=2)
        task.rogue_remove_picks = Mock()

        self.assertTrue(task.handle_rogue_remove(Timer(0)))
        task.tap_point.assert_called_once_with(913, 673, name='ROGUE_REMOVE_CANCEL')
        task.rogue_remove_picks.assert_not_called()

    def test_two_card_removal_header_distinguished_from_transform_and_copy(self):
        from module.chaoszero.assets import ROGUE_COPY_TITLE2, ROGUE_REMOVE, ROGUE_TRANSFORM
        for button, expected in (
            (ROGUE_REMOVE, True),
            (ROGUE_TRANSFORM, False),
            (ROGUE_COPY_TITLE2, False),
        ):
            with self.subTest(template=button.name):
                task = make_task()
                del task.rogue_remove_appear
                task.device.image = np.array(Image.open(button.file).convert('RGB'))
                self.assertEqual(task.rogue_remove_appear(), expected)


class RemovalTemplateTest(unittest.TestCase):
    def test_template_keeps_full_frame_and_extractable_nonempty_title(self):
        for button in (ROGUE_REMOVE_DONE, ROGUE_REMOVE_SKIP):
            with self.subTest(template=button.name):
                template = Image.open(button.file).convert('RGB')
                self.assertEqual(template.size, (1280, 720))
                self.assertEqual(template.getbbox(), button.area)
                self.assertGreater(float(np.array(template.crop(button.area)).std()), 10)


if __name__ == '__main__':
    unittest.main()
