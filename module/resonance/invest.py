"""Commodity investment at the current station exchange for 雷索纳斯."""

import re

import cv2
import numpy as np

from module.base.timer import Timer
from module.logger import logger
from module.ocr.ocr import Ocr
from module.resonance import assets
from module.resonance.fatigue import ResonanceFatigue
from module.resonance.map_nav import _make_point_button
from module.resonance.page import page_resonance_trade_hub, page_resonance_trade_invest

OFFSET = (5, 5)
GRID_X0 = 63
GRID_Y0 = 145
GRID_DX = 127
GRID_DY = 132
CARD_W = 110
CARD_H = 125
MAX_INVEST_LEVEL = 20

INVEST_LEVEL_AREA = (594, 450, 662, 482)
INVEST_COST_AREA = (1080, 395, 1225, 430)

INVEST_LEVEL_OCR = Ocr([], lang='cnocr', threshold=128, alphabet='LVOo.0123456789', name='Invest level')
INVEST_COST_OCR = Ocr([], lang='cnocr', threshold=128, alphabet='0123456789', name='Invest cost')


def parse_invest_level(text):
    """Parse commodity level text like 'LV.O', 'V.14', 'LV.20' into integer 0..20."""
    cleaned = str(text or '').replace('O', '0').replace('o', '0')
    match = re.search(r'(\d+)', cleaned)
    if not match:
        return None
    val = int(match.group(1))
    return val if 0 <= val <= MAX_INVEST_LEVEL else None


def _yellow_mask_count(patch):
    r = patch[:, :, 0].astype(np.int16)
    g = patch[:, :, 1].astype(np.int16)
    b = patch[:, :, 2].astype(np.int16)
    return int(((r > 105) & (g > 75) & (b < 60) & ((r - b) > 65) & ((g - b) > 45)).sum())


def is_invest_panel_maxed(image):
    """Return True when the right-side detail panel shows the yellow '已满级' badge."""
    return _yellow_mask_count(image[220:254, 772:855]) >= 800


def is_invest_slot_selected(image, row, col):
    """Return True when the commodity slot (row, col) has the active yellow border on any edge."""
    x1 = GRID_X0 + col * GRID_DX
    y1 = GRID_Y0 + row * GRID_DY
    top_hits = _yellow_mask_count(image[y1:y1 + 10, x1 + 8:x1 + 102])
    bot_hits = _yellow_mask_count(image[y1 + 110:y1 + 125, x1 + 8:x1 + 102])
    left_hits = _yellow_mask_count(image[y1 + 10:y1 + 112, max(0, x1 - 2):x1 + 6])
    right_hits = _yellow_mask_count(image[y1 + 10:y1 + 112, x1 + 102:x1 + 112])
    return top_hits >= 120 or bot_hits >= 250 or (top_hits + bot_hits + left_hits + right_hits) >= 450


def inspect_invest_slot(image, row, col, lock_gray):
    """Classify slot (row, col) as 'empty', 'locked', or 'unlocked'."""
    if is_invest_slot_selected(image, row, col):
        return 'unlocked'
    x1 = GRID_X0 + col * GRID_DX
    y1 = GRID_Y0 + row * GRID_DY
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    footer_mean = float(gray[y1 + 112:y1 + 122, x1 + 15:x1 + 95].mean())
    is_low_sat = True
    if image.ndim == 3:
        bot = image[y1 + 112:y1 + 122, x1 + 15:x1 + 95]
        is_low_sat = float((bot.max(axis=2) - bot.min(axis=2)).mean()) < 30.0
    if footer_mean > 110 and is_low_sat:
        return 'empty'
    patch = gray[y1 + 25:y1 + 95, x1 + 20:x1 + 90]
    score = float(cv2.matchTemplate(patch, lock_gray, cv2.TM_CCOEFF_NORMED).max())
    return 'locked' if score >= 0.78 else 'unlocked'


def invest_slot_button(row, col):
    """Build clickable Button centered on commodity grid slot (row, col)."""
    cx = GRID_X0 + col * GRID_DX + CARD_W // 2
    cy = GRID_Y0 + row * GRID_DY + CARD_H // 2
    return _make_point_button(cx, cy, 'INVEST_SLOT_%d_%d' % (row, col), radius=15)


class ResonanceInvest(ResonanceFatigue):
    """Station commodity investment controller."""

    def read_invest_level(self):
        """Read current commodity level (0..20) from the middle tag card."""
        x1, y1, x2, y2 = INVEST_LEVEL_AREA
        inv = 255 - self.device.image[y1:y2, x1:x2].min(axis=2)
        up = np.repeat(np.repeat(inv, 2, axis=0), 2, axis=1)
        rgb = np.stack((up, up, up), axis=2)
        raw = INVEST_LEVEL_OCR.ocr([rgb], direct_ocr=True)
        text = raw[0] if isinstance(raw, list) and raw else str(raw or '')
        return parse_invest_level(text)

    def read_invest_cost(self):
        """Read required investment amount from the right panel, or None."""
        x1, y1, x2, y2 = INVEST_COST_AREA
        gray = self.device.image[y1:y2, x1:x2].max(axis=2)
        rgb = np.stack((gray, gray, gray), axis=2)
        raw = INVEST_COST_OCR.ocr([rgb], direct_ocr=True)
        text = raw[0] if isinstance(raw, list) and raw else str(raw or '')
        digits = ''.join(ch for ch in str(text) if ch.isdigit())
        return int(digits) if digits else None

    def _select_invest_slot(self, row, col):
        """Select grid slot (row, col) and wait until its yellow border appears."""
        if is_invest_slot_selected(self.device.image, row, col):
            return True
        btn = invest_slot_button(row, col)
        click_timer = Timer(0.8)
        clicks = 0
        for _ in self.loop(timeout=4):
            if self.ui_page_appear(page_resonance_trade_invest, offset=OFFSET):
                if is_invest_slot_selected(self.device.image, row, col):
                    self.device.click_record_clear()
                    return True
                if clicks >= 3:
                    break
                if click_timer.reached():
                    self.device.click(btn)
                    self.device.click_record_clear()
                    clicks += 1
                    click_timer.reset()
        self.device.click_record_clear()
        return False

    def _confirm_max_invest(self, level_before):
        """Click MAX and confirm direct investment; return (upgraded, reached_max)."""
        if self.appear(assets.INVEST_CONFIRM, offset=OFFSET):
            if self.appear(assets.INVEST_MAX, offset=OFFSET):
                self.device.click(assets.INVEST_MAX)
            self.wait_until_still((890, 215, 1120, 265), timeout=1.0, threshold=2, skip_first_screenshot=False)
            self.device.click(assets.INVEST_CONFIRM)
        else:
            return False, False

        for _ in self.loop(skip_first=False, timeout=1.8):
            if self.handle_reward_popup():
                continue
            if self.ui_page_appear(page_resonance_trade_invest, offset=OFFSET):
                now_lv = self.read_invest_level()
                if is_invest_panel_maxed(self.device.image) or (now_lv is not None and now_lv >= MAX_INVEST_LEVEL):
                    self.wait_until_still((55, 140, 435, 560), timeout=1.2, threshold=2, skip_first_screenshot=False)
                    return True, True
                if level_before is not None and now_lv is not None and now_lv > level_before:
                    return True, False
        return False, False

    def _scroll_invest_grid(self):
        """Scroll left 3x3 commodity grid downward; return True if grid visibly moved."""
        if self.ui_page_appear(page_resonance_trade_invest, offset=OFFSET):
            grid_area = (55, 140, 435, 560)
            before = self.image_crop(grid_area)
            self.device.drag(
                (245, 520), (245, 220),
                segments=4, shake=(0, 0), point_random=(0, 0, 0, 0), shake_random=(0, 0, 0, 0),
                hold_duration=0.15, name='INVEST_GRID_SCROLL',
            )
            if self.wait_until_still(grid_area, timeout=4, threshold=2, skip_first_screenshot=False):
                return cv2.absdiff(before, self.image_crop(grid_area)).mean() >= 2
        return False

    def _invest_visible_page(self, lock_gray, max_upgrades):
        """Scan up to 9 visible grid slots on current page; return (upgrades, stop_early)."""
        upgrades = 0
        slots = ((r, c) for r in range(3) for c in range(3))
        for row, col in slots:
            slot_state = inspect_invest_slot(self.device.image, row, col, lock_gray)
            if slot_state in ('empty', 'locked'):
                return upgrades, True
            if not self._select_invest_slot(row, col):
                return upgrades, True
            if is_invest_panel_maxed(self.device.image):
                continue
            lv = self.read_invest_level()
            if lv is not None and lv >= MAX_INVEST_LEVEL:
                continue
            if self.appear(assets.INVEST_CONFIRM, offset=OFFSET):
                upgraded, reached_max = self._confirm_max_invest(lv)
                self.device.click_record_clear()
                if upgraded:
                    upgrades += 1
                if not reached_max or upgrades >= max_upgrades:
                    return upgrades, True
        return upgrades, False

    def invest_current_city(self):
        """Invest into all unlocked <20 commodities at current station via MAX -> confirm."""
        self.enter_exchange(page_resonance_trade_hub)
        self.ui_ensure(page_resonance_trade_invest, skip_first_screenshot=True)

        lock_gray = cv2.cvtColor(assets.TEMPLATE_INVEST_LOCK.image, cv2.COLOR_RGB2GRAY)
        upgrades = 0
        for page_idx in range(3):
            added, stop = self._invest_visible_page(lock_gray, 8 - upgrades)
            upgrades += added
            if stop or upgrades >= 8 or page_idx == 2 or not self._scroll_invest_grid():
                break

        logger.info('当前车站交易品投资完成，本次升级 %d 次', upgrades)
        self.ui_ensure(page_resonance_trade_hub, skip_first_screenshot=True)
        return upgrades
