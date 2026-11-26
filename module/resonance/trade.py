"""Exchange buying and selling for 雷索纳斯 (Resonance Solstice)."""

from difflib import SequenceMatcher
import re

import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.ocr.ocr import Ocr
from module.resonance import assets
from module.resonance.map_nav import ResonanceMapNav
from module.resonance.page import page_resonance_city, page_resonance_trade_buy, page_resonance_trade_hub, page_resonance_trade_sell
from module.resonance.shop import normalize_name

OFFSET = (5, 5)
GOODS_LIST = (480, 135, 860, 695)
LEFT_BAR_X = (482, 498)
LEFT_BAR_Y = (135, 695)
BARGAIN_PIP_Y = (485, 487)
BARGAIN_PIP_XS = (
    (1109, 1124), (1126, 1141), (1143, 1158), (1160, 1175),
    (1177, 1192), (1194, 1209), (1211, 1226), (1227, 1242),
)
MODE_MAX_DOT = (827, 93, 851, 117)
CARGO_AREA = (1085, 386, 1252, 414)
SELL_TOTAL_AREA = (1140, 570, 1255, 600)
SELL_SUMMARY_AREA = (1100, 534, 1255, 600)

FATIGUE_OCR = Ocr((940, 16, 1040, 48), lang='cnocr', threshold=128, alphabet='0123456789/', name='Trade fatigue')
CARGO_OCR = Ocr([], lang='cnocr', threshold=128, alphabet='0123456789/+-', name='Trade cargo')
SELL_TOTAL_OCR = Ocr([], lang='cnocr', threshold=128, alphabet='0123456789', name='Trade sell total')
BARGAIN_PCT_OCR = Ocr((980, 445, 1058, 480), lang='cnocr', threshold=128, alphabet='0123456789.%', name='Trade bargain pct')
RESTOCK_QTY_OCR = Ocr((575, 355, 705, 390), lang='cnocr', threshold=128, alphabet='0123456789/', name='Restock quantity')
RESTOCK_OWN_OCR = Ocr((585, 305, 695, 335), lang='cnocr', threshold=128, alphabet='0123456789', name='Restock owned')
GOODS_NAME_OCR = Ocr([], lang='cnocr', threshold=128, name='Trade goods')


def parse_cargo_text(text):
    """Parse cargo indicator like '108+226/994' or '3-3/994' into (loaded, delta, capacity)."""
    match = re.fullmatch(r'(\d+)([+-]\d+)?/(\d+)', normalize_name(text or ''))
    if not match:
        return None
    loaded = int(match.group(1))
    delta = int(match.group(2)) if match.group(2) else 0
    return loaded, delta, int(match.group(3))


def parse_fraction_text(text):
    """Parse 'cur/total' OCR output into (cur, total)."""
    match = re.fullmatch(r'(\d+)/(\d+)', normalize_name(text or ''))
    return (int(match.group(1)), int(match.group(2))) if match else None


def parse_pct_text(text):
    """Parse percentage string like '13.0%' into float."""
    match = re.fullmatch(r'(\d+(?:\.\d+)?)%', normalize_name(text or ''))
    return float(match.group(1)) if match else None


def split_buy_targets(plan_or_items):
    """Split a route leg dict or name sequence into (full_names_set, partial_tail_name)."""
    if isinstance(plan_or_items, dict):
        full_names = set()
        tail_name = None
        for item in plan_or_items.get('combinations', ()):
            name = normalize_name(item.get('name', ''))
            if not name:
                continue
            buy_lot = item.get('buy_lot', 0)
            avail_lot = item.get('available_lot', buy_lot)
            if buy_lot < avail_lot:
                tail_name = name
            else:
                full_names.add(name)
        return full_names, tail_name

    full_names = {normalize_name(name) for name in (plan_or_items or ()) if normalize_name(name)}
    return full_names, None


def match_buy_target(ocr_name, target_names):
    """Match an OCR commodity name to `target_names` (exact first, then fuzzy >= 0.75)."""
    if ocr_name in target_names:
        return ocr_name
    if len(ocr_name) < 3:
        return None
    score, tgt = max(
        ((SequenceMatcher(None, ocr_name, t).ratio(), t) for t in target_names),
        default=(0.0, None),
    )
    return tgt if score >= 0.75 else None


def find_cyan_card_runs(image):
    """Find (y0, y1) spans of stocked buy cards by their cyan left accent bar."""
    strip = image[LEFT_BAR_Y[0]:LEFT_BAR_Y[1], LEFT_BAR_X[0]:LEFT_BAR_X[1]].astype(np.int16)
    r, g, b = strip[:, :, 0], strip[:, :, 1], strip[:, :, 2]
    cyan = (b - r > 50) & (g - r > 30) & (b > 140)
    ys = np.where(cyan.mean(axis=1) > 0.3)[0]
    if len(ys) == 0:
        return []
    runs = []
    start = prev = int(ys[0])
    for y in ys[1:]:
        yi = int(y)
        if yi > prev + 3:
            if prev + 1 - start >= 65:
                runs.append((LEFT_BAR_Y[0] + start, LEFT_BAR_Y[0] + prev + 1))
            start = yi
        prev = yi
    if prev + 1 - start >= 65:
        runs.append((LEFT_BAR_Y[0] + start, LEFT_BAR_Y[0] + prev + 1))
    return runs


def count_bargain_pips_in_image(image):
    """Count remaining lit negotiation pips (0..8) underneath the orange button."""
    y1, y2 = BARGAIN_PIP_Y
    return sum(1 for x1, x2 in BARGAIN_PIP_XS if image[y1:y2, x1:x2].mean() > 130)


def _make_card_button(name, y0, y1):
    """Build a clickable Button for a stocked buy-list card."""
    return Button(area=(500, y0, 852, y1), color=(0, 0, 0), button=(660, y0 + 25, 830, y1 - 25),
                  name='TRADE_CARD_%s_%d' % (name, y0))


class ResonanceTrade(ResonanceMapNav):
    """Exchange trade controller for buying, selling, restocking, and negotiating."""

    def read_fatigue(self):
        """Read (current, capacity) fatigue from the top bar."""
        return parse_fraction_text(FATIGUE_OCR.ocr(self.device.image))

    def read_cargo(self):
        """Read (loaded, delta, capacity) from the cargo indicator using smooth max-channel."""
        crop = self.device.image[CARGO_AREA[1]:CARGO_AREA[3], CARGO_AREA[0]:CARGO_AREA[2]]
        gray = crop.max(axis=2)
        rgb = np.stack((gray, gray, gray), axis=2)
        raw = CARGO_OCR.ocr([rgb], direct_ocr=True)
        if isinstance(raw, list):
            raw = raw[0] if raw else ''
        return parse_cargo_text(raw)

    def cargo_remaining(self):
        """Return remaining cargo slots, or None if cargo OCR failed."""
        cargo = self.read_cargo()
        if cargo is None:
            return None
        loaded, delta, capacity = cargo
        return max(0, capacity - (loaded + max(0, delta)))

    def read_sell_total(self):
        """Read post-tax sell total amount from the right panel, or None."""
        crop = self.device.image[SELL_TOTAL_AREA[1]:SELL_TOTAL_AREA[3], SELL_TOTAL_AREA[0]:SELL_TOTAL_AREA[2]]
        gray = crop.max(axis=2)
        rgb = np.stack((gray, gray, gray), axis=2)
        raw = SELL_TOTAL_OCR.ocr([rgb], direct_ocr=True)
        text = raw[0] if isinstance(raw, list) and raw else str(raw or '')
        digits = ''.join(ch for ch in str(text) if ch.isdigit())
        return int(digits) if digits else None

    def read_bargain_pct(self):
        """Read current bargain or raise percentage."""
        return parse_pct_text(BARGAIN_PCT_OCR.ocr(self.device.image))

    def count_bargain_pips(self):
        """Count remaining negotiation pips on the current frame."""
        return count_bargain_pips_in_image(self.device.image)

    def has_sell_cargo(self):
        """Check whether the sell list contains at least one stocked item."""
        strip = self.device.image[LEFT_BAR_Y[0]:LEFT_BAR_Y[1], LEFT_BAR_X[0]:LEFT_BAR_X[1]].astype(np.int16)
        r, g, b = strip[:, :, 0], strip[:, :, 1], strip[:, :, 2]
        yellow = (r > 180) & (g > 140) & (b < 80)
        return int(yellow.sum()) > 200

    def visible_buy_cards(self):
        """Return [(normalized_name, click_button, y0, y1), ...] for stocked cards."""
        runs = find_cyan_card_runs(self.device.image)
        if not runs:
            return []
        crops = [self.device.image[y0 + 6:y0 + 40, 624:848] for y0, _ in runs]
        names = GOODS_NAME_OCR.ocr(crops, direct_ocr=True)
        if isinstance(names, str):
            names = [names]
        return [
            (name, _make_card_button(name, y0, y1), y0, y1)
            for (y0, y1), raw_name in zip(runs, names)
            for name in (normalize_name(raw_name),) if name
        ]

    def open_city_exchange(self, city_name=None):
        """Open the exchange hub from the city map screen."""
        retry = Timer(2)
        for _ in self.loop(skip_first=False, timeout=15):
            if self.ui_page_appear(page_resonance_trade_hub, offset=OFFSET):
                self.ui_current = page_resonance_trade_hub
                return
            if self.ui_page_appear(page_resonance_city, offset=OFFSET):
                score, btn = assets.TEMPLATE_CITY_EXCHANGE.match_result(self.device.image)
                if score > 0.80 and retry.reached():
                    self.device.click(btn)
                    retry.reset()
        raise GameStuckError('Resonance city exchange icon did not open the exchange hub')

    def enter_exchange(self, target_page=page_resonance_trade_sell, city_name=None):
        """Navigate from any recognized screen to the buy or sell exchange page."""
        current = self.ui_get_current_page(skip_first_screenshot=False)
        if current in (page_resonance_trade_hub, page_resonance_trade_buy, page_resonance_trade_sell):
            self.ui_ensure(target_page, skip_first_screenshot=True)
            return
        if current is page_resonance_city:
            self.open_city_exchange(city_name=city_name)
        else:
            self.open_current_city_exchange()
        self.ui_ensure(target_page, skip_first_screenshot=True)

    def ensure_max_mode(self, page):
        """Ensure the '最大' quantity radio button is selected on the trade page."""
        self.interval_clear(assets.TRADE_MODE_MAX)
        for _ in self.loop(timeout=10):
            if self.ui_page_appear(page, offset=OFFSET):
                dot = self.device.image[MODE_MAX_DOT[1]:MODE_MAX_DOT[3], MODE_MAX_DOT[0]:MODE_MAX_DOT[2]]
                if int((dot.mean(axis=2) > 180).sum()) > 80:
                    return
                self.appear_then_click(assets.TRADE_MODE_MAX, offset=OFFSET, interval=2)
                continue
            if self.handle_trade_report() or self.handle_trade_modal():
                continue
        raise GameStuckError('Resonance trade max mode could not be enabled')

    def _open_restock_modal(self):
        """Open the restock confirmation dialog via 使用道具 -> 进货采买书."""
        self.interval_clear((assets.TRADE_USE_ITEM, assets.TRADE_ITEM_RESTOCK_USE))
        for _ in self.loop(timeout=12):
            if self.appear(assets.TRADE_RESTOCK_MODAL, offset=OFFSET) and self.appear(assets.TRADE_RESTOCK_CONFIRM, offset=OFFSET):
                return
            if self.appear(assets.TRADE_ITEMS_MODAL, offset=OFFSET):
                self.appear_then_click(assets.TRADE_ITEM_RESTOCK_USE, offset=OFFSET, interval=2)
                continue
            self.appear_then_click(assets.TRADE_USE_ITEM, offset=OFFSET, interval=2)
        raise GameStuckError('Resonance restock modal did not open')

    def _dismiss_restock_overlays(self):
        """Close any remaining restock or use-item modal back to page_resonance_trade_buy."""
        self.interval_clear((assets.TRADE_RESTOCK_CANCEL, assets.TRADE_ITEMS_MODAL))
        for _ in self.loop(timeout=10):
            if self.ui_page_appear(page_resonance_trade_buy, offset=OFFSET):
                return
            if self.handle_trade_modal():
                continue
        raise GameStuckError('Resonance trade buy page did not resume after restock')

    def _adjust_restock_quantity(self, want):
        """Adjust quantity in the open restock modal and confirm, returning books used."""
        self.interval_clear((assets.TRADE_RESTOCK_MAX, assets.TRADE_RESTOCK_PLUS, assets.TRADE_RESTOCK_MINUS, assets.TRADE_RESTOCK_CONFIRM))
        for _ in self.loop(timeout=15):
            if self.appear(assets.TRADE_RESTOCK_MODAL, offset=OFFSET) and self.appear(assets.TRADE_RESTOCK_CONFIRM, offset=OFFSET):
                own_text = normalize_name(RESTOCK_OWN_OCR.ocr(self.device.image))
                owned = int(own_text) if own_text.isdigit() else None
                if owned == 0:
                    self._last_restock_owned = 0
                    logger.warning('Resonance trade has 0 restock books left')
                    self._dismiss_restock_overlays()
                    return 0
                frac = parse_fraction_text(RESTOCK_QTY_OCR.ocr(self.device.image))
                if frac is None:
                    continue
                cur, max_qty = frac
                cap = min(want, max_qty, owned) if owned is not None else min(want, max_qty)
                if cap <= 0:
                    if owned is not None:
                        self._last_restock_owned = owned
                    self._dismiss_restock_overlays()
                    return 0
                if cur == cap:
                    self.device.click(assets.TRADE_RESTOCK_CONFIRM)
                    if self.wait_until_disappear(assets.TRADE_RESTOCK_MODAL, offset=OFFSET, timeout=8):
                        if owned is not None:
                            self._last_restock_owned = max(0, owned - cap)
                        self._dismiss_restock_overlays()
                        return cap
                    raise GameStuckError('Resonance restock modal did not close after confirm')
                if cur < cap and cap == max_qty:
                    self.appear_then_click(assets.TRADE_RESTOCK_MAX, offset=OFFSET, interval=1.5)
                elif cur < cap:
                    self.appear_then_click(assets.TRADE_RESTOCK_PLUS, offset=OFFSET, interval=0.8)
                else:
                    self.appear_then_click(assets.TRADE_RESTOCK_MINUS, offset=OFFSET, interval=0.8)
        raise GameStuckError('Resonance restock quantity adjustment timed out')

    def use_restock_books(self, count):
        """Use up to `count` restock books in batches of at most 10."""
        remaining = max(0, int(count))
        used_total = 0
        for _ in range(10):
            if remaining <= 0:
                return used_total
            self._open_restock_modal()
            used = self._adjust_restock_quantity(min(remaining, 10))
            if used <= 0:
                return used_total
            used_total += used
            remaining -= used
        return used_total

    def _wait_negotiate_settle(self, page_check, pips_before, pct_before):
        """Wait for bargain/raise animation to finish and UI state to update."""
        for _ in self.loop(timeout=10):
            if self.appear(page_check, offset=OFFSET):
                pips_now = self.count_bargain_pips()
                pct_now = self.read_bargain_pct()
                if pips_now < pips_before or (pct_now is not None and pct_before is not None and pct_now > pct_before):
                    return
        logger.warning('Resonance negotiation state did not visibly change before timeout')

    def negotiate(self, is_buy, target_pct, max_fatigue_ratio=0.95):
        """Click bargain or raise until target_pct, pips exhausted, or fatigue cap reached."""
        self._last_negotiate_fatigue = None
        if target_pct <= 0:
            return
        page_check = assets.TRADE_BUY_CHECK if is_buy else assets.TRADE_SELL_CHECK
        btn = assets.TRADE_BARGAIN if is_buy else assets.TRADE_RAISE
        start_f, clicked = None, False
        for _ in range(10):
            if not self.wait_until_appear(page_check, offset=OFFSET, timeout=8):
                raise GameStuckError('Resonance trade page lost during negotiation')
            pct = self.read_bargain_pct()
            if (pct is not None and pct >= target_pct) or self.count_bargain_pips() <= 0:
                break
            pips = self.count_bargain_pips()
            fatigue = self.read_fatigue()
            if start_f is None and fatigue is not None:
                start_f = fatigue[0]
            if fatigue is not None and fatigue[0] + 8 > int(fatigue[1] * max_fatigue_ratio):
                logger.info('Resonance negotiation stopped by fatigue cap: %s/%s' % fatigue)
                break
            if self.appear(btn, offset=OFFSET):
                self.device.click(btn)
                clicked = True
                self._wait_negotiate_settle(page_check, pips, pct)
            else:
                break
        if clicked and start_f is not None:
            end_f = self.read_fatigue()
            if end_f is not None and end_f[0] > start_f:
                self._last_negotiate_fatigue = end_f[0] - start_f

    def _confirm_and_dismiss_report(self, page_check, confirm_btn, report_btn):
        """Click buy/sell confirm, wait for settlement report, and dismiss it."""
        self.interval_clear((confirm_btn, report_btn))
        for _ in self.loop(timeout=15):
            if self.appear(report_btn, offset=OFFSET):
                break
            if self.appear(page_check, offset=OFFSET) and self.appear_then_click(confirm_btn, offset=OFFSET, interval=2):
                continue
        else:
            raise GameStuckError('Resonance trade settlement report did not appear')

        for _ in self.loop(timeout=12):
            if self.appear(report_btn, offset=OFFSET):
                self.appear_then_click(report_btn, offset=OFFSET, interval=2)
                continue
            if self.appear(page_check, offset=OFFSET):
                return
            if self.appear(assets.TRADE_HUB_CHECK, offset=OFFSET):
                self.ui_current = page_resonance_trade_hub
                return
            if self.handle_reward_popup():
                continue
        raise GameStuckError('Resonance trade settlement report did not close')

    def _should_raise_sell(self, min_raise_total=300000, min_raise_ratio=0.2):
        """Skip price raising when staged cargo value or lot count is too small to justify fatigue."""
        total = self.read_sell_total()
        if total is not None:
            if total < min_raise_total:
                logger.info('卖出总价 %d 低于阈值 %d，跳过抬价以节省疲劳', total, min_raise_total)
                return False
            return True
        cargo = self.read_cargo()
        if cargo is not None and abs(cargo[1]) < max(50, int(cargo[2] * min_raise_ratio)):
            logger.info('卖出货量过小 (%d/%d)，跳过抬价以节省疲劳', abs(cargo[1]), cargo[2])
            return False
        return True

    def sell_all(self, raise_target=0, max_fatigue_ratio=0.95, min_raise_total=300000):
        """Enter exchange sell tab, stage all cargo, optionally raise price, and sell."""
        self._last_sell_image = None
        self.enter_exchange(page_resonance_trade_sell)
        self.ensure_max_mode(page_resonance_trade_sell)
        self.interval_clear(assets.TRADE_SELL_ALL)
        stage_clicks = 0
        for _ in self.loop(timeout=12):
            if self.appear(assets.TRADE_CANCEL_ALL, offset=OFFSET):
                break
            if self.appear(assets.TRADE_SELL_CHECK, offset=OFFSET):
                if stage_clicks == 0 and not self.has_sell_cargo():
                    logger.info('Resonance sell cargo is empty, skipping sell')
                    return False
                if stage_clicks >= 2 and self.appear(assets.TRADE_SELL_ALL, offset=OFFSET):
                    logger.info('货舱中仅剩本地不可卖货物，跳过卖出')
                    return False
                if self.appear_then_click(assets.TRADE_SELL_ALL, offset=OFFSET, interval=2):
                    stage_clicks += 1
        else:
            raise GameStuckError('Resonance sell_all did not stage cargo')

        self.wait_until_still(SELL_SUMMARY_AREA, timeout=2.5, threshold=0.25, skip_first_screenshot=False)
        if raise_target > 0 and self._should_raise_sell(min_raise_total=min_raise_total):
            self.negotiate(is_buy=False, target_pct=raise_target, max_fatigue_ratio=max_fatigue_ratio)
            self.wait_until_still(SELL_SUMMARY_AREA, timeout=2.0, threshold=0.25, skip_first_screenshot=False)
        self._last_sell_image = self.device.image
        self._confirm_and_dismiss_report(assets.TRADE_SELL_CHECK, assets.TRADE_SELL_CONFIRM, assets.TRADE_SELL_REPORT)
        return True

    def scroll_buy_list(self, direction):
        """Scroll the buy commodity list up (1) or down (-1); return True if content moved."""
        if self.appear(assets.TRADE_BUY_CHECK, offset=OFFSET):
            before = self.image_crop(GOODS_LIST)
            self.device.drag((680, 420), (680, 420 + direction * 260), segments=4, shake=(0, 0), point_random=(0, 0, 0, 0),
                             shake_random=(0, 0, 0, 0), hold_duration=0.15, name='TRADE_BUY_SCROLL')
            if self.wait_until_still(GOODS_LIST, timeout=8, threshold=2, skip_first_screenshot=False):
                return cv2.absdiff(before, self.image_crop(GOODS_LIST)).mean() >= 2
        raise GameStuckError('Resonance buy list did not settle after scrolling')

    def _wait_card_staged(self, name, cargo_before):
        """Wait until clicking a buy card updates cargo or clears the card."""
        for _ in self.loop(timeout=4):
            if self.appear(assets.TRADE_BUY_CHECK, offset=OFFSET):
                if self.read_cargo() != cargo_before:
                    return True
                if not any(match_buy_target(card_name, (name,)) for card_name, _, _, _ in self.visible_buy_cards()):
                    return True
        return False

    def _stage_visible_targets(self, target_names):
        """Click visible stocked cards matching target_names until none remain in view."""
        for _ in range(16):
            if not target_names or self.cargo_remaining() == 0:
                return
            if self.ui_page_appear(page_resonance_trade_buy, offset=OFFSET):
                match = next(((tgt, btn) for card_name, btn, _, _ in self.visible_buy_cards()
                              for tgt in (match_buy_target(card_name, target_names),) if tgt is not None), None)
                if match is None:
                    return
                name, btn = match
                cargo_before = self.read_cargo()
                self.device.click(btn)
                if not self._wait_card_staged(name, cargo_before):
                    logger.warning('Resonance buy card %s did not visibly stage' % name)
                target_names.discard(name)
            else:
                return

    def _select_buy_targets(self, target_names):
        """Scroll buy list top-to-bottom and stage all matching target_names."""
        if not target_names:
            return
        for _ in range(16):
            if not self.scroll_buy_list(1):
                break
        for _ in range(16):
            self._stage_visible_targets(target_names)
            if not target_names or self.cargo_remaining() == 0:
                return
            if not self.scroll_buy_list(-1):
                return

    def buy_plan(self, plan_or_items, restock_books=None, bargain_target=0, max_fatigue_ratio=0.95):
        """Enter exchange buy tab, restock if needed, stage plan items, bargain, and buy."""
        full_names, tail_name = split_buy_targets(plan_or_items)
        if restock_books is None and isinstance(plan_or_items, dict):
            restock_books = plan_or_items.get('restock', 0)
        restock_books = restock_books or 0

        self.enter_exchange(page_resonance_trade_buy)
        self.ensure_max_mode(page_resonance_trade_buy)
        if restock_books > 0:
            self.use_restock_books(restock_books)
        self._select_buy_targets(set(full_names))
        if tail_name and self.cargo_remaining() != 0:
            self._select_buy_targets({tail_name})
        if self.appear(assets.TRADE_CANCEL_ALL, offset=OFFSET):
            if bargain_target > 0:
                self.negotiate(is_buy=True, target_pct=bargain_target, max_fatigue_ratio=max_fatigue_ratio)
            self._confirm_and_dismiss_report(assets.TRADE_BUY_CHECK, assets.TRADE_BUY_CONFIRM, assets.TRADE_BUY_REPORT)
            return True
        logger.warning('Resonance buy staged no items for plan')
        return False
