"""Fatigue recovery (bento, rest area soda, items) and recovery-time scheduling."""

from datetime import datetime, timedelta
import json
import math
import os

import numpy as np

from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.ocr.ocr import Ocr
from module.resonance import assets
from module.resonance.map_nav import _make_point_button
from module.resonance.page import (
    page_resonance_bento, page_resonance_fatigue, page_resonance_rest_area, page_resonance_rest_drink,
)
from module.resonance.profile import ResonanceProfile
from module.resonance.route import _calc_fatigue
from module.resonance.trade import parse_fraction_text

OFFSET = (5, 5)
FATIGUE_RECOVERY_MIN_PER_POINT = 6
REST_AREA_MIN_FATIGUE = 300
REST_AREA_MAX_DRINKS = 6
REST_AREA_CITIES = ('七号自由港', '澄明数据中心', '修格里城', '岚心城', '海角城', '贡露城')
DAILY_STATE_PATH = os.path.join('config', 'state', 'resonance_daily_state.json')
BENTO_FATIGUE_AREA = (1185, 23, 1254, 44)
SKIP_NO_PROMPT_INNER = (547, 657, 570, 679)

FATIGUE_ITEM_TIERS = {
    'none': (),
    'lollipop': ('lollipop',),
    'lollipop_gum': ('lollipop', 'gum'),
    'all': ('lollipop', 'gum', 'cactus'),
}

# Only safe consumables are listed; 桦石 (-150) is never auto-spent.
FATIGUE_ITEMS = (
    ('lollipop', 60, (573, 155, 745, 325)),
    ('gum', 100, (814, 155, 986, 325)),
    ('cactus', 900, (573, 412, 745, 582)),
)

FATIGUE_ITEM_BTN = {
    'lollipop': assets.FATIGUE_LOLLIPOP,
    'gum': assets.FATIGUE_GUM,
    'cactus': assets.FATIGUE_CACTUS,
}

FATIGUE_CNT_OCR = Ocr([], lang='azur_lane', threshold=128, alphabet='0123456789', name='Fatigue item count')
BENTO_FATIGUE_OCR = Ocr([], lang='cnocr', threshold=128, alphabet='0123456789/', name='Bento fatigue')
REST_DRINK_FATIGUE_OCR = Ocr(
    (1085, 325, 1185, 358), lang='cnocr', threshold=128, alphabet='0123456789/',
    name='Rest drink fatigue',
)
FATIGUE_CONFIRM_QTY_OCR = Ocr(
    (575, 452, 705, 482), lang='cnocr', threshold=128, alphabet='0123456789/',
    name='Fatigue confirm qty',
)


def normalize_fatigue_item_mode(value):
    """Normalize config option (legacy bool or tier name) into one of FATIGUE_ITEM_TIERS keys."""
    if isinstance(value, bool):
        return 'all' if value else 'none'
    text = str(value or 'none').strip().lower()
    if text in ('true', 'yes', '1'):
        return 'all'
    if text in FATIGUE_ITEM_TIERS:
        return text
    return 'none'


def server_day_key(now=None):
    """Return YYYY-MM-DD key anchored at 05:00 server reset."""
    now = now or datetime.now()
    return (now - timedelta(hours=5)).strftime('%Y-%m-%d')


def is_rest_area_done_today(path=DAILY_STATE_PATH, now=None):
    """Return True if rest-area soda quota is already recorded done for today's 05:00 reset."""
    if not os.path.exists(path):
        return False
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return isinstance(data, dict) and data.get('rest_area_date') == server_day_key(now)
    except (OSError, ValueError):
        return False


def mark_rest_area_done(path=DAILY_STATE_PATH, now=None):
    """Record rest-area soda quota as completed for today's 05:00 reset."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    data = {}
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            pass
    data['rest_area_date'] = server_day_key(now)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def nearest_rest_area_city(current_city, roles, data):
    """Return (nearest_rest_city, travel_fatigue) among the 6 Rest Area cities."""
    if current_city in REST_AREA_CITIES:
        return current_city, 0
    return min(
        ((city, _calc_fatigue(current_city, city, roles, data)) for city in REST_AREA_CITIES),
        key=lambda x: x[1],
    )


def is_skip_no_prompt_checked(image):
    """Return True when '下次跳过时不再提示' checkbox on the skip modal shows a checkmark."""
    x1, y1, x2, y2 = SKIP_NO_PROMPT_INNER
    return int((image[y1:y2, x1:x2].min(axis=2) > 180).sum()) >= 35


def parse_fatigue_items(image):
    """Parse owned stock of lollipop, gum, and cactus from FATIGUE POINT modal."""
    results = []
    for key, recover, (x1, y1, x2, y2) in FATIGUE_ITEMS:
        pill = image[y1 + 70:y1 + 105, x1 + 30:x2 - 30]
        if int((pill.min(axis=2) > 220).sum()) >= 400:
            results.append({'key': key, 'recover': recover, 'owned': 0})
            continue
        crop = image[y2 - 40:y2 - 4, x2 - 55:x2 - 4]
        min_ch = crop.min(axis=2)
        up = np.repeat(np.repeat(min_ch, 2, axis=0), 2, axis=1)
        rgb = np.stack((up, up, up), axis=2)
        raw = FATIGUE_CNT_OCR.ocr([rgb], direct_ocr=True)
        text = raw[0] if isinstance(raw, list) and raw else ''
        digits = ''.join(ch for ch in str(text) if ch.isdigit())
        results.append({'key': key, 'recover': recover, 'owned': int(digits) if digits else 0})
    return results


def choose_fatigue_item_plan(cur_fatigue, needed_drop, items, allowed_keys=None):
    """Choose highest-priority allowed consumable and count to drop `needed_drop`."""
    if needed_drop <= 0:
        return None
    allowed = None if allowed_keys is None else set(allowed_keys)
    for item in items:
        if allowed is not None and item.get('key') not in allowed:
            continue
        owned = item.get('owned', 0)
        if owned <= 0:
            continue
        recover = item['recover']
        want = max(1, int(math.ceil(needed_drop / float(recover))))
        if cur_fatigue >= recover:
            max_useful = max(cur_fatigue // recover, want if needed_drop <= cur_fatigue else cur_fatigue // recover)
            count = min(owned, want, max(1, max_useful))
        else:
            count = 1
        return item['key'], count
    return None


def compute_fatigue_recovery_minutes(cur_fatigue, max_fatigue, needed_fatigue, buffer_minutes=2):
    """Compute wait minutes until natural fatigue recovery (6 min/pt) allows `needed_fatigue`."""
    remaining = max(0, max_fatigue - cur_fatigue)
    shortfall = needed_fatigue - remaining
    if shortfall <= 0:
        return 0
    return shortfall * FATIGUE_RECOVERY_MIN_PER_POINT + buffer_minutes


class ResonanceFatigue(ResonanceProfile):
    """Controller for recovering fatigue via bento, rest area soda, and safe items."""

    def read_bento_fatigue(self):
        """Read (cur, max) fatigue from the bento cabinet top-right bar."""
        x1, y1, x2, y2 = BENTO_FATIGUE_AREA
        crop = self.device.image[y1:y2, x1:x2]
        gray = crop.max(axis=2)
        up = np.repeat(np.repeat(gray, 2, axis=0), 2, axis=1)
        rgb = np.stack((up, up, up), axis=2)
        raw = BENTO_FATIGUE_OCR.ocr([rgb], direct_ocr=True)
        text = raw[0] if isinstance(raw, list) and raw else str(raw or '')
        return parse_fraction_text(text)

    def read_rest_drink_fatigue(self):
        """Read (cur, max) fatigue from the rest-area drink selection bar."""
        return parse_fraction_text(REST_DRINK_FATIGUE_OCR.ocr(self.device.image))

    def use_bento_cabinet(self):
        """Navigate to bento cabinet, use all available bentos, and return latest fatigue."""
        self.ui_ensure(page_resonance_bento, skip_first_screenshot=False)
        before = self.read_bento_fatigue()
        latest = before
        clicks = 0
        ready = Timer(1.5).start()
        self.interval_clear((assets.BENTO_USE_ALL, assets.GARBAGE_CONFIRM_OK))
        for _ in self.loop(skip_first=False, timeout=15):
            if self.handle_reward_popup():
                continue
            if self.appear(assets.BENTO_CONFIRM_MODAL, offset=(60, 10)):
                self.appear_then_click(assets.GARBAGE_CONFIRM_OK, offset=OFFSET, interval=1.5)
                continue
            if self.ui_page_appear(page_resonance_bento, offset=OFFSET):
                now = self.read_bento_fatigue()
                if now is not None:
                    latest = now
                if before is not None and now is not None and now[0] < before[0]:
                    return now
                if self.appear(assets.BENTO_USE_ALL, offset=OFFSET):
                    if clicks >= 2:
                        return latest
                    if self.appear_then_click(assets.BENTO_USE_ALL, offset=OFFSET, interval=2):
                        clicks += 1
                elif clicks > 0 or ready.reached():
                    return latest
        return latest

    def _handle_rest_skip_modal(self, skip_timer, skip_clicks):
        """Tick '下次跳过时不再提示' and click confirm on rest-area skip dialog."""
        if self.appear(assets.REST_AREA_SKIP_MODAL, offset=OFFSET):
            if not is_skip_no_prompt_checked(self.device.image) and skip_clicks < 2:
                if skip_timer.reached():
                    self.device.click(_make_point_button(558, 668, 'REST_AREA_SKIP_NO_PROMPT', radius=6))
                    skip_clicks += 1
                    skip_timer.reset()
                return True, skip_clicks
            self.appear_then_click(assets.REST_AREA_SKIP_CONFIRM, offset=OFFSET, interval=2)
            return True, skip_clicks
        return False, skip_clicks

    def _drink_one_soda(self, before):
        """Buy one rest-area drink and skip its cutscene; return (succeeded, latest_fatigue)."""
        self.interval_clear((
            assets.REST_AREA_DRINK_BUY, assets.REST_AREA_DRINK_AGAIN,
            assets.REST_AREA_SKIP, assets.REST_AREA_SKIP_CONFIRM,
        ))
        skip_timer = Timer(1.2)
        skip_clicks = 0
        buy_clicks = 0
        saw_action = False
        latest = before
        for _ in self.loop(skip_first=False, timeout=15):
            if self.appear_then_click(assets.REST_AREA_DRINK_AGAIN, offset=OFFSET, interval=2):
                saw_action = True
                continue
            handled, skip_clicks = self._handle_rest_skip_modal(skip_timer, skip_clicks)
            if handled:
                saw_action = True
                continue
            if self.appear_then_click(assets.REST_AREA_SKIP, offset=OFFSET, interval=1.5):
                saw_action = True
                continue
            if self.handle_reward_popup():
                saw_action = True
                continue
            if self.ui_page_appear(page_resonance_rest_drink, offset=OFFSET):
                now = self.read_rest_drink_fatigue()
                if now is not None:
                    latest = now
                if before is not None and now is not None and now[0] <= before[0] - 20:
                    return True, now
                if buy_clicks >= 2 and not saw_action:
                    return False, latest
                if self.appear_then_click(assets.REST_AREA_DRINK_BUY, offset=OFFSET, interval=2):
                    buy_clicks += 1
        return False, latest

    def _open_rest_drink(self):
        """Navigate to rest area, wait for entrance animation, and open the drink menu."""
        if self.device.image is not None and self.ui_page_appear(page_resonance_rest_drink, offset=OFFSET):
            return
        self.ui_ensure(page_resonance_rest_area, skip_first_screenshot=False)
        self.wait_until_still((730, 285, 1195, 530), timeout=4, threshold=1.5, skip_first_screenshot=False)
        self.interval_clear(assets.REST_AREA_DRINK_ENTRY)
        for _ in self.loop(skip_first=False, timeout=12):
            if self.ui_page_appear(page_resonance_rest_drink, offset=OFFSET):
                self.ui_current = page_resonance_rest_drink
                return
            if self.appear_then_click(assets.REST_AREA_DRINK_ENTRY, offset=OFFSET, interval=1.5):
                continue
        raise GameStuckError('Resonance rest area drink page did not open')

    def drink_rest_area_soda(self, max_drinks=REST_AREA_MAX_DRINKS):
        """Enter current city's rest area and drink up to `max_drinks` sodas; return (count, exhausted, fatigue)."""
        self._open_rest_drink()
        latest = self.read_rest_drink_fatigue()
        drinks = 0
        exhausted = False
        for _ in range(max_drinks):
            if latest is not None and latest[0] < 50:
                break
            ok, now = self._drink_one_soda(latest)
            if now is not None:
                latest = now
            if not ok:
                exhausted = True
                break
            drinks += 1
        logger.info('休息区喝汽水完成: 本次 %d 杯, 疲劳 %s', drinks, latest)
        self.ui_goto_main()
        return drinks, exhausted, latest

    def _adjust_and_confirm_fatigue_item(self, count):
        """Set quantity in the open '请选择补充次数' dialog and confirm."""
        self.interval_clear((
            assets.FATIGUE_CONFIRM_MAX, assets.FATIGUE_CONFIRM_PLUS,
            assets.FATIGUE_CONFIRM_MINUS, assets.FATIGUE_CONFIRM_OK,
        ))
        for _ in self.loop(timeout=15):
            if self.appear(assets.FATIGUE_CONFIRM_MODAL, offset=OFFSET) and self.appear(assets.FATIGUE_CONFIRM_OK, offset=OFFSET):
                frac = parse_fraction_text(FATIGUE_CONFIRM_QTY_OCR.ocr(self.device.image))
                if frac is None:
                    continue
                cur, max_qty = frac
                cap = min(count, max_qty)
                if cap <= 0:
                    return 0
                if cur == cap:
                    self.device.click(assets.FATIGUE_CONFIRM_OK)
                    if self.wait_until_disappear(assets.FATIGUE_CONFIRM_MODAL, offset=OFFSET, timeout=8):
                        self.wait_until_appear(assets.FATIGUE_MODAL_CHECK, offset=OFFSET, timeout=8)
                        return cap
                    raise GameStuckError('Resonance fatigue confirm modal did not close')
                if cur < cap and cap == max_qty:
                    self.appear_then_click(assets.FATIGUE_CONFIRM_MAX, offset=OFFSET, interval=1.5)
                elif cur < cap:
                    self.appear_then_click(assets.FATIGUE_CONFIRM_PLUS, offset=OFFSET, interval=0.8)
                else:
                    self.appear_then_click(assets.FATIGUE_CONFIRM_MINUS, offset=OFFSET, interval=0.8)
        raise GameStuckError('Resonance fatigue quantity adjustment timed out')

    def _use_fatigue_item(self, item_btn, count):
        """Click `item_btn` on page_resonance_fatigue and confirm usage."""
        self.interval_clear(item_btn)
        for _ in self.loop(timeout=12):
            if self.appear(assets.FATIGUE_CONFIRM_MODAL, offset=OFFSET):
                return self._adjust_and_confirm_fatigue_item(count)
            if self.ui_page_appear(page_resonance_fatigue, offset=OFFSET):
                self.appear_then_click(item_btn, offset=OFFSET, interval=2)
                continue
        raise GameStuckError('Resonance fatigue item confirm modal did not open')

    def recover_fatigue(self, cur_fatigue, max_fatigue, needed_fatigue, item_mode='all', use_bento=True):
        """Recover fatigue via bento first (if enabled), then allowed consumable items."""
        shortfall = needed_fatigue - max(0, max_fatigue - cur_fatigue)
        if shortfall <= 0:
            return True

        if use_bento:
            self.ui_ensure(page_resonance_fatigue, skip_first_screenshot=False)
            bento_f = self.use_bento_cabinet()
            if bento_f is not None:
                cur_fatigue, max_fatigue = bento_f
                shortfall = needed_fatigue - max(0, max_fatigue - cur_fatigue)
                if shortfall <= 0:
                    return True

        mode = normalize_fatigue_item_mode(item_mode)
        allowed_keys = FATIGUE_ITEM_TIERS[mode]
        if not allowed_keys:
            return False

        self.ui_ensure(page_resonance_fatigue, skip_first_screenshot=False)
        for _ in range(6):
            if self.ui_page_appear(page_resonance_fatigue, offset=OFFSET):
                items = parse_fatigue_items(self.device.image)
                plan = choose_fatigue_item_plan(cur_fatigue, shortfall, items, allowed_keys=allowed_keys)
                if plan is None:
                    logger.warning('雷索纳斯疲劳值不足且没有可用的允许恢复道具 (%s)，等待自然恢复', mode)
                    return False
                key, count = plan
                recover_val = next(r for k, r, _ in FATIGUE_ITEMS if k == key)
                used = self._use_fatigue_item(FATIGUE_ITEM_BTN[key], count)
                if used <= 0:
                    return False
                cur_fatigue = max(0, cur_fatigue - used * recover_val)
                shortfall = needed_fatigue - max(0, max_fatigue - cur_fatigue)
                if shortfall <= 0:
                    return True
            else:
                raise GameStuckError('Resonance fatigue modal closed unexpectedly')
        return shortfall <= 0
