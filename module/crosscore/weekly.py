"""碎星虚影（周本） of 交错战线 (Cross Core)."""

import datetime
import re

import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import crop
from module.crosscore.assets import (BOOT_BACK, DIALOG_CONFIRM, E_5_1, EXERCISE_LOSE, EXERCISE_RESULT,
    EXERCISE_RESULT_CLICK, EXERCISE_WIN, EXPLORE_SORTIE, WEEKLY_ACTION_START, WEEKLY_ACTIVITY_ENTRY,
    WEEKLY_ACTIVITY_HEADER, WEEKLY_BATTLE_START, WEEKLY_CRYSTAL_OCR, WEEKLY_FORMATION_TITLE,
    WEEKLY_MAP_GOLIKE, WEEKLY_MAP_HUD, WEEKLY_MAP_NECRO, WEEKLY_MAP_NOS, WEEKLY_OVERFLOW_CONFIRM,
    WEEKLY_RESET_OCR, WEEKLY_SHATTER_CARD, WEEKLY_STAGE_REWARD_BTN, WEEKLY_STAGE_SLOT_1,
    WEEKLY_STAGE_SLOT_2, WEEKLY_STAGE_SLOT_3, WEEKLY_STAGE_SLOT_4)
from module.crosscore.crosscore_ui import CrosscoreUI
from module.crosscore.page import page_main
from module.crosscore.utils import image_diff
from module.crosscore.weekly_board import (
    ENEMY_SEARCH_AREA, TILE_SEARCH_AREA, find_green_tiles, find_map_enemies, is_my_turn,
    is_near_any, pick_combat_candidates, split_crystal_num_end,
)
from module.logger import logger
from module.ocr.ocr import Ocr

MAP_BUTTONS = {'戈里刻虚影': WEEKLY_MAP_GOLIKE, '诺斯虚影': WEEKLY_MAP_NOS, '尼克罗虚影': WEEKLY_MAP_NECRO}
STAGE_INDEX = {'第1关': 1, '第2关': 2, '第3关': 3, '第4关': 4, '第5关': 5, '第6关': 6}
STAGE_SLOTS = (WEEKLY_STAGE_SLOT_1, WEEKLY_STAGE_SLOT_2, WEEKLY_STAGE_SLOT_3, WEEKLY_STAGE_SLOT_4)

# Middle-column stage list (`x 440..820, y 130..635`), 4 cards fit completely.
STAGE_LIST_BAND = (440, 130, 820, 635)
# Selected stage card shows ~891 gold border pixels vs 1~8 on idle cards.
STAGE_GOLD_PIXELS = 200

BATTLEFIELD_AREA = (200, 100, 1000, 600)
WEEKLY_CRYSTAL_CAP_AREA = (156, 634, 202, 653)
MAX_WEEKLY_RUNS = 20

CRYSTAL_PATTERN = re.compile(r'(\d+)\s*/\s*(\d+)')
COUNTDOWN_PATTERN = re.compile(r'(?:(\d+)\s*天\s*)?(\d{1,2}):(\d{2}):(\d{2})')
RESET_MARGIN_SECONDS = 60
MAX_RESET_SECONDS = 8 * 86400


class CrystalOcr(Ocr):
    """Luminance-normalized white-padded OCR for crystal numerator/cap digits."""

    def pre_process(self, image):
        lum = image.min(axis=2).astype(np.float32)
        inv = np.clip((235.0 - lum) * (255.0 / (235.0 - self.threshold)), 0, 255).astype(np.uint8)
        return cv2.copyMakeBorder(inv, 4, 4, 12, 12, cv2.BORDER_CONSTANT, value=255)


def parse_crystal_counter(text):
    """Parse `'45/540'` into `(45, 540)` or None if unreadable."""
    match = CRYSTAL_PATTERN.search((text or '').strip())
    if not match:
        return None
    current, total = int(match.group(1)), int(match.group(2))
    return (current, total) if total >= 100 else None


def parse_weekly_countdown(text):
    """Parse `'2天 04:58:54后重置'` into total remaining seconds (0 if invalid)."""
    match = COUNTDOWN_PATTERN.search((text or '').strip())
    if not match:
        return 0
    days = int(match.group(1) or 0)
    hours, minutes, seconds = int(match.group(2)), int(match.group(3)), int(match.group(4))
    if hours >= 24 or minutes >= 60 or seconds >= 60:
        return 0
    total = days * 86400 + hours * 3600 + minutes * 60 + seconds
    return total if (RESET_MARGIN_SECONDS <= total <= MAX_RESET_SECONDS) else 0


def _next_tile_button(image, state):
    """Pick first untried walkable tile `(point, action)` as a clickable Button."""
    ordered = sorted(
        pick_combat_candidates(image, state.get('pushed', ())),
        key=lambda c: c[1] == 'move' and is_near_any(c[0][0], c[0][1], state['history'], 45, 45),
    )
    for point, action in ordered:
        if is_near_any(point[0], point[1], state['tried'], 35, 35):
            continue
        state['tried'].append(point)
        if action == 'move':
            state['history'] = (state['history'] + [point])[-6:]
        state['pending_push'] = point if action == 'push_switch' else None
        tx, ty = point
        logger.info(f'Tactical move [{action}] -> ({tx}, {ty})')
        area = (max(0, tx - 15), max(0, ty - 15), min(1280, tx + 15), min(720, ty + 15))
        return Button(area=area, color=(0, 0, 0), button=area, name='WEEKLY_TILE')
    return None


class CrosscoreWeekly(CrosscoreUI):
    """Cross Core weekly dungeon (`碎星虚影`)."""

    def run(self):
        """Run weekly dungeon farming until crystal cap, then schedule past reset."""
        logger.hr('交错周本（碎星虚影）', level=1)
        self.ui_ensure(page_main)

        map_name = str(self.config.CrosscoreWeekly_Map)
        if map_name not in MAP_BUTTONS:
            logger.warning(f'Unknown weekly map <{map_name}>, fall back to 戈里刻虚影')
            map_name = '戈里刻虚影'

        stage_idx = STAGE_INDEX.get(str(self.config.CrosscoreWeekly_Stage))
        if stage_idx is None:
            logger.warning(f'Unknown weekly stage <{self.config.CrosscoreWeekly_Stage}>, fall back to 第6关')
            stage_idx = 6

        logger.info(f'Weekly target: {map_name} - 第{stage_idx}关')
        if not self.weekly_enter_maps():
            logger.warning('Cannot open 碎星虚影 map selection, retry in 15 minutes')
            self.back_to_main()
            self.config.task_delay(minute=15)
            return

        if self._weekly_cap_reached():
            target = self.compute_weekly_reset_target()
            self.back_to_main()
            self.config.task_delay(target=target)
            return

        if not self.weekly_pick_map(map_name):
            logger.warning('Cannot open stage list, retry in 15 minutes')
            self.back_to_main()
            self.config.task_delay(minute=15)
            return

        result = self.weekly_farm(stage_idx)
        if result == 'cap':
            target = self.compute_weekly_reset_target()
            self.back_to_main()
            self.config.task_delay(target=target)
            return

        logger.warning(f'Weekly dungeon stopped ({result}), retry in 15 minutes')
        self.back_to_main()
        self.config.task_delay(minute=15)

    def weekly_farm(self, stage_idx):
        """Repeat stage clears from stage selection screen until crystal cap is reached."""
        for run_num in range(1, MAX_WEEKLY_RUNS + 1):
            if self._weekly_cap_reached():
                return 'cap'
            logger.hr(f'碎星虚影 第{run_num}轮', level=1)
            if not self.weekly_pick_stage(stage_idx) or not self.weekly_start_action():
                return 'entry_failed'
            status = self.weekly_run_stage()
            if status != 'cleared':
                return status
        return 'cap' if self._weekly_cap_reached() else 'max_runs'

    def weekly_run_stage(self):
        """Play one weekly stage run from tactical deployment back to stage selection."""
        logger.hr('周本战棋作战', level=2)
        state = {
            'fought': False, 'last_board': None, 'tried': [], 'history': [],
            'pushed': [], 'pending_push': None, 'win_timer': Timer(1.5),
        }

        for _ in self.loop(timeout=600):
            self.device.stuck_record_clear()
            if state['fought'] and self.appear(WEEKLY_STAGE_REWARD_BTN, offset=(20, 20), similarity=0.80) \
                    and self.appear(WEEKLY_BATTLE_START, offset=(20, 20), similarity=0.80):
                self.wait_until_still(STAGE_LIST_BAND, timeout=2)
                self.device.click_record_clear()
                logger.info('Weekly stage cleared and returned to stage selection')
                return 'cleared'

            outcome = self._handle_combat_results(state)
            if outcome == 'defeat':
                return 'defeat'
            if outcome:
                continue

            if self.appear(WEEKLY_MAP_HUD, offset=(20, 20), similarity=0.80, interval=1.8) \
                    and is_my_turn(self.device.image):
                self._step_tactical_map(state)

        logger.warning('Weekly stage run timed out')
        return 'timeout'

    def _handle_combat_results(self, state):
        """Handle BOSS reward popup, battle victory, or battle defeat screens."""
        if self.appear(E_5_1, offset=(30, 30), similarity=0.80, interval=1.5):
            logger.info('Weekly BOSS reward popup, click to continue')
            state['fought'] = True
            state['tried'].clear()
            state['history'].clear()
            self.device.click_record_clear()
            self.device.click(EXERCISE_RESULT_CLICK)
            return 'handled'

        if self.appear(EXERCISE_WIN, offset=(20, 20), similarity=0.80, threshold=30) \
                or self.appear(EXERCISE_RESULT, offset=(20, 20), similarity=0.80):
            if state['win_timer'].reached():
                logger.info('Weekly battle won, click to continue')
                state['win_timer'].reset()
                state['fought'] = True
                state['tried'].clear()
                state['history'].clear()
                self.device.click_record_clear()
                self.device.click(EXERCISE_RESULT_CLICK)
            return 'handled'

        if self.appear(EXERCISE_LOSE, offset=(20, 20), similarity=0.80, threshold=30, interval=1.5):
            logger.warning('Weekly battle defeat detected')
            self.device.click_record_clear()
            self.device.click(EXERCISE_RESULT_CLICK)
            return 'defeat'
        return None

    def _step_tactical_map(self, state):
        """Wait for board to settle, then click best walkable tile toward BOSS or mob."""
        self.wait_until_still(BATTLEFIELD_AREA, timeout=1.2, threshold=3.5)
        if self.appear(WEEKLY_MAP_HUD, offset=(20, 20), similarity=0.80):
            cur_board = crop(self.device.image, BATTLEFIELD_AREA, copy=True)
            if state['last_board'] is None or image_diff(state['last_board'], cur_board) >= 5:
                state['tried'].clear()
                if state['last_board'] is not None and state.get('pending_push') is not None:
                    state['pushed'].append(state['pending_push'])
                state['pending_push'] = None
                self.device.click_record_clear()
            state['last_board'] = cur_board
            tile_btn = _next_tile_button(self.device.image, state)
            if tile_btn is not None:
                self.device.click(tile_btn)
                return
            logger.warning('No untried walkable tile found on tactical board')
            state['tried'].clear()

    def read_weekly_crystals(self):
        """Read bottom-left `本周报酬微晶` counter `(current, total)` or None."""
        x_cut = split_crystal_num_end(self.device.image)
        num_area = (WEEKLY_CRYSTAL_OCR.area[0], WEEKLY_CRYSTAL_OCR.area[1], x_cut, WEEKLY_CRYSTAL_OCR.area[3])
        cap_area = (x_cut + 2, 634, 218, 653)
        num_ocr = CrystalOcr(num_area, lang='cnocr', threshold=145, alphabet='0123456789/', name='WEEKLY_CRYSTAL')
        den_ocr = CrystalOcr(cap_area, lang='cnocr', threshold=115, alphabet='0123456789/', name='WEEKLY_CRYSTAL_CAP')
        num_text = num_ocr.ocr(self.device.image).split('/')[0].strip()
        den_text = den_ocr.ocr(self.device.image).lstrip('/').strip()
        if not den_text.isdigit() or int(den_text) < 100:
            den_text = '540'
        return parse_crystal_counter(f'{num_text}/{den_text}')

    def back_to_main(self):
        """Dismiss settlement popups and retreat from any unfinished map before returning home."""
        state = {'fought': False, 'tried': [], 'history': [], 'win_timer': Timer(1.5)}
        for _ in self.loop(timeout=20):
            self.device.stuck_record_clear()
            if self._handle_combat_results(state):
                continue
            if self.appear(WEEKLY_MAP_HUD, offset=(20, 20), similarity=0.80):
                if self.appear(DIALOG_CONFIRM, offset=(20, 20), interval=2):
                    self.device.click_record_clear()
                    self.device.click(DIALOG_CONFIRM)
                    self.wait_until_disappear(DIALOG_CONFIRM, offset=(20, 20), timeout=5)
                    continue
                if self.appear(BOOT_BACK, offset=(20, 20), interval=2):
                    self.device.click(BOOT_BACK)
                continue
            break
        return super().back_to_main()

    def read_reset_seconds(self):
        """Read bottom-left reset countdown in seconds, or 0 if unreadable."""
        ocr = Ocr(WEEKLY_RESET_OCR, lang='cnocr', letter=(210, 210, 215),
                  threshold=128, name='WEEKLY_RESET')
        return parse_weekly_countdown(ocr.ocr(self.device.image))

    def _weekly_cap_reached(self):
        """Whether current weekly crystal count has reached the weekly limit."""
        if self.config.CrosscoreWeekly_IgnoreCap:
            logger.info('IgnoreCap enabled, skip weekly crystal cap check')
            return False
        crystals = self.read_weekly_crystals()
        if crystals is None:
            logger.info('Could not read weekly crystal counter, continue into stage')
            return False
        current, total = crystals
        logger.info(f'Weekly crystal progress: {current}/{total}')
        if current >= total:
            logger.info('Weekly crystal cap reached, schedule after next weekly reset')
            return True
        return False

    def compute_weekly_reset_target(self):
        """Compute next weekly reset `datetime` from on-screen countdown (or Monday 04:00 fallback)."""
        seconds = self.read_reset_seconds()
        now = datetime.datetime.now()
        if seconds > 0:
            return now + datetime.timedelta(seconds=seconds + RESET_MARGIN_SECONDS)

        # Fallback: next Monday 04:00 local time.
        days_ahead = (7 - now.weekday()) % 7
        candidate = now.replace(hour=4, minute=0, second=0, microsecond=0) \
            + datetime.timedelta(days=days_ahead)
        if candidate <= now:
            candidate += datetime.timedelta(days=7)
        return candidate

    def weekly_enter_maps(self):
        """Navigate from `page_main` through 出击 → 活动探索 → 碎星虚影 into the 3-map screen."""
        logger.hr('进入碎星虚影', level=2)
        for _ in self.loop(timeout=60):
            if self.handle_item_popup() or self.handle_lobby_popup():
                continue
            if self.appear(WEEKLY_MAP_NOS, offset=(20, 20), similarity=0.80) \
                    or self.appear(WEEKLY_STAGE_REWARD_BTN, offset=(20, 20), similarity=0.80):
                self.wait_until_still(WEEKLY_MAP_GOLIKE.area, timeout=2)
                return True
            if self.appear(WEEKLY_SHATTER_CARD, offset=(450, 40), similarity=0.80):
                self.wait_until_still(WEEKLY_SHATTER_CARD.button, timeout=2)
                if self.appear(WEEKLY_SHATTER_CARD, offset=(450, 40), similarity=0.80, interval=2):
                    logger.info('活动探索 page, press 碎星虚影')
                    self.device.click(WEEKLY_SHATTER_CARD)
                continue
            if self.appear(WEEKLY_ACTIVITY_HEADER, offset=(20, 20), similarity=0.80, interval=2):
                logger.info('活动探索 page, swipe left to find 碎星虚影')
                self.device.swipe((950, 380), (300, 380), duration=0.6)
                self.device.click_record_clear()
                continue
            if self.appear(WEEKLY_ACTIVITY_ENTRY, offset=(20, 20), similarity=0.80):
                self.wait_until_still(WEEKLY_ACTIVITY_ENTRY.area, timeout=2)
                if self.appear(WEEKLY_ACTIVITY_ENTRY, offset=(20, 20), similarity=0.80, interval=2):
                    logger.info('Sortie page, press 活动探索')
                    self.device.click(WEEKLY_ACTIVITY_ENTRY)
                continue
            if self.appear(EXPLORE_SORTIE, offset=(20, 20), interval=2):
                logger.info('Lobby, press 出击')
                self.device.click(EXPLORE_SORTIE)
        logger.warning('Cannot reach 碎星虚影 map selection')
        return False

    def weekly_pick_map(self, map_name):
        """Click the configured map card on the 3-map screen until the stage list opens."""
        logger.hr(f'选择地图: {map_name}', level=2)
        self._stage_scroll_pos = None
        map_btn = MAP_BUTTONS[map_name]
        for _ in self.loop(timeout=30):
            if self.appear(WEEKLY_STAGE_REWARD_BTN, offset=(20, 20), similarity=0.80) \
                    and self.appear(WEEKLY_BATTLE_START, offset=(20, 20), similarity=0.80):
                self.wait_until_still(STAGE_LIST_BAND, timeout=2)
                return True
            if self.appear(WEEKLY_MAP_NOS, offset=(20, 20), similarity=0.80) \
                    and self.appear(map_btn, offset=(20, 20), similarity=0.80, interval=2):
                logger.info(f'Select map {map_name}')
                self.device.click(map_btn)
        logger.warning(f'Cannot open stage list for map {map_name}')
        return False

    def weekly_pick_stage(self, stage_idx):
        """Select stage `stage_idx` (1..6); stages 5..6 scroll to bottom (`slots 3..4`)."""
        logger.hr(f'选择关卡: 第{stage_idx}关', level=2)
        if stage_idx >= 5:
            if getattr(self, '_stage_scroll_pos', None) != 'bottom':
                self.weekly_scroll(top=False)
                self._stage_scroll_pos = 'bottom'
            slot = stage_idx - 2
        else:
            if getattr(self, '_stage_scroll_pos', None) != 'top':
                self.weekly_scroll(top=True)
                self._stage_scroll_pos = 'top'
            slot = stage_idx
        for _ in self.loop(timeout=20):
            if self._stage_slot_selected(slot):
                logger.info(f'Stage 第{stage_idx}关 (slot {slot}) is selected')
                return True
            if self.appear(WEEKLY_BATTLE_START, offset=(20, 20), similarity=0.80, interval=1.5):
                logger.info(f'Click stage slot {slot} for 第{stage_idx}关')
                self.device.click(STAGE_SLOTS[slot - 1])
        logger.warning(f'Cannot select stage 第{stage_idx}关 (slot {slot})')
        return False

    def weekly_scroll(self, top, swipes=3):
        """Drag stage list to its top (`top=True`) or bottom (`top=False`) until clamped."""
        p1, p2 = ((630, 220), (630, 540)) if top else ((630, 540), (630, 200))
        self.device.screenshot()
        for _ in range(swipes):
            before = self.image_crop(STAGE_LIST_BAND, copy=True)
            self.device.swipe(p1, p2, duration=0.9)
            self.wait_until_still(STAGE_LIST_BAND, timeout=2)
            self.device.screenshot()
            after = self.image_crop(STAGE_LIST_BAND, copy=True)
            if image_diff(before, after) < 1:
                break
        self.device.click_record_clear()

    def _stage_slot_selected(self, slot):
        """Whether visible slot `slot` (1..4) has its golden selection border."""
        if not self.device.has_cached_image:
            self.device.screenshot()
        im = self.device.image
        y_top, y_bot = 135 + 128 * (slot - 1), 245 + 128 * (slot - 1)
        edges = (
            crop(im, (440, y_top, 816, y_top + 6), copy=False),
            crop(im, (440, y_bot - 6, 816, y_bot), copy=False),
            crop(im, (439, y_top, 446, y_bot), copy=False),
            crop(im, (811, y_top, 817, y_bot), copy=False),
        )
        warm = sum(
            int(((roi[:, :, 0] > 170) & (roi[:, :, 1] > 130)
                 & ((roi[:, :, 0].astype(int) - roi[:, :, 2].astype(int)) > 55)).sum())
            for roi in edges
        )
        return warm >= STAGE_GOLD_PIXELS

    def weekly_start_action(self):
        """Click `开始战斗` on stage list, then `开始行动` on formation (default Team 1)."""
        logger.hr('开始行动', level=2)
        for _ in self.loop(timeout=30):
            if self.appear(WEEKLY_OVERFLOW_CONFIRM, offset=(20, 20), similarity=0.80, interval=2):
                logger.info('Weekly reward overflow prompt, press 开启')
                self.device.click_record_clear()
                self.device.click(WEEKLY_OVERFLOW_CONFIRM)
                self.wait_until_disappear(WEEKLY_OVERFLOW_CONFIRM, offset=(20, 20), timeout=5)
                continue
            if self.appear(WEEKLY_FORMATION_TITLE, offset=(20, 20), similarity=0.80) \
                    and self.appear(WEEKLY_ACTION_START, offset=(20, 20), similarity=0.80):
                self.wait_until_still(WEEKLY_ACTION_START.area, timeout=2)
                if self.appear(WEEKLY_ACTION_START, offset=(20, 20), similarity=0.80, interval=2):
                    logger.info('Formation page, press 开始行动')
                    self.device.click(WEEKLY_ACTION_START)
                    if self.wait_until_disappear(WEEKLY_ACTION_START, offset=(20, 20), timeout=8):
                        return True
                continue
            if self.appear(WEEKLY_BATTLE_START, offset=(20, 20), similarity=0.80, interval=2):
                logger.info('Stage page, press 开始战斗')
                self.device.click(WEEKLY_BATTLE_START)
        logger.warning('Cannot start weekly action from formation page')
        return False
