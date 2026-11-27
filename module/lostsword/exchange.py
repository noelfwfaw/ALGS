"""Exchange shop (交易所) sweeper for Lost Sword (失落之剑).

Layout measured on 1280x720 screenshots:
- Top tab bar: 「交易所」 pill sits at (615, 83, 710, 119); cream when active.
- Left sidebar (92 px vertical pitch, 84 px cream pill when selected, above 「批量购买」):
  Top-scrolled: 消耗品 (cy=184), 突袭 (cy=276), 世界领主 (cy=368), 公会 (cy=460),
  竞技场 (cy=552).
  Bottom-scrolled: 灵魂 plus one or more timed Event currency tabs (e.g. 驯鹿币,
  南瓜币) with an expiry date line `~ YY.MM.DD` below the label.
- Two-row card shelf (columns 275 px wide, 296 px pitch):
  Row 0 name (156..188), price strip (378..412), tap y = 285
  Row 1 name (444..476), price strip (666..700), tap y = 573
- Purchase dialog: 「购买商品」, quantity `>>` at `SHOP_EXCHANGE_MAX`, confirm at
  `SHOP_EXCHANGE_BUY`, cost badge in `(790, 524, 1030, 560)`, and resource-short
  alert `SHOP_LACK_CONFIRM`.
"""

import numpy as np

from module.base.timer import Timer
from module.base.utils import crop, get_color
from module.logger import logger
from module.lostsword.assets import (REWARD_POPUP_TITLE, SHOP_DIALOG_TITLE,
                                     SHOP_EXCHANGE_BUY, SHOP_EXCHANGE_MAX,
                                     SHOP_LACK_CONFIRM, SHOP_TAB_EXCHANGE,
                                     SHOP_TITLE)
from module.lostsword.exchange_filter import (EXCHANGE_BLUE_DIALOG_MIN,
                                              exchange_area_button,
                                              exchange_has_blue_diamond,
                                              exchange_keyword_hit,
                                              exchange_match_rank,
                                              exchange_norm,
                                              exchange_parse_filter)
from module.lostsword.page import page_shop
from module.ocr.ocr import Ocr

# Default left-sidebar sub-tab positions when scrolled to top (`世界领主` sits at cy=368).
EXCHANGE_SUBTABS = {
    'consumable': ('消耗品', (80, 160, 240, 205), 'ConsumableFilter'),
    'raid': ('突袭', (80, 252, 240, 297), 'RaidFilter'),
    'guild': ('公会', (80, 436, 240, 481), 'GuildFilter'),
    'arena': ('竞技场', (80, 528, 240, 573), 'ArenaFilter'),
}
EXCHANGE_SIDEBAR_AREA = (60, 140, 260, 640)
EXCHANGE_TOP_CENTERS = (184, 276, 368, 460, 552)
EXCHANGE_BOTTOM_CENTERS = (225, 317, 409, 501, 593)
# Timed event currency tabs show `~ YY.MM.DD` below the label (std 22~29 vs <=3.2 on permanent tabs).
EXCHANGE_EVENT_DATE_STD = 10.0
EXCHANGE_PERMANENT_KEYWORDS = ('消耗', '突袭', '领主', '公会', '竞技', '灵魂')
EXCHANGE_TAB_SELECTED_MEAN = 150
EXCHANGE_OCR_DARK_LETTER = (70, 62, 54)

# Card grid geometry (1280x720).
EXCHANGE_ROWS = (
    {'row': 0, 'name': (156, 188), 'strip': (378, 412), 'tap': 285},
    {'row': 1, 'name': (444, 476), 'strip': (666, 700), 'tap': 573},
)
EXCHANGE_SAFE_LEFT = 295
EXCHANGE_SAFE_RIGHT = 1278
EXCHANGE_MIN_CARD_W = 235
EXCHANGE_MAX_CARD_W = 295
EXCHANGE_STRIP_BRIDGE = 12
EXCHANGE_SOLD_STRIP_MEAN = 188.0
EXCHANGE_GOODS_AREA = (300, 145, 1265, 705)
EXCHANGE_AMOUNT_AREA = (550, 410, 1040, 570)
EXCHANGE_DIALOG_COST_AREA = (790, 524, 1030, 560)
EXCHANGE_MOVED_DIFF = 2.0
EXCHANGE_MAX_PAGES = 8
EXCHANGE_STEP_PX = 592

EXCHANGE_OCR_LETTER = (235, 230, 220)
EXCHANGE_OCR_THRESHOLD = 128
EXCHANGE_MAX_ATTEMPTS = 2


class LostswordExchange:
    """
    Mixin providing Lost Sword Exchange (`交易所`) sub-shop purchasing.

    Designed to be mixed into `LostswordShop(LostswordUI, LostswordExchange)`.
    """

    def exchange_run(self):
        """
        Sweep configured sub-shops inside the `交易所` tab.

        Pages:
            in: page_shop
            out: page_shop
        """
        logger.hr('Exchange shop', level=1)
        self.ui_ensure(page_shop)
        if not self.exchange_goto_tab():
            logger.warning('[Exchange] 交易所 tab did not open, skipped')
            return 0

        total = 0
        for key in ('consumable', 'raid', 'guild', 'arena'):
            label, area, cfg_key = EXCHANGE_SUBTABS[key]
            raw = getattr(self.config, f'LostswordShop_{cfg_key}', '')
            total += self.exchange_run_subtab(key, label, area, raw)

        event_raw = getattr(self.config, 'LostswordShop_EventFilter', '')
        total += self.exchange_run_event(event_raw)
        logger.attr('Exchange bought', total)
        return total

    # ---- navigation --------------------------------------------------------

    def exchange_goto_tab(self, timeout=10):
        """
        Switch top bar to 「交易所」.

        Uses `SHOP_TITLE` plus `shop_tab_selected(SHOP_TAB_EXCHANGE)` instead
        of template matching `SHOP_TAB_EXCHANGE`, because the template was taken
        in its bright cream selected state and inverts correlation when idle.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            if self.shop_tab_selected(SHOP_TAB_EXCHANGE):
                return True
            if timeout.reached():
                logger.warning('[Exchange] cannot open 交易所 tab')
                return False
            if self.appear(SHOP_TITLE, offset=30, interval=1.5):
                self.device.click(SHOP_TAB_EXCHANGE)

    def _scroll_sidebar(self, start, end, stop_check=None):
        """Drag the left sidebar until `stop_check` holds or the list stops moving."""
        for _ in range(3):
            if stop_check is not None and stop_check():
                return
            before = self.image_crop(EXCHANGE_SIDEBAR_AREA, copy=True).astype(np.int16)
            self.device.swipe(start, end, name='EXCHANGE_SIDEBAR_SCROLL')
            self.wait_until_still(EXCHANGE_SIDEBAR_AREA, timeout=1.5, skip_first_screenshot=False)
            self.device.screenshot()
            after = self.image_crop(EXCHANGE_SIDEBAR_AREA, copy=True).astype(np.int16)
            if float(np.abs(after - before).mean()) <= EXCHANGE_MOVED_DIFF:
                return

    def exchange_sidebar_top(self):
        """Ensure fixed sidebar tabs sit at their top-aligned positions."""
        top_area = EXCHANGE_SUBTABS['consumable'][1]
        self._scroll_sidebar(
            (160, 220),
            (160, 580),
            stop_check=lambda: (
                self.exchange_area_bright(top_area)
                or '消耗' in self.exchange_ocr_tab(self.device.image, EXCHANGE_TOP_CENTERS[0])
            ),
        )

    def exchange_sidebar_bottom(self):
        """Scroll the left sidebar all the way down to reveal timed event coin tabs."""
        self._scroll_sidebar((160, 560), (160, 200))

    def exchange_select_slot(self, label, area, timeout=8):
        """Click a sidebar slot area and wait until its cream highlight becomes active."""
        btn = exchange_area_button(area, name=f'EXCHANGE_TAB_{label}')
        timer = Timer(timeout).start()
        for _ in self.loop():
            if self.exchange_area_bright(area):
                return True
            if timer.reached():
                logger.warning(f'[Exchange] {label} tab did not become active')
                return False
            if self.appear(SHOP_TITLE, offset=30, interval=1.5):
                self.device.click(btn)

    def exchange_select_fixed(self, label, area, timeout=8):
        """Select a top-aligned sub-tab (`消耗品` / `突袭` / `公会` / `竞技场`)."""
        self.exchange_sidebar_top()
        target_area = self.exchange_locate_fixed_tab(self.device.image, label, area)
        return self.exchange_select_slot(label, target_area, timeout=timeout)

    def exchange_area_bright(self, area):
        color = get_color(self.device.image, area)
        return sum(color) / 3 > EXCHANGE_TAB_SELECTED_MEAN

    @staticmethod
    def exchange_ocr_single(image, area, dark=False):
        letter = EXCHANGE_OCR_DARK_LETTER if dark else EXCHANGE_OCR_LETTER
        ocr = Ocr([], lang='cnocr', letter=letter, threshold=EXCHANGE_OCR_THRESHOLD)
        ocr.SHOW_LOG = False
        res = ocr.ocr([crop(image, np.array(area))], direct_ocr=True)
        return res[0] if res else ''

    @classmethod
    def exchange_ocr_tab(cls, image, cy, upper=False):
        """OCR one left-sidebar slot centered at `cy`, choosing ink polarity by pill highlight."""
        bright = sum(get_color(image, (80, cy - 22, 240, cy + 22))) / 3 > EXCHANGE_TAB_SELECTED_MEAN
        area = (75, cy - 34, 245, cy + 2) if upper else (75, cy - 20, 245, cy + 20)
        return cls.exchange_ocr_single(image, area, dark=bright)

    @classmethod
    def exchange_locate_fixed_tab(cls, image, label, default_area):
        """Locate a fixed permanent sub-tab dynamically in top-scrolled slots."""
        key = label[:2]
        for cy in EXCHANGE_TOP_CENTERS:
            if key in cls.exchange_ocr_tab(image, cy):
                return (80, cy - 22, 240, cy + 22)
        return default_area

    @classmethod
    def exchange_find_event_tabs(cls, image):
        """Return active timed event currency tabs `[(name, area), ...]` from bottom slots."""
        found = []
        for cy in EXCHANGE_BOTTOM_CENTERS:
            lo_std = float(crop(image, np.array((95, cy + 12, 225, cy + 32))).mean(axis=2).std())
            if lo_std < EXCHANGE_EVENT_DATE_STD:
                continue
            name = cls.exchange_ocr_tab(image, cy, upper=True).strip() or '活动币'
            if any(k in name for k in EXCHANGE_PERMANENT_KEYWORDS):
                continue
            found.append((name, (80, cy - 22, 240, cy + 22)))
        return found

    # ---- shelf reading & scrolling -----------------------------------------

    @staticmethod
    def exchange_strip_runs(band):
        """Find full card column spans `(x1, x2)` from an 85th-percentile row strip profile."""
        raw, start = [], None
        for x, val in enumerate(band):
            if val > 150 and start is None:
                start = x
            elif val <= 150 and start is not None:
                raw.append((start, x))
                start = None
        if start is not None:
            raw.append((start, len(band)))

        merged = []
        for x1, x2 in raw:
            if merged and x1 - merged[-1][1] <= EXCHANGE_STRIP_BRIDGE:
                merged[-1] = (merged[-1][0], x2)
            else:
                merged.append((x1, x2))

        return [
            (x1, x2) for x1, x2 in merged
            if EXCHANGE_MIN_CARD_W <= x2 - x1 <= EXCHANGE_MAX_CARD_W
            and EXCHANGE_SAFE_LEFT <= x1 and x2 <= EXCHANGE_SAFE_RIGHT
        ]

    def exchange_scan_screen(self, include_all=False):
        """
        Read all cards on the current shelf view.

        By default skips `售罄` and diamond (`paid`) cards before OCR so they
        are neither slow to read nor ever clickable.
        """
        image = self.device.image
        candidates = []
        for spec in EXCHANGE_ROWS:
            sy1, sy2 = spec['strip']
            ny1, ny2 = spec['name']
            band = np.percentile(image[sy1:sy2, :, :].mean(axis=2), 85, axis=0)
            for x1, x2 in self.exchange_strip_runs(band):
                sold_out = float(band[x1:x2].mean()) < EXCHANGE_SOLD_STRIP_MEAN
                paid = exchange_has_blue_diamond(image, (x1 + 25, sy1 + 2, x2 - 25, sy2 - 2))
                if not include_all and (sold_out or paid):
                    continue
                candidates.append({
                    'row': spec['row'],
                    'x1': x1,
                    'x2': x2,
                    'tap_y': spec['tap'],
                    'name_area': (x1 + 14, ny1, x2 - 14, ny2),
                    'sold_out': sold_out,
                    'paid': paid,
                    'title': '',
                    'norm': '',
                })

        if candidates:
            ocr = Ocr([], lang='cnocr', letter=EXCHANGE_OCR_LETTER, threshold=EXCHANGE_OCR_THRESHOLD)
            ocr.SHOW_LOG = False
            crops = [crop(image, np.array(c['name_area'])) for c in candidates]
            titles = ocr.ocr(crops, direct_ocr=True)
            for c, title in zip(candidates, titles):
                c['title'] = title
                c['norm'] = exchange_norm(title)
        return candidates

    def exchange_goods_diff(self, before):
        area = EXCHANGE_GOODS_AREA
        after = self.image_crop(area, copy=True).astype(np.int16)
        return float(np.abs(after - before).mean())

    def exchange_drag_shelf(self, delta_x):
        """Drag shelf horizontally; `delta_x > 0` advances right towards later items."""
        before = self.image_crop(EXCHANGE_GOODS_AREA, copy=True).astype(np.int16)
        x1 = 1050 if delta_x > 0 else 420
        x2 = max(320, min(1150, x1 - delta_x))
        self.device.drag((x1, 420), (x2, 420), point_random=(-5, -5, 5, 5),
                         hold_duration=0.3, name='EXCHANGE_SCROLL')
        self.wait_until_still(EXCHANGE_GOODS_AREA, timeout=2.0, skip_first_screenshot=False)
        self.device.screenshot()
        return self.exchange_goods_diff(before) > EXCHANGE_MOVED_DIFF

    def exchange_scroll_home(self):
        """Scroll horizontal shelf back to its leftmost column."""
        self.wait_until_still(EXCHANGE_GOODS_AREA, timeout=1.0, skip_first_screenshot=False)
        for _ in range(EXCHANGE_MAX_PAGES):
            if not self.exchange_drag_shelf(-700):
                break
        self.device.click_record_clear()

    # ---- buying flow -------------------------------------------------------

    def exchange_run_subtab(self, key, label, area, raw_filter):
        includes, excludes = exchange_parse_filter(raw_filter)
        if not includes:
            logger.info(f'[Exchange] {label}: skipped (disabled by filter)')
            return 0
        logger.hr(f'Exchange · {label}', level=2)
        if not self.exchange_select_fixed(label, area):
            return 0
        return self.exchange_sweep(label, includes, excludes)

    def exchange_run_event(self, raw_filter):
        includes, excludes = exchange_parse_filter(raw_filter)
        if not includes:
            logger.info('[Exchange] 活动: skipped (disabled by filter)')
            return 0
        self.exchange_sidebar_bottom()
        tabs = self.exchange_find_event_tabs(self.device.image)
        if not tabs:
            logger.info('[Exchange] no active event currency tab')
            return 0
        total = 0
        for name, area in tabs:
            logger.hr(f'Exchange · 活动 ({name})', level=2)
            if not self.exchange_select_slot(name, area):
                continue
            total += self.exchange_sweep(f'活动·{name}', includes, excludes)
        return total

    def exchange_collect_all(self, includes, excludes, skipped=None):
        """Scroll left-to-right across pages and collect matching non-paid items."""
        self.exchange_scroll_home()
        skipped = skipped or set()
        found = {}
        current_page = 0
        for page_idx in range(EXCHANGE_MAX_PAGES):
            self.device.stuck_record_clear()
            for card in self.exchange_scan_screen():
                rank = exchange_match_rank(card['title'], includes, excludes)
                if rank is None:
                    continue
                key = (card['row'], card['norm'])
                if key in skipped or key in found:
                    continue
                card['rank'] = rank
                card['page'] = page_idx
                found[key] = card
            current_page = page_idx
            if not self.exchange_drag_shelf(EXCHANGE_STEP_PX):
                break
        self.device.click_record_clear()
        return list(found.values()), current_page

    def exchange_seek_card(self, target, current_page):
        """Navigate shelf to the live view holding `target` and return updated card."""
        def _match_screen():
            for c in self.exchange_scan_screen():
                if c['row'] == target['row'] and exchange_keyword_hit(target['title'], c['title']):
                    return c
            return None

        live = _match_screen()
        if live is not None:
            return live, current_page

        step = -EXCHANGE_STEP_PX if target['page'] < current_page else EXCHANGE_STEP_PX
        for _ in range(EXCHANGE_MAX_PAGES):
            self.device.stuck_record_clear()
            moved = self.exchange_drag_shelf(step)
            current_page += -1 if step < 0 else 1
            live = _match_screen()
            if live is not None:
                return live, current_page
            if not moved:
                break

        self.exchange_scroll_home()
        current_page = 0
        for page_idx in range(EXCHANGE_MAX_PAGES):
            live = _match_screen()
            if live is not None:
                return live, page_idx
            if not self.exchange_drag_shelf(EXCHANGE_STEP_PX):
                break
            current_page = page_idx + 1
        return None, current_page

    def exchange_sweep(self, label, includes, excludes):
        """Buy wanted items in priority order inside the currently open sub-tab."""
        bought = 0
        items, current_page = self.exchange_collect_all(includes, excludes)
        items.sort(key=lambda c: (c['rank'], c['page'], c['row'], c['x1']))

        for target in items:
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            live, current_page = self.exchange_seek_card(target, current_page)
            if live is None:
                continue
            if self.exchange_buy_card(live) == 'bought':
                bought += 1

        logger.info(f'[Exchange] {label}: bought {bought} item(s)')
        return bought

    def exchange_buy_card(self, card, timeout=6):
        """
        Open card dialog, verify non-diamond, pull quantity with `>>`, and buy.

        Returns:
            str: `'bought'`, `'insufficient'`, `'paid'`, or `'skipped'`.
        """
        cx = (card['x1'] + card['x2']) // 2
        cy = card['tap_y']
        btn = exchange_area_button((cx - 35, cy - 25, cx + 35, cy + 25), name='EXCHANGE_CARD')
        logger.info(f"[Exchange] open {card['title']} @row{card['row']}({cx},{cy})")

        timer = Timer(timeout).start()
        for _ in self.loop():
            if self.appear(SHOP_DIALOG_TITLE, offset=30):
                if self.wait_overlay_settle(SHOP_DIALOG_TITLE):
                    break
                continue
            if timer.reached():
                logger.warning(f"[Exchange] purchase dialog did not open for {card['title']}")
                return 'skipped'
            if self.appear(SHOP_TITLE, offset=30, interval=2):
                self.device.click(btn)

        if exchange_has_blue_diamond(self.device.image, EXCHANGE_DIALOG_COST_AREA, EXCHANGE_BLUE_DIALOG_MIN):
            logger.warning(f"[Exchange] diamond cost detected for {card['title']}, aborting")
            self.shop_close_dialog()
            return 'paid'

        if self.appear(SHOP_EXCHANGE_MAX, offset=20):
            self.device.click(SHOP_EXCHANGE_MAX)
            self.wait_until_still(EXCHANGE_AMOUNT_AREA, timeout=1.0, skip_first_screenshot=False)

        if self.appear(SHOP_DIALOG_TITLE, offset=30):
            self.device.click(SHOP_EXCHANGE_BUY)

        confirm_timer = Timer(timeout).start()
        for _ in self.loop():
            if self.appear(SHOP_LACK_CONFIRM, offset=30):
                logger.info(f"[Exchange] resource insufficient for {card['title']}, skip")
                self.device.click(SHOP_LACK_CONFIRM)
                self.wait_until_disappear(SHOP_LACK_CONFIRM, offset=30, timeout=3, settle=self.SETTLE_FRAMES)
                self.shop_close_dialog()
                return 'insufficient'
            if self.appear(REWARD_POPUP_TITLE, offset=30):
                self.handle_reward_popup()
                return 'bought'
            if confirm_timer.reached():
                logger.warning(f"[Exchange] confirm timeout for {card['title']}")
                self.shop_close_dialog()
                return 'skipped'
