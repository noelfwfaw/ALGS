"""Short-term crash course (短期速成班) automation for Trickcal.

Entry path: `page_main -> page_adventure -> page_class -> page_class_stage`.
Schedule:
- Mon..Fri: 1 subject opens per day (green / blue / red / yellow / purple),
  detected dynamically from brightness and absence of the center padlock.
- Saturday: green + blue + red open simultaneously (`SaturdaySubject` chooses).
- Sunday: yellow + purple open simultaneously (`SundaySubject` chooses).
Daily limit: 2 free sweeps per day (0 stamina cost), 25 lessons per subject.
"""

from datetime import datetime, timedelta
import re

import cv2
import numpy as np

from module.base.timer import Timer
from module.base.utils import crop
from module.logger import logger
from module.ocr.ocr import Ocr
from module.trickcal.assets import (
    CLASS_SWEEP_BTN,
    DUNGEON_CLONE_EMPTY,
    DUNGEON_SWEEP_CONFIRM,
    DUNGEON_SWEEP_TITLE,
    EVENT_STAMINA_BUY,
    EVENT_SWEEP_CANCEL,
    EVENT_SWEEP_CLEAR,
    EVENT_SWEEP_CONFIRM,
    EVENT_SWEEP_MAX,
    EVENT_SWEEP_TITLE,
    SHOP_BUY_CANCEL,
)
from module.trickcal.dungeon_stage import _ocr_bw, tap_box
from module.trickcal.page import page_class, page_class_stage, page_main
from module.trickcal.trickcal_ui import TrickcalUI

CLASS_SUBJECT_ORDER = ('green', 'blue', 'red', 'yellow', 'purple')
CLASS_SUBJECT_CARDS = {
    'green': (10, 272, 254, 566),
    'blue': (264, 130, 508, 424),
    'red': (518, 272, 762, 566),
    'yellow': (772, 130, 1016, 424),
    'purple': (1026, 272, 1270, 566),
}
SATURDAY_SUBJECTS = ('green', 'blue', 'red')
SUNDAY_SUBJECTS = ('yellow', 'purple')
WEEKDAY_CLASS_SUBJECTS = (
    ('green',),                  # Mon
    ('blue',),                   # Tue
    ('red',),                    # Wed
    ('yellow',),                 # Thu
    ('purple',),                 # Fri
    ('green', 'blue', 'red'),    # Sat
    ('yellow', 'purple'),        # Sun
)
CLASS_CARDS_SETTLE_ROI = (10, 125, 1270, 570)
SUBJECT_LESSON_ATTR = {
    'green': 'TrickcalClass_GreenLesson',
    'blue': 'TrickcalClass_BlueLesson',
    'red': 'TrickcalClass_RedLesson',
    'yellow': 'TrickcalClass_YellowLesson',
    'purple': 'TrickcalClass_PurpleLesson',
}

CLASS_HUB_COUNT_AREA = (704, 612, 762, 654)
CLASS_STAGE_BADGE_AREA = (1168, 596, 1248, 626)
CLASS_STAGE_BADGE_LEFT_AREA = (1170, 596, 1200, 626)
CLASS_SELECTED_HEADER_AREA = (834, 104, 976, 146)
CLASS_LIST_SCROLL_ROI = (34, 96, 276, 692)

CLASS_OFFSET = (20, 20)
CLASS_SWEEP_OFFSET = (25, 35)
SWEEP_COLOR_THRESHOLD = 35
SCROLL_MAX_ATTEMPTS = 10

_CLASS_OCR_CACHE = {}


def _get_hub_daily_ocr():
    if 'hub_daily' not in _CLASS_OCR_CACHE:
        _CLASS_OCR_CACHE['hub_daily'] = Ocr(
            tap_box(CLASS_HUB_COUNT_AREA, 'OCR_CLASS_DAILY'),
            lang='azur_lane',
            letter=(255, 255, 255),
            threshold=128,
            alphabet='0123456789/',
            name='OCR_CLASS_DAILY',
        )
    return _CLASS_OCR_CACHE['hub_daily']


def _get_stage_badge_ocr():
    if 'stage_badge' not in _CLASS_OCR_CACHE:
        _CLASS_OCR_CACHE['stage_badge'] = Ocr(
            tap_box(CLASS_STAGE_BADGE_LEFT_AREA, 'OCR_CLASS_BADGE'),
            lang='azur_lane',
            letter=(255, 255, 255),
            threshold=128,
            alphabet='0123456789',
            name='OCR_CLASS_BADGE',
        )
    return _CLASS_OCR_CACHE['stage_badge']


def scheduled_class_subjects(now=None):
    """Return subject keys scheduled open for `now` under the 03:00 daily reset."""
    cur = now if now is not None else datetime.now()
    return list(WEEKDAY_CLASS_SUBJECTS[(cur - timedelta(hours=3)).weekday()])


def inspect_class_subjects(image):
    """Return `{subject: (mean_luma, padlock_px)}` for each card on `page_class`."""
    stats = {}
    for key in CLASS_SUBJECT_ORDER:
        x1, y1, x2, y2 = CLASS_SUBJECT_CARDS[key]
        patch = image[y1:y2, x1:x2]
        mean_luma = float(cv2.cvtColor(patch, cv2.COLOR_RGB2GRAY).mean())
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        center = image[cy - 45:cy + 45, cx - 35:cx + 35]
        padlock_px = int((center.min(axis=2) > 220).sum())
        stats[key] = (round(mean_luma, 1), padlock_px)
    return stats


def find_open_class_subjects(image):
    """Return subject keys whose card on `page_class` is bright and unpadlocked."""
    stats = inspect_class_subjects(image)
    return [
        key for key in CLASS_SUBJECT_ORDER
        if stats[key][0] >= 95.0 and stats[key][1] < 300
    ]


def pick_class_subject(open_subjects, saturday_subject='green', sunday_subject='yellow'):
    """Pick the subject key to enter from currently open cards and weekend settings."""
    if not open_subjects:
        return None
    if len(open_subjects) == 1:
        return open_subjects[0]
    open_set = set(open_subjects)
    if open_set.issubset(set(SATURDAY_SUBJECTS)) and saturday_subject in open_set:
        return saturday_subject
    if open_set.issubset(set(SUNDAY_SUBJECTS)) and sunday_subject in open_set:
        return sunday_subject
    if saturday_subject in open_set:
        return saturday_subject
    if sunday_subject in open_set:
        return sunday_subject
    return open_subjects[0]


def read_class_daily_remaining(image, on_hub=True):
    """Read remaining daily entries (`0..2`) on `page_class` or `page_class_stage`."""
    if on_hub:
        raw = _get_hub_daily_ocr().ocr(image)
        m = re.search(r'(\d+)\s*/\s*(\d+)', raw)
        if m:
            return int(m.group(1))
        logger.warning(f'Could not parse class daily remaining on hub: {raw!r}')
        return None

    patch = crop(image, CLASS_STAGE_BADGE_AREA)
    bw = np.where(patch.min(axis=2) > 180, 0, 255).astype(np.uint8)
    txt = _ocr_bw(bw, alphabet=None)
    m = re.search(r'(\d+)\s*[→\->=]+\s*(\d+)', txt)
    if m:
        return int(m.group(1))
    raw = _get_stage_badge_ocr().ocr(image)
    m = re.search(r'\d+', raw)
    if m:
        return int(m.group(0))
    return None


def read_selected_class_lesson(image):
    """Read currently selected lesson index (`1..25`) from the right-hand title."""
    patch = crop(image, CLASS_SELECTED_HEADER_AREA)
    bw = np.where(patch.min(axis=2) > 190, 0, 255).astype(np.uint8)
    txt = _ocr_bw(bw, alphabet=None)
    m = re.search(r'第\s*(\d+)\s*课', txt) or re.search(r'(\d+)', txt)
    if not m:
        return None
    num = int(m.group(1))
    return num if 1 <= num <= 25 else None


def _contiguous_runs(mask, offset_y, min_len=80):
    """Find contiguous True vertical intervals of at least `min_len` pixels."""
    out = []
    in_run = False
    start = 0
    for idx, flag in enumerate(mask):
        if flag and not in_run:
            start = idx
            in_run = True
        elif not flag and in_run:
            if idx - start >= min_len:
                out.append((offset_y + start, offset_y + idx))
            in_run = False
    if in_run and len(mask) - start >= min_len:
        out.append((offset_y + start, offset_y + len(mask)))
    return out


def find_visible_class_lessons(image):
    """Return `(lessons, has_locked)` where `lessons` is `[(n, cx, cy, is_three_star), ...]`."""
    y_start, y_end = 90, 712
    side_l = image[y_start:y_end, 50:105, 1].mean(axis=1)
    side_r = image[y_start:y_end, 205:260, 1].mean(axis=1)
    side_g = (side_l + side_r) / 2.0

    unlocked_runs = _contiguous_runs(side_g >= 105.0, y_start, min_len=80)
    locked_runs = _contiguous_runs(side_g <= 76.0, y_start, min_len=80)
    has_locked = len(locked_runs) > 0

    lessons = []
    for y1, y2 in unlocked_runs:
        title = image[y1 + 6:min(y1 + 48, y2), 65:245]
        bw = np.where(title.min(axis=2) > 180, 0, 255).astype(np.uint8)
        txt = _ocr_bw(bw, alphabet=None)
        m = re.search(r'第\s*(\d+)\s*课', txt) or re.search(r'(\d+)', txt)
        if not m:
            continue
        lesson_num = int(m.group(1))
        if not 1 <= lesson_num <= 25:
            continue

        stars = image[y1 + 48:max(y1 + 49, y2 - 8), 90:222]
        gold = (stars[:, :, 0] > 210) & (stars[:, :, 1] > 155) & (stars[:, :, 2] < 95)
        w = gold.shape[1]
        is_three_star = (
            w >= 3
            and all(int(gold[:, i * w // 3:(i + 1) * w // 3].sum()) >= 120 for i in range(3))
        )
        lessons.append((lesson_num, 156, (y1 + y2) // 2, is_three_star))

    lessons.sort(key=lambda item: item[0])
    return lessons, has_locked


def class_sweep_lit(image):
    """Return True when the cream 速战 button on `page_class_stage` is enabled."""
    return CLASS_SWEEP_BTN.appear_on(image, threshold=SWEEP_COLOR_THRESHOLD)


class TrickcalClass(TrickcalUI):
    """
    Daily sweep for 短期速成班 (0 stamina, 2 free runs/day).

    Pages:
        in: page_main
        out: page_main
    """

    def ui_additional(self):
        """Dismiss leftover sweep or modal overlays during `ui_goto`."""
        if self.appear(EVENT_SWEEP_CLEAR, offset=CLASS_OFFSET, interval=2):
            logger.info('Leftover sweep CLEAR popup, press 确定')
            self.device.click(EVENT_SWEEP_CLEAR)
            return True
        if self.appear(EVENT_SWEEP_CANCEL, offset=CLASS_OFFSET, interval=2):
            logger.info('Leftover sweep count popup, press 取消')
            self.device.click(EVENT_SWEEP_CANCEL)
            return True
        if self.appear(EVENT_STAMINA_BUY, offset=CLASS_OFFSET, interval=2):
            logger.info('Leftover stamina buy popup, press 取消')
            self.device.click(EVENT_STAMINA_BUY)
            return True
        if self.appear(SHOP_BUY_CANCEL, offset=CLASS_OFFSET, interval=2):
            logger.info('Leftover shop buy popup, press 取消')
            self.device.click(SHOP_BUY_CANCEL)
            return True
        return super().ui_additional()

    def run(self):
        """Run 短期速成班 sweep for today's active subject and exit back to lobby."""
        logger.hr('Trickcal Class', level=1)
        self.ui_ensure(page_main)
        self.ui_ensure(page_class)
        self._wait_class_hub_settled()

        rem = read_class_daily_remaining(self.device.image, on_hub=True)
        if rem == 0:
            logger.info('Class daily entries 0/2, skip')
            self.ui_goto_main()
            self.config.task_delay(server_update=True)
            return

        sat = self.config.TrickcalClass_SaturdaySubject
        sun = self.config.TrickcalClass_SundaySubject
        stats = inspect_class_subjects(self.device.image)
        open_subjects = find_open_class_subjects(self.device.image)
        subject = pick_class_subject(open_subjects, sat, sun)
        logger.info(f'Class cards={stats}, open={open_subjects}, chosen={subject}')

        entered = False
        active_subject = subject
        tried = []
        if active_subject is not None:
            tried.append(active_subject)
            entered = self._enter_subject(active_subject, timeout=5)

        if not entered and self.ui_page_appear(page_class):
            retry_open = find_open_class_subjects(self.device.image)
            retry_subject = pick_class_subject(retry_open, sat, sun)
            if retry_subject is not None and retry_subject not in tried:
                logger.info(f'Retry class subject after settle: open={retry_open}, chosen={retry_subject}')
                tried.append(retry_subject)
                active_subject = retry_subject
                entered = self._enter_subject(active_subject, timeout=5)

        if not entered and self.ui_page_appear(page_class):
            sched_open = scheduled_class_subjects()
            sched_subject = pick_class_subject(sched_open, sat, sun)
            if sched_subject is not None and sched_subject not in tried:
                logger.warning(f'Visual subject entry failed ({tried}), fallback to weekday schedule: {sched_subject}')
                active_subject = sched_subject
                entered = self._enter_subject(active_subject, timeout=5)

        if not entered or active_subject is None:
            logger.warning(f'Could not enter class subject {active_subject}, skip')
            self.ui_goto_main()
            self.config.task_delay(server_update=True)
            return

        raw_lesson = getattr(self.config, SUBJECT_LESSON_ATTR[active_subject], 0)
        target = max(0, min(25, int(raw_lesson)))
        selected = (
            self._select_highest_three_star_lesson()
            if target == 0
            else self._select_lesson(target)
        )
        if selected:
            self._sweep_class()
        else:
            logger.warning(f'Could not select target lesson {target} for {active_subject}, skip')

        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def _wait_class_hub_settled(self):
        """Wait briefly on `page_class` for card entrance animations to finish."""
        settle = Timer(0.8).start()
        prev = crop(self.device.image, CLASS_CARDS_SETTLE_ROI)
        for _ in self.loop(timeout=5):
            cur = crop(self.device.image, CLASS_CARDS_SETTLE_ROI)
            diff = float(np.abs(cur.astype(np.int16) - prev.astype(np.int16)).mean())
            prev = cur
            if settle.reached() and self.ui_page_appear(page_class) and diff < 2.0:
                return True
        return False

    def _enter_subject(self, subject, timeout=5):
        """Click the chosen subject card on `page_class` until `page_class_stage` opens."""
        x1, y1, x2, y2 = CLASS_SUBJECT_CARDS[subject]
        card_btn = tap_box((x1 + 30, y1 + 40, x2 - 30, y2 - 40), f'CLASS_SUBJECT_{subject.upper()}')
        retry = Timer(2.0)
        for _ in self.loop(timeout=timeout):
            if self.ui_page_appear(page_class_stage):
                return True
            if self.ui_page_appear(page_class) and retry.reached():
                retry.reset()
                logger.info(f'Enter short-class subject {subject}')
                self.device.click(card_btn)  # alas-lint: allow - guarded by ui_page_appear(page_class)
        return self.ui_page_appear(page_class_stage)

    def _tap_lesson_and_confirm(self, target, cy):
        """Tap lesson row around `cy` until right-hand header confirms `target`."""
        row_btn = tap_box((65, max(98, cy - 30), 245, min(706, cy + 30)), 'CLASS_LESSON_ROW')
        retry = Timer(2.0)
        for _ in self.loop(timeout=8):
            if read_selected_class_lesson(self.device.image) == target:
                return True
            if self.ui_page_appear(page_class_stage) and retry.reached():
                retry.reset()
                logger.info(f'Select class lesson {target}')
                self.device.click(row_btn)  # alas-lint: allow - guarded by ui_page_appear(page_class_stage)
        return read_selected_class_lesson(self.device.image) == target

    def _scroll_lesson_list(self, drag_up):
        """Scroll left lesson list vertically and return mean pixel diff after settling."""
        before = crop(self.device.image, CLASS_LIST_SCROLL_ROI)
        start = (156, 600) if drag_up else (156, 180)
        end = (156, 180) if drag_up else (156, 600)
        logger.info(f'Scroll class lesson list {"down (drag up)" if drag_up else "up (drag down)"}')
        self.device.drag(start, end, point_random=(-10, -10, 10, 10), name='CLASS_LESSON_SCROLL')

        settle = Timer(0.7).start()
        for _ in self.loop(timeout=2):
            if settle.reached() and self.ui_page_appear(page_class_stage):
                break

        after = crop(self.device.image, CLASS_LIST_SCROLL_ROI)
        return float(np.abs(after.astype(np.int16) - before.astype(np.int16)).mean())

    def _select_lesson(self, target):
        """Scroll lesson list until `target` (1..25) is visible, tap it, and confirm."""
        if read_selected_class_lesson(self.device.image) == target:
            return True

        unchanged = 0
        for _ in range(SCROLL_MAX_ATTEMPTS):
            lessons, has_locked = find_visible_class_lessons(self.device.image)
            for num, _, cy, _ in lessons:
                if num == target:
                    return self._tap_lesson_and_confirm(target, cy)

            if lessons:
                max_vis = max(num for num, _, _, _ in lessons)
                if target > max_vis:
                    if has_locked:
                        logger.warning(f'Class lesson {target} is locked (max unlocked visible={max_vis})')
                        return False
                    drag_up = True
                else:
                    drag_up = False
            else:
                drag_up = False

            if self._scroll_lesson_list(drag_up) < 2.0:
                unchanged += 1
                if unchanged >= 2:
                    logger.warning(f'Class lesson scroll reached boundary without finding {target}')
                    break
            else:
                unchanged = 0

        return read_selected_class_lesson(self.device.image) == target

    def _select_highest_three_star_lesson(self):
        """Scan unlocked lessons and select the highest 3-starred lesson."""
        best = None
        best_cy = None
        lessons = []

        unchanged = 0
        for _ in range(SCROLL_MAX_ATTEMPTS):
            lessons, has_locked = find_visible_class_lessons(self.device.image)
            for num, _, cy, is_three in lessons:
                if is_three and (best is None or num > best):
                    best = num
                    best_cy = cy

            visible_nums = [num for num, _, _, _ in lessons]
            if has_locked or (visible_nums and max(visible_nums) >= 25):
                break
            if self._scroll_lesson_list(drag_up=True) < 2.0:
                unchanged += 1
                if unchanged >= 2:
                    break
            else:
                unchanged = 0

        if best is None:
            unchanged = 0
            for _ in range(SCROLL_MAX_ATTEMPTS):
                if self._scroll_lesson_list(drag_up=False) < 2.0:
                    unchanged += 1
                    if unchanged >= 2:
                        break
                else:
                    unchanged = 0
                lessons, _ = find_visible_class_lessons(self.device.image)
                for num, _, cy, is_three in lessons:
                    if is_three and (best is None or num > best):
                        best = num
                        best_cy = cy
                if best is not None:
                    break

        if best is None:
            logger.warning('No 3-starred class lesson found')
            return False

        for num, _, cy, _ in lessons:
            if num == best:
                return self._tap_lesson_and_confirm(best, cy)
        return self._select_lesson(best) if best_cy is not None else False

    def _open_sweep_dialog(self):
        """Press 速战 until sweep count modal opens or daily entries report exhausted."""
        retry = Timer(2.0)
        for _ in self.loop(timeout=15):
            if self.appear(DUNGEON_CLONE_EMPTY, offset=CLASS_OFFSET):
                logger.info('Class daily entries exhausted (每日入场次数已用完), stop')
                return False
            if self.appear(DUNGEON_SWEEP_TITLE, offset=CLASS_SWEEP_OFFSET) or self.appear(
                EVENT_SWEEP_TITLE, offset=CLASS_SWEEP_OFFSET
            ):
                return True
            if retry.reached():
                retry.reset()
                logger.info('Open class sweep dialog, press 速战')
                self.device.click(CLASS_SWEEP_BTN)  # alas-lint: allow - guarded by class_sweep_lit() before call
        return False

    def _sweep_confirm_once(self):
        """Tap 最大 then 速战 inside the sweep modal until CLEAR/reward appears."""
        max_tapped = False
        settle = Timer(0.5)
        confirm_retry = Timer(2.0)
        for _ in self.loop(timeout=20):
            if self.handle_reward_popup():
                continue
            if self.appear(EVENT_SWEEP_CLEAR, offset=CLASS_OFFSET):
                return True
            if self.appear(DUNGEON_SWEEP_TITLE, offset=CLASS_SWEEP_OFFSET) or self.appear(
                EVENT_SWEEP_TITLE, offset=CLASS_SWEEP_OFFSET
            ):
                if not max_tapped:
                    logger.info('Set class sweep count to 最大')
                    self.device.click(EVENT_SWEEP_MAX)  # alas-lint: allow - guarded by sweep dialog title
                    max_tapped = True
                    settle = Timer(0.5).start()
                    continue
                if not settle.reached():
                    continue
                confirm_btn = None
                if self.appear(DUNGEON_SWEEP_CONFIRM, offset=CLASS_OFFSET):
                    confirm_btn = DUNGEON_SWEEP_CONFIRM
                elif self.appear(EVENT_SWEEP_CONFIRM, offset=CLASS_OFFSET):
                    confirm_btn = EVENT_SWEEP_CONFIRM
                if confirm_btn is not None and confirm_retry.reached():
                    confirm_retry.reset()
                    logger.info('Confirm class sweep, press 速战')
                    self.device.click(confirm_btn)
        return False

    def _close_sweep_cancel(self):
        """Dismiss sweep count dialog via 取消 when a sweep cannot proceed."""
        retry = Timer(2.0)
        for _ in self.loop(timeout=8):
            if self.appear(EVENT_SWEEP_CANCEL, offset=CLASS_OFFSET):
                if retry.reached():
                    retry.reset()
                    logger.info('Cancel class sweep dialog')
                    self.device.click(EVENT_SWEEP_CANCEL)
                continue
            if self.ui_page_appear(page_class_stage):
                return True
        return False

    def _close_sweep_clear(self):
        """Dismiss CLEAR popup and settle back on `page_class_stage`."""
        retry = Timer(2.0)
        clean = 0
        for _ in self.loop(timeout=12):
            if self.handle_reward_popup():
                clean = 0
                continue
            if self.appear(EVENT_SWEEP_CLEAR, offset=CLASS_OFFSET):
                clean = 0
                if retry.reached():
                    retry.reset()
                    logger.info('Dismiss class sweep CLEAR result, press 确定')
                    self.device.click(EVENT_SWEEP_CLEAR)
                continue
            if self.ui_page_appear(page_class_stage):
                clean += 1
                if clean >= 2:
                    return True
            else:
                clean = 0
        return False

    def _sweep_class(self):
        """Sweep remaining daily class entries via 最大 (up to 3 rounds safeguard)."""
        for _ in range(3):
            rem = read_class_daily_remaining(self.device.image, on_hub=False)
            if rem == 0:
                logger.info('Class daily entries 0 -> 0, stop')
                return True
            if not class_sweep_lit(self.device.image):
                logger.warning('Class 速战 is disabled (not 3-starred or 0 entries), stop')
                return False
            if not self._open_sweep_dialog():
                return True
            if not self._sweep_confirm_once():
                self._close_sweep_cancel()
                return True
            if not self._close_sweep_clear():
                return False
        return True
