"""Dispatch commissions (铁安协同终端 -> 派遣委托) for 雷索纳斯."""

import re

import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import load_image
from module.exception import GameStuckError
from module.logger import logger
from module.ocr.ocr import Ocr
from module.resonance import assets
from module.resonance.page import page_resonance_dispatch
from module.resonance.resonance_ui import ResonanceUI


OFFSET = (5, 5)
DISPATCH_TASK_KEYS = ('patrol', 'drill', 'collect', 'materialize', 'enhance')
DISPATCH_CARDS = {
    'patrol': (0, (29, 256)),       # 义务巡逻
    'drill': (1, (276, 504)),       # 战斗演习
    'collect': (2, (522, 750)),     # 思维搜集
    'materialize': (3, (769, 997)), # 思维具现
    'enhance': (4, (1016, 1244)),   # 强化材料搜集
}
CARD_XRANGES = (
    (29, 256),
    (276, 504),
    (522, 750),
    (769, 997),
    (1016, 1244),
)
DURATION_BOXES = {
    '4h': (773, 508, 818, 538),
    '8h': (816, 466, 844, 510),
    '12h': (842, 508, 886, 538),
    '20h': (816, 535, 844, 578),
}
DURATION_MINUTES = {
    '4h': 240,
    '8h': 480,
    '12h': 720,
    '20h': 1200,
}
CREW_COLS = ((46, 141), (156, 251), (265, 360), (374, 470), (484, 579))
CREW_ROWS = ((164, 275, 258, 274), (294, 405, 388, 404), (424, 535, 518, 534))
CREW_SLOTS = tuple(
    (r_idx, c_idx, (x1 + 8, y1 + 8, x2 - 8, y2 - 8), (x1 + 4, ny1, x2 - 4, ny2))
    for r_idx, (y1, y2, ny1, ny2) in enumerate(CREW_ROWS)
    for c_idx, (x1, x2) in enumerate(CREW_COLS)
)
ROW0_SLOTS = CREW_SLOTS[:5]
ROW1_SLOTS = CREW_SLOTS[5:10]

def _box_button(box, name):
    return Button(area=box, color=(), button=box, name=name)


PLUS_SLOT_BTN = _box_button((128, 550, 174, 598), 'DISPATCH_PLUS_0')
CLAIM_BTN = _box_button((950, 618, 1150, 658), 'DISPATCH_CLAIM')

TEAM_COUNT_OCR = Ocr(
    (555, 42, 625, 75),
    lang='cnocr', threshold=128, alphabet='0123456789/', name='Dispatch teams',
)
CARD_TIME_OCRS = tuple(
    Ocr(
        (cx1 + 51, 215, cx1 + 176, 255),
        lang='cnocr', threshold=128, alphabet='0123456789:', name=f'Dispatch card time {idx}',
    )
    for idx, (cx1, _) in enumerate(CARD_XRANGES)
)


_TASK_TEMPLATE_CACHE = {}


def _load_task_template(task_key):
    """Return cached icon+title RGB patch for one of the 5 dispatch tasks."""
    tpl = _TASK_TEMPLATE_CACHE.get(task_key)
    if tpl is None:
        asset = getattr(assets, f'TEMPLATE_DISPATCH_{task_key.upper()}')
        tpl = load_image(asset.file)
        _TASK_TEMPLATE_CACHE[task_key] = tpl
    return tpl


def classify_card_state(image, card_idx):
    """Classify card header banner as 'idle' (blue), 'active' (orange/yellow), or 'other'."""
    cx1, cx2 = CARD_XRANGES[card_idx]
    mean_rgb = image[86:103, cx1 + 20:cx2 - 20].mean(axis=(0, 1))
    r, g, b = float(mean_rgb[0]), float(mean_rgb[1]), float(mean_rgb[2])
    if b > 190 and b - r > 90:
        return 'idle'
    if r > 190 and g > 130 and b < 90:
        return 'active'
    return 'other'


def count_active_cards(image):
    """Count currently running (orange/yellow header) dispatch cards across slots 0..4."""
    return sum(1 for idx in range(len(CARD_XRANGES)) if classify_card_state(image, idx) == 'active')


def find_idle_task_slot(image, task_key):
    """Find the slot index (0..4) of an idle card matching task_key via icon+title template."""
    tpl = _load_task_template(task_key)
    best_slot = None
    best_score = 0.85
    for idx, (cx1, cx2) in enumerate(CARD_XRANGES):
        if classify_card_state(image, idx) != 'idle':
            continue
        roi = image[120:262, cx1 + 45:cx2 - 45]
        score = float(cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED).max())
        if score >= best_score:
            best_score = score
            best_slot = idx
    return best_slot


def is_duration_selected(image, duration):
    """Return True if the requested dispatch duration pill is highlighted yellow/orange."""
    x1, y1, x2, y2 = DURATION_BOXES[duration]
    mean_rgb = image[y1:y2, x1:x2].mean(axis=(0, 1))
    return bool(mean_rgb[0] > 170 and (float(mean_rgb[0]) - float(mean_rgb[2])) > 100)


def is_portrait_selected(image, nameplate_box):
    """Return True if the crew portrait nameplate strip is highlighted blue."""
    x1, y1, x2, y2 = nameplate_box
    mean_rgb = image[y1:y2, x1:x2].mean(axis=(0, 1))
    return bool(mean_rgb[2] > 190 and (float(mean_rgb[2]) - float(mean_rgb[0])) > 70)


def is_recall_red_visible(image):
    """Return True if the red '召回' button is shown in the bottom-right action slot."""
    roi = image[605:665, 930:1220]
    r = roi[:, :, 0].astype(np.int16)
    g = roi[:, :, 1].astype(np.int16)
    b = roi[:, :, 2].astype(np.int16)
    mask = (r > 120) & (g < 100) & (r - g > 80) & (r - b > 80)
    return int(np.count_nonzero(mask)) >= 5000


def is_send_yellow_visible(image):
    """Return True if the bottom-right '派遣' button is active yellow."""
    mean_rgb = image[618:658, 925:1055].mean(axis=(0, 1))
    return bool(mean_rgb[0] > 100 and (float(mean_rgb[0]) - float(mean_rgb[2])) > 60)


def parse_team_count(image):
    """Parse '当前委托队伍 used/total' from the header; return (used, total) or None."""
    text = TEAM_COUNT_OCR.ocr(image)
    match = re.search(r'(\d+)\s*/\s*(\d+)', str(text))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def parse_card_remaining_minutes(image, card_idx):
    """Parse remaining HH:MM:SS on an active dispatch card into rounded-up minutes."""
    text = CARD_TIME_OCRS[card_idx].ocr(image)
    match = re.search(r'(\d{2}):?(\d{2}):?(\d{2})', str(text))
    if not match:
        return None
    hours, minutes, seconds = int(match.group(1)), int(match.group(2)), int(match.group(3))
    return hours * 60 + minutes + (1 if seconds > 0 else 0)


class ResonanceDispatch(ResonanceUI):
    """Claim finished dispatches and send up to 2 squads on configured commissions."""

    def _select_card(self, card_idx):
        """Tap one of the 5 top dispatch task cards."""
        cx1, cx2 = CARD_XRANGES[card_idx]
        card_btn = _box_button((cx1 + 30, 140, cx2 - 30, 320), f'DISPATCH_CARD_{card_idx}')
        clicked = False
        wait = Timer(0.6)
        for _ in self.loop(timeout=6):
            if self.handle_reward_popup():
                continue
            if self.ui_page_appear(page_resonance_dispatch, offset=OFFSET):
                if not clicked:
                    self.device.click(card_btn)
                    clicked = True
                    wait.reset()
                elif wait.reached():
                    return

    def _inspect_and_claim_card(self, card_idx):
        """Select a non-idle card; return ('running', minutes) or claim it and return ('claimed', None)."""
        self._select_card(card_idx)
        if self.appear(assets.DISPATCH_RECALL, offset=OFFSET) or is_recall_red_visible(self.device.image):
            return 'running', parse_card_remaining_minutes(self.device.image, card_idx)
        if classify_card_state(self.device.image, card_idx) == 'idle':
            return 'claimed', None
        if any(is_duration_selected(self.device.image, dur) for dur in DURATION_BOXES):
            return 'idle', None

        retry = Timer(2)
        settle = Timer(1.2)
        claimed = False
        for _ in self.loop(timeout=12):
            if self.handle_reward_popup():
                claimed = True
                settle.reset()
                continue
            if claimed:
                if settle.reached():
                    return 'claimed', None
                continue
            if self.ui_page_appear(page_resonance_dispatch, offset=OFFSET):
                if self.appear(assets.DISPATCH_RECALL, offset=OFFSET) or is_recall_red_visible(self.device.image):
                    return 'running', parse_card_remaining_minutes(self.device.image, card_idx)
                if classify_card_state(self.device.image, card_idx) == 'idle':
                    return 'claimed', None
                if retry.reached():
                    self.device.click(CLAIM_BTN)
                    retry.reset()
        return 'idle', None

    def _next_unseen_non_idle_slot(self, seen):
        """Return first slot index not in seen whose header is non-idle, or None."""
        for card_idx in range(len(CARD_XRANGES)):
            if card_idx not in seen and classify_card_state(self.device.image, card_idx) != 'idle':
                return card_idx
        return None

    def claim_completed_and_scan(self):
        """Inspect non-idle cards cleanly across card shifts, claiming finished ones."""
        seen = set()
        running_by_slot = {}
        for _ in range(10):
            card_idx = self._next_unseen_non_idle_slot(seen)
            if card_idx is None:
                break
            status, mins = self._inspect_and_claim_card(card_idx)
            if status == 'running':
                seen.add(card_idx)
                if mins is not None:
                    running_by_slot[card_idx] = mins
            elif status == 'claimed':
                # Claiming reorders cards back to idle order, so rescan running slots cleanly.
                seen.clear()
                running_by_slot.clear()
            else:
                seen.add(card_idx)
        return list(running_by_slot.values())

    def _select_duration(self, duration):
        """Select desired duration ('4h', '8h', '12h', '20h') on the bottom diamond selector."""
        btn = _box_button(DURATION_BOXES[duration], f'DISPATCH_DUR_{duration}')
        retry = Timer(1.2)
        for _ in self.loop(timeout=8):
            if self.ui_page_appear(page_resonance_dispatch, offset=OFFSET):
                if is_duration_selected(self.device.image, duration):
                    return
                if retry.reached():
                    self.device.click(btn)
                    retry.reset()
        raise GameStuckError(f'Resonance dispatch duration {duration} was not selected')

    def _open_crew_drawer(self):
        """Click the first member '+' slot to expand 选择派遣队员."""
        retry = Timer(1.5)
        for _ in self.loop(timeout=10):
            if self.appear(assets.DISPATCH_CREW_DRAWER, offset=OFFSET):
                return
            if self.ui_page_appear(page_resonance_dispatch, offset=OFFSET) and retry.reached():
                self.device.click(PLUS_SLOT_BTN)
                retry.reset()
        raise GameStuckError('Resonance dispatch crew drawer did not open')

    def _click_crew_row(self, slots):
        """Click unselected crew portraits in one row, wait for highlight, and return selected count."""
        clicked_slots = []
        for row_idx, col_idx, click_box, nameplate_box in slots:
            if not is_portrait_selected(self.device.image, nameplate_box):
                btn = _box_button(click_box, f'DISPATCH_CREW_{row_idx}_{col_idx}')
                if self.appear(assets.DISPATCH_CREW_DRAWER, offset=OFFSET):
                    self.device.click(btn)
                    clicked_slots.append(nameplate_box)
        if not clicked_slots:
            return sum(1 for _, _, _, nb in slots if is_portrait_selected(self.device.image, nb))
        settle = Timer(0.6).start()
        for _ in self.loop(skip_first=False, timeout=2):
            if all(is_portrait_selected(self.device.image, nb) for nb in clicked_slots) or settle.reached():
                break
        return sum(1 for _, _, _, nb in slots if is_portrait_selected(self.device.image, nb))

    def _pick_five_crew(self):
        """Directly select the top 5 available members (Row 0, or Row 1 if Row 0 is all busy)."""
        self._open_crew_drawer()
        picked = self._click_crew_row(ROW0_SLOTS)
        if 0 < picked < 5:
            picked = self._click_crew_row(ROW0_SLOTS)
        elif picked == 0:
            picked = self._click_crew_row(ROW1_SLOTS)
        return picked

    def _close_crew_drawer(self):
        """Close 选择派遣队员 via its '<' handle tab."""
        self.interval_clear(assets.DISPATCH_CREW_DRAWER)
        for _ in self.loop(timeout=8):
            if self.appear(assets.DISPATCH_CREW_DRAWER, offset=OFFSET):
                self.appear_then_click(assets.DISPATCH_CREW_DRAWER, offset=OFFSET, interval=1.5)
            else:
                return
        raise GameStuckError('Resonance dispatch crew drawer did not close')

    def _send_dispatch(self, active_before):
        """Click bright yellow '派遣' until active card count rises or red '召回' appears."""
        self.interval_clear(assets.DISPATCH_SEND_READY)
        for _ in self.loop(timeout=12):
            if self.handle_reward_popup():
                continue
            if self.ui_page_appear(page_resonance_dispatch, offset=OFFSET):
                if (count_active_cards(self.device.image) > active_before
                        or self.appear(assets.DISPATCH_RECALL, offset=OFFSET)
                        or is_recall_red_visible(self.device.image)):
                    return True
                if (self.appear(assets.DISPATCH_SEND_READY, offset=OFFSET)
                        and is_send_yellow_visible(self.device.image)):
                    self.appear_then_click(assets.DISPATCH_SEND_READY, offset=OFFSET, interval=2)
        return False

    def dispatch_task(self, task_key, duration):
        """Locate task_key dynamically, pick 5 crew and duration, and dispatch; return minutes or None."""
        card_idx = find_idle_task_slot(self.device.image, task_key)
        if card_idx is None:
            return None
        active_before = count_active_cards(self.device.image)
        self._select_card(card_idx)
        if classify_card_state(self.device.image, card_idx) != 'idle':
            return None
        self._select_duration(duration)
        picked = self._pick_five_crew()
        self._close_crew_drawer()
        if picked < 1:
            logger.warning('琐呐派遣委托 %s 未选到可用队员，跳过', task_key)
            return None
        if self._send_dispatch(active_before):
            logger.info('琐呐派遣委托已出发: %s (槽位%d, %s, %d人)', task_key, card_idx, duration, picked)
            return DURATION_MINUTES[duration]
        return None

    def run(self):
        """Claim completed dispatches, dispatch up to 2 configured tasks, return to main, and schedule."""
        self.ui_ensure(page_resonance_dispatch, skip_first_screenshot=False)
        remaining = self.claim_completed_and_scan()

        configured = []
        for key in (self.config.ResonanceDispatch_Task1, self.config.ResonanceDispatch_Task2):
            if key in DISPATCH_CARDS and key not in configured:
                configured.append(key)

        duration = self.config.ResonanceDispatch_Duration
        if duration not in DURATION_BOXES:
            duration = '12h'

        team_info = parse_team_count(self.device.image)
        used, total = team_info if team_info is not None else (len(remaining), 2)

        for task_key in configured:
            if used >= total:
                break
            if find_idle_task_slot(self.device.image, task_key) is None:
                continue
            mins = self.dispatch_task(task_key, duration)
            if mins is not None:
                remaining.append(mins)
                used += 1

        self.ui_goto_main()
        if remaining:
            delay = max(5, min(remaining) + 1)
            logger.info('琐呐派遣委托完成，预计 %d 分钟后收取', delay)
            self.config.task_delay(minute=delay)
        else:
            logger.info('琐呐派遣委托完成，当前无进行中队伍')
            self.config.task_delay(server_update=True)
