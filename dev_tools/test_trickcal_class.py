from datetime import datetime
import os
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from module.config.server import set_server

# Bind trickcal assets/config before importing module.trickcal.*
set_server('trickcal')

from module.trickcal.assets import (  # noqa: E402
    CLASS_SWEEP_BTN,
    DUNGEON_CLONE_EMPTY,
    DUNGEON_SWEEP_CONFIRM,
    DUNGEON_SWEEP_TITLE,
    EVENT_SWEEP_CANCEL,
    EVENT_SWEEP_CLEAR,
    EVENT_SWEEP_MAX,
)
from module.trickcal.class_task import (  # noqa: E402
    CLASS_SUBJECT_CARDS,
    TrickcalClass,
    class_sweep_lit,
    find_open_class_subjects,
    find_visible_class_lessons,
    pick_class_subject,
    scheduled_class_subjects,
)
from module.trickcal.page import page_class, page_class_stage  # noqa: E402


def _make_class_task():
    cls = TrickcalClass.__new__(TrickcalClass)
    cls.device = MagicMock()
    cls.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
    cls.device.click = MagicMock()
    cls.device.click_record_clear = MagicMock()
    cls.device.drag = MagicMock()
    cls.device.screenshot = MagicMock(side_effect=lambda: cls.device.image)
    cls.device.stuck_record_clear = MagicMock()
    cls.loop = MagicMock(side_effect=lambda timeout=10: iter(range(20)))
    cls.ui_ensure = MagicMock()
    cls.ui_goto_main = MagicMock()
    cls.ui_page_appear = MagicMock(return_value=False)
    cls.appear = MagicMock(return_value=False)
    cls.handle_reward_popup = MagicMock(return_value=False)
    cls.config = MagicMock()
    cls.config.TrickcalClass_SaturdaySubject = 'blue'
    cls.config.TrickcalClass_SundaySubject = 'purple'
    cls.config.TrickcalClass_GreenLesson = 0
    cls.config.TrickcalClass_BlueLesson = 0
    cls.config.TrickcalClass_RedLesson = 0
    cls.config.TrickcalClass_YellowLesson = 0
    cls.config.TrickcalClass_PurpleLesson = 0
    return cls


class TestTrickcalClass(unittest.TestCase):
    def test_pick_class_subject(self):
        # Mon..Fri: only 1 open card, auto-pick regardless of weekend dropdowns.
        for day_open in ('green', 'blue', 'red', 'yellow', 'purple'):
            self.assertEqual(pick_class_subject([day_open], 'red', 'purple'), day_open)

        # Saturday: green + blue + red open simultaneously.
        self.assertEqual(pick_class_subject(['green', 'blue', 'red'], 'red', 'yellow'), 'red')
        # Sunday: yellow + purple open simultaneously.
        self.assertEqual(pick_class_subject(['yellow', 'purple'], 'blue', 'purple'), 'purple')
        # Edge cases: empty returns None; full-open falls back cleanly.
        self.assertIsNone(pick_class_subject([], 'blue', 'purple'))
        self.assertEqual(
            pick_class_subject(['green', 'blue', 'red', 'yellow', 'purple'], 'red', 'purple'),
            'red',
        )

    def test_open_subject_and_sweep_lit_detectors(self):
        # Closed cards are dark with white padlock pixels in center; open cards are bright without padlock.
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        for key, (x1, y1, x2, y2) in CLASS_SUBJECT_CARDS.items():
            if key in ('green', 'red'):
                img[y1:y2, x1:x2] = (170, 170, 170)
            else:
                img[y1:y2, x1:x2] = (65, 65, 65)
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2
                img[cy - 25:cy + 25, cx - 25:cx + 25] = (250, 250, 250)
        self.assertEqual(find_open_class_subjects(img), ['green', 'red'])

        # CLASS_SWEEP_BTN lit cream matches while dark/grey fails.
        CLASS_SWEEP_BTN.ensure_template()
        x1, y1, x2, y2 = CLASS_SWEEP_BTN.area
        img_lit = np.zeros((720, 1280, 3), dtype=np.uint8)
        img_lit[y1:y2, x1:x2] = CLASS_SWEEP_BTN.image
        self.assertTrue(class_sweep_lit(img_lit))

        img_dim = np.zeros((720, 1280, 3), dtype=np.uint8)
        img_dim[y1:y2, x1:x2] = (140, 140, 140)
        self.assertFalse(class_sweep_lit(img_dim))

    def test_real_screenshots_when_present(self):
        hub_path = r'C:\Users\14494\.gemini\antigravity\brain\13f03cda-c1d1-419a-8ba6-f6233f3d96d8\.user_uploaded\media_1795534720672_f3a606a5.png'
        stg_path = r'C:\Users\14494\.gemini\antigravity\brain\13f03cda-c1d1-419a-8ba6-f6233f3d96d8\.user_uploaded\media_1795534720671_90da1c6b.png'
        if not (os.path.exists(hub_path) and os.path.exists(stg_path)):
            return
        hub = cv2.resize(
            cv2.cvtColor(cv2.imdecode(np.fromfile(hub_path, dtype=np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB),
            (1280, 720),
            interpolation=cv2.INTER_CUBIC,
        )
        stg = cv2.resize(
            cv2.cvtColor(cv2.imdecode(np.fromfile(stg_path, dtype=np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB),
            (1280, 720),
            interpolation=cv2.INTER_CUBIC,
        )
        self.assertEqual(find_open_class_subjects(hub), ['blue'])
        lessons, has_locked = find_visible_class_lessons(stg)
        self.assertTrue(has_locked)
        self.assertEqual([(n, s) for n, _, _, s in lessons], [(1, True), (2, False)])
        self.assertTrue(class_sweep_lit(stg))

    def test_skip_when_daily_entries_zero(self):
        cls = _make_class_task()
        with patch('module.trickcal.class_task.read_class_daily_remaining', return_value=0), \
             patch('module.trickcal.class_task.find_open_class_subjects') as mock_open:
            cls.run()

        mock_open.assert_not_called()
        cls.ui_goto_main.assert_called_once()
        cls.config.task_delay.assert_called_once_with(server_update=True)

    def test_saturday_auto_highest_three_star_and_sweep(self):
        cls = _make_class_task()
        cls.config.TrickcalClass_SaturdaySubject = 'red'

        state = {'page': page_class, 'selected': 1, 'rem': 2, 'in_sweep': False, 'step': 0}
        cls.ui_page_appear.side_effect = lambda p: p == state['page']

        # Simulate scrolling down once: first frame shows 1..3 (3-star), second frame shows 4 (3-star), 5 (0-star), 6 (locked).
        visible_seq = [
            ([(1, 156, 150, True), (2, 156, 276, True), (3, 156, 402, True)], False),
            ([(4, 156, 150, True), (5, 156, 276, False)], True),
            ([(4, 156, 150, True), (5, 156, 276, False)], True),
        ]

        def appear_fn(btn, offset=None, interval=None):
            if not state['in_sweep']:
                return False
            step = state['step']
            if btn == DUNGEON_SWEEP_TITLE and step in (1, 2, 3):
                return True
            if btn == DUNGEON_SWEEP_CONFIRM and step == 2:
                return True
            if btn == EVENT_SWEEP_CLEAR and step == 3:
                return True
            return False

        def click_fn(btn):
            if btn.name == 'CLASS_SUBJECT_RED':
                state['page'] = page_class_stage
            elif btn.name == 'CLASS_LESSON_ROW':
                state['selected'] = 4
            elif btn == CLASS_SWEEP_BTN:
                state['in_sweep'] = True
                state['step'] = 1
            elif btn == EVENT_SWEEP_MAX:
                state['step'] = 2
            elif btn == DUNGEON_SWEEP_CONFIRM:
                state['step'] = 3
            elif btn == EVENT_SWEEP_CLEAR:
                state['in_sweep'] = False
                state['step'] = 4
                state['rem'] = 0

        cls.appear.side_effect = appear_fn
        cls.device.click.side_effect = click_fn
        cls.device.drag.side_effect = lambda *a, **kw: None

        with patch('module.trickcal.class_task.read_class_daily_remaining', side_effect=lambda im, on_hub=True: state['rem']), \
             patch('module.trickcal.class_task.find_open_class_subjects', return_value=['green', 'blue', 'red']), \
             patch('module.trickcal.class_task.find_visible_class_lessons', side_effect=lambda im: visible_seq.pop(0)), \
             patch('module.trickcal.class_task.read_selected_class_lesson', side_effect=lambda im: state['selected']), \
             patch('module.trickcal.class_task.class_sweep_lit', return_value=True), \
             patch('module.trickcal.class_task.Timer') as mock_timer, \
             patch.object(TrickcalClass, '_scroll_lesson_list', return_value=12.0) as mock_scroll:
            mock_timer.return_value.start.return_value = mock_timer.return_value
            mock_timer.return_value.reached.return_value = True
            cls.run()

        clicked_names = [c[0][0].name for c in cls.device.click.call_args_list]
        self.assertEqual(
            clicked_names,
            ['CLASS_SUBJECT_RED', 'CLASS_LESSON_ROW', 'CLASS_SWEEP_BTN', 'EVENT_SWEEP_MAX', 'DUNGEON_SWEEP_CONFIRM', 'EVENT_SWEEP_CLEAR'],
        )
        mock_scroll.assert_called_once_with(drag_up=True)
        cls.ui_goto_main.assert_called_once()
        cls.config.task_delay.assert_called_once_with(server_update=True)

    def test_explicit_lesson_and_dim_sweep_no_force_battle(self):
        cls = _make_class_task()
        cls.config.TrickcalClass_TuesdayLesson = 0  # unused, BlueLesson used
        cls.config.TrickcalClass_BlueLesson = 7
        cls.ui_page_appear.side_effect = lambda p: p == page_class_stage

        visible_seq = [
            ([(1, 156, 150, True), (2, 156, 276, True), (3, 156, 402, True)], False),
            ([(6, 156, 150, True), (7, 156, 276, False)], True),
        ]
        selected_seq = [1, 1, 7]

        with patch('module.trickcal.class_task.read_class_daily_remaining', side_effect=[2, 2]), \
             patch('module.trickcal.class_task.find_open_class_subjects', return_value=['blue']), \
             patch('module.trickcal.class_task.find_visible_class_lessons', side_effect=lambda im: visible_seq.pop(0)), \
             patch('module.trickcal.class_task.read_selected_class_lesson', side_effect=lambda im: selected_seq.pop(0) if selected_seq else 7), \
             patch('module.trickcal.class_task.class_sweep_lit', return_value=False), \
             patch('module.trickcal.class_task.Timer') as mock_timer, \
             patch.object(TrickcalClass, '_scroll_lesson_list', return_value=15.0):
            mock_timer.return_value.start.return_value = mock_timer.return_value
            mock_timer.return_value.reached.return_value = True
            cls.run()

        clicked_names = [c[0][0].name for c in cls.device.click.call_args_list]
        self.assertEqual(clicked_names, ['CLASS_LESSON_ROW'])
        cls.ui_goto_main.assert_called_once()

    def test_empty_toast_stops_sweep_cleanly(self):
        cls = _make_class_task()
        cls.ui_page_appear.side_effect = lambda p: p == page_class_stage
        cls.appear.side_effect = lambda btn, offset=None, interval=None: btn == DUNGEON_CLONE_EMPTY

        with patch('module.trickcal.class_task.read_class_daily_remaining', side_effect=[2, 1]), \
             patch('module.trickcal.class_task.find_open_class_subjects', return_value=['blue']), \
             patch('module.trickcal.class_task.find_visible_class_lessons', return_value=([(1, 156, 150, True)], True)), \
             patch('module.trickcal.class_task.read_selected_class_lesson', return_value=1), \
             patch('module.trickcal.class_task.class_sweep_lit', return_value=True):
            cls.run()

        cls.device.click.assert_not_called()
        cls.ui_goto_main.assert_called_once()

    def test_weekday_schedule_and_fallback_recovery(self):
        # 1. Verify Mon..Sun schedule with 03:00 daily reset boundary (2026-11-23 is Monday).
        self.assertEqual(scheduled_class_subjects(datetime(2026, 11, 23, 3, 0)), ['green'])
        self.assertEqual(scheduled_class_subjects(datetime(2026, 11, 24, 2, 59)), ['green'])
        self.assertEqual(scheduled_class_subjects(datetime(2026, 11, 24, 3, 0)), ['blue'])
        self.assertEqual(scheduled_class_subjects(datetime(2026, 11, 25, 12, 0)), ['red'])
        self.assertEqual(scheduled_class_subjects(datetime(2026, 11, 26, 12, 0)), ['yellow'])
        self.assertEqual(scheduled_class_subjects(datetime(2026, 11, 27, 12, 0)), ['purple'])
        self.assertEqual(scheduled_class_subjects(datetime(2026, 11, 28, 12, 0)), ['green', 'blue', 'red'])
        self.assertEqual(scheduled_class_subjects(datetime(2026, 11, 29, 12, 0)), ['yellow', 'purple'])

        # 2. If initial open check mis-detects purple on Tuesday and clicking purple stays on page_class,
        #    re-check / weekday fallback switches to Tuesday's open blue card and completes sweep.
        cls = _make_class_task()
        cls.config.TrickcalClass_BlueLesson = 0
        state = {'page': page_class, 'rem': 1, 'in_sweep': False, 'step': 0}
        cls.ui_page_appear.side_effect = lambda p: p == state['page']

        # Frame shows purple bright by mistake at first, then locked, while blue stays dark so fallback hits scheduled blue.
        img_wrong = np.zeros((720, 1280, 3), dtype=np.uint8)
        px1, py1, px2, py2 = CLASS_SUBJECT_CARDS['purple']
        img_wrong[py1:py2, px1:px2] = (160, 160, 160)
        cls.device.image = img_wrong

        def click_fn(btn):
            if btn.name == 'CLASS_SUBJECT_BLUE':
                state['page'] = page_class_stage
            elif btn.name == 'CLASS_SWEEP_BTN':
                state['in_sweep'] = True
                state['step'] = 1
            elif btn.name == 'EVENT_SWEEP_MAX':
                state['step'] = 2
            elif btn.name == 'DUNGEON_SWEEP_CONFIRM':
                state['step'] = 3
            elif btn.name == 'EVENT_SWEEP_CLEAR':
                state['in_sweep'] = False
                state['step'] = 4
                state['rem'] = 0

        def appear_fn(btn, offset=None, interval=None):
            if not state['in_sweep']:
                return False
            if btn == DUNGEON_SWEEP_TITLE and state['step'] in (1, 2, 3):
                return True
            if btn == DUNGEON_SWEEP_CONFIRM and state['step'] == 2:
                return True
            if btn == EVENT_SWEEP_CLEAR and state['step'] == 3:
                return True
            return False

        cls.appear.side_effect = appear_fn
        cls.device.click.side_effect = click_fn

        with patch('module.trickcal.class_task.read_class_daily_remaining', side_effect=lambda im, on_hub=True: state['rem']), \
             patch('module.trickcal.class_task.scheduled_class_subjects', return_value=['blue']), \
             patch('module.trickcal.class_task.find_visible_class_lessons', return_value=([(1, 156, 150, True)], True)), \
             patch('module.trickcal.class_task.read_selected_class_lesson', return_value=1), \
             patch('module.trickcal.class_task.class_sweep_lit', return_value=True), \
             patch('module.trickcal.class_task.Timer') as mock_timer:
            mock_timer.return_value.start.return_value = mock_timer.return_value
            mock_timer.return_value.reached.return_value = True
            cls.run()

        clicked = [c[0][0].name for c in cls.device.click.call_args_list]
        self.assertIn('CLASS_SUBJECT_PURPLE', clicked)
        self.assertIn('CLASS_SUBJECT_BLUE', clicked)
        self.assertEqual(clicked[-4:], ['CLASS_SWEEP_BTN', 'EVENT_SWEEP_MAX', 'DUNGEON_SWEEP_CONFIRM', 'EVENT_SWEEP_CLEAR'])
        cls.ui_goto_main.assert_called_once()


if __name__ == '__main__':
    unittest.main()
