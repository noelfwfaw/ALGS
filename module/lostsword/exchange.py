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
from module.exception import TaskFailed
from module.logger import logger
from module.lostsword.assets import (REWARD_POPUP_TITLE, SHOP_DIALOG_TITLE,
                                     SHOP_EXCHANGE_BUY, SHOP_EXCHANGE_MAX,
                                     SHOP_LACK_CONFIRM, SHOP_TAB_EXCHANGE,
                                     SHOP_TITLE)
from module.lostsword.exchange_filter import (EXCHANGE_BLUE_DIALOG_MIN,
                                              exchange_area_button,
                                              exchange_has_blue_diamond,
                                              exchange_has_gold_coin,
                                              exchange_is_event_ticket,
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
EXCHANGE_EVENT_BALANCE_AREA = (978, 22, 1068, 52)
EXCHANGE_EVENT_BALANCE_BRIGHT = 165
EXCHANGE_PAGE_BUY_CAP = 12


def exchange_same_card(first, second):
    """
    Whether two scanned cards represent the same shelf item across reflows.

    Buying an item shifts trailing cards left and can flip their row (`0 <-> 1`),
    so identity tracks the normalized title rather than the row slot.
    """
    if first['norm'] and first['norm'] == second['norm']:
        return True
    return exchange_keyword_hit(first['title'], second['title'])


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
    def exchange_ocr_single(image, area, dark=False, alphabet=None):
        letter = EXCHANGE_OCR_DARK_LETTER if dark else EXCHANGE_OCR_LETTER
        ocr = Ocr([], lang='cnocr', letter=letter, threshold=EXCHANGE_OCR_THRESHOLD, alphabet=alphabet)
        ocr.SHOW_LOG = False
        res = ocr.ocr([crop(image, np.array(area))], direct_ocr=True)
        return res[0] if res else ''

    @staticmethod
    def exchange_parse_int(text):
        """Parse an integer coin balance or price string, returning `None` if unreadable."""
        digits = ''.join(ch for ch in (text or '') if ch.isdigit())
        return int(digits) if digits else None

    @classmethod
    def exchange_read_event_balance(cls, image):
        """Read the active event currency balance in the top-right bar, or `None`."""
        x1, y1, _, _ = EXCHANGE_EVENT_BALANCE_AREA
        sub = crop(image, np.array(EXCHANGE_EVENT_BALANCE_AREA))
        ys, xs = np.where(sub.min(axis=2) > EXCHANGE_EVENT_BALANCE_BRIGHT)
        if not ys.size:
            return None
        pad = 3
        tight = (
            max(0, x1 + int(xs.min()) - pad),
            max(0, y1 + int(ys.min()) - pad),
            min(image.shape[1], x1 + int(xs.max()) + pad + 1),
            min(image.shape[0], y1 + int(ys.max()) + pad + 1),
        )
        return cls.exchange_parse_int(cls.exchange_ocr_single(image, tight, alphabet='0123456789,'))

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
                icon_area = (x1 + 25, sy1 + 2, x2 - 25, sy2 - 2)
                paid = exchange_has_blue_diamond(image, icon_area)
                if not include_all and (sold_out or paid):
                    continue
                gold = exchange_has_gold_coin(image, icon_area)
                candidates.append({
                    'row': spec['row'],
                    'x1': x1,
                    'x2': x2,
                    'tap_y': spec['tap'],
                    'name_area': (x1 + 14, ny1, x2 - 14, ny2),
                    'price_area': (x1 + 55, sy1 + 2, x2 - 15, sy2 - 2),
                    'sold_out': sold_out,
                    'paid': paid,
                    'gold': gold,
                    'title': '',
                    'norm': '',
                    'price': None,
                })

        if candidates:
            ocr = Ocr([], lang='cnocr', letter=EXCHANGE_OCR_LETTER, threshold=EXCHANGE_OCR_THRESHOLD)
            ocr.SHOW_LOG = False
            crops = [crop(image, np.array(c['name_area'])) for c in candidates]
            for c, title in zip(candidates, ocr.ocr(crops, direct_ocr=True)):
                c['title'] = title
                c['norm'] = exchange_norm(title)

            price_ocr = Ocr([], lang='cnocr', letter=EXCHANGE_OCR_DARK_LETTER,
                            threshold=EXCHANGE_OCR_THRESHOLD, alphabet='0123456789,')
            price_ocr.SHOW_LOG = False
            price_crops = [crop(image, np.array(c['price_area'])) for c in candidates]
            for c, raw_price in zip(candidates, price_ocr.ocr(price_crops, direct_ocr=True)):
                c['price'] = self.exchange_parse_int(raw_price)
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
            total += self.exchange_sweep(f'活动·{name}', includes, excludes, single_currency=True)
        return total

    def _exchange_init_budget(self, label, single_currency):
        if not single_currency:
            return None
        budget = self.exchange_read_event_balance(self.device.image)
        if budget is not None:
            logger.info(f'[Exchange] {label}: balance={budget}')
        return budget

    @staticmethod
    def _exchange_affordable(card, budget, single_currency=False):
        if single_currency and exchange_is_event_ticket(card):
            return True
        price = card.get('price')
        return price is None or budget is None or price <= budget

    def _exchange_after_buy(self, label, status, card, budget, single_currency):
        """Refresh remaining event coin budget and tell whether the sweep should stop."""
        if not single_currency:
            return budget, False
        if exchange_is_event_ticket(card):
            # Gold-priced ticket does not spend event currency and must not cap event-coin budget.
            return budget, False
        if status == 'bought':
            self.device.screenshot()
            refreshed = self.exchange_read_event_balance(self.device.image)
            if refreshed is not None:
                budget = refreshed
                logger.info(f'[Exchange] {label}: remaining balance={budget}')
            return budget, budget == 0
        if status == 'insufficient':
            self.device.screenshot()
            refreshed = self.exchange_read_event_balance(self.device.image)
            if refreshed is not None:
                budget = refreshed
            price = card.get('price')
            if price is not None and (budget is None or budget >= price):
                budget = max(0, price - 1)
            if budget is not None:
                logger.info(f'[Exchange] {label}: budget capped at {budget} after insufficient warning')
            return budget, budget == 0
        return budget, False

    def exchange_collect_all(self, includes, excludes, skipped=None, budget=None, single_currency=False):
        """Collect matching items and the stable card anchors of each visited view."""
        self.exchange_scroll_home()
        skipped = skipped or set()
        found = {}
        pages = []
        for page_idx in range(EXCHANGE_MAX_PAGES):
            self.device.stuck_record_clear()
            cards = self.exchange_scan_screen()
            view = {(c['row'], c['norm']) for c in cards if c['norm']}
            if pages and view == pages[-1]:
                # Shelf did not change: stop instead of indexing a phantom page.
                break
            pages.append(view)
            for card in cards:
                rank = exchange_match_rank(card['title'], includes, excludes)
                if rank is None or not self._exchange_affordable(card, budget, single_currency=single_currency):
                    continue
                if single_currency and exchange_is_event_ticket(card):
                    rank = -1
                key = card['norm'] or card['title']
                if key in skipped or key in found:
                    continue
                card['rank'] = rank
                card['page'] = page_idx
                found[key] = card
            if page_idx + 1 >= EXCHANGE_MAX_PAGES:
                # Scan cap reached: do not drag past the last indexed view.
                break
            if not self.exchange_drag_shelf(EXCHANGE_STEP_PX):
                break
        self.device.click_record_clear()
        return list(found.values()), pages

    def exchange_seek_card(self, target, pages, current_page):
        """Use live card anchors to navigate to `target` without assuming row invariance."""
        def locate():
            cards = self.exchange_scan_screen()
            live = next((card for card in cards
                         if exchange_keyword_hit(target['title'], card['title'])), None)
            screen = {(c['row'], c['norm']) for c in cards if c['norm']}
            scores = [len(screen & page) for page in pages]
            if not scores or max(scores) == 0 or scores.count(max(scores)) != 1:
                return live, None
            return live, scores.index(max(scores))

        live, position = locate()
        if live is not None:
            return live, current_page if position is None else position
        if position is not None:
            current_page = position
        elif current_page is None:
            # A purchase can reset the shelf and invalidate every saved anchor.
            self.exchange_scroll_home()
            current_page = 0
            live, position = locate()
            if live is not None:
                return live, current_page if position is None else position
        if target['page'] == current_page:
            return None, current_page

        step = -EXCHANGE_STEP_PX if target['page'] < current_page else EXCHANGE_STEP_PX
        for _ in range(EXCHANGE_MAX_PAGES):
            self.device.stuck_record_clear()
            previous_page = current_page
            if not self.exchange_drag_shelf(step):
                return None, current_page
            current_page += -1 if step < 0 else 1
            live, position = locate()
            if live is not None:
                return live, current_page if position is None else position
            if position is not None:
                if position == previous_page:
                    # Anchors confirm the shelf stayed on this page: stop retrying the same drag.
                    return None, position
                current_page = position
            if current_page == target['page']:
                break
        return None, current_page

    @staticmethod
    def exchange_order_items(items):
        """Sort wanted cards by filter priority first, then by their shelf position."""
        return sorted(items, key=lambda c: (c['rank'], c['page'], c['row'], c['x1']))

    @staticmethod
    def exchange_merge_items(pending, fresh):
        """
        Merge a rescan into the cards that are still waiting to be bought.

        The pending list keeps its order and a card the rescan saw again replaces
        its stale copy, so one card is never ordered twice.
        """
        merged = []
        for card in pending:
            same = next((c for c in fresh if exchange_same_card(card, c)), None)
            merged.append(same if same is not None else card)
        for card in fresh:
            if any(exchange_same_card(card, c) for c in merged):
                continue
            merged.append(card)
        return merged

    def _exchange_buy_event_tickets(self, label, includes, excludes, budget):
        """
        Scan left-to-right to buy gold-priced event sweep tickets first.

        Also records whether any non-ticket wanted item is affordable so Phase 2
        can be skipped completely when event coins are 0 or insufficient.
        """
        self.exchange_scroll_home()
        bought = 0
        attempted = set()
        drags = 0
        prev_view = None
        has_affordable_event = False
        reached_end = False
        last_cards = None

        for _ in range(EXCHANGE_MAX_PAGES):
            page_bought = False
            for _ in range(EXCHANGE_PAGE_BUY_CAP):
                self.device.stuck_record_clear()
                self.device.click_record_clear()
                cards = self.exchange_scan_screen()
                last_cards = cards
                view = tuple((c['row'], c['norm'] or c['title']) for c in cards)
                if not page_bought and prev_view is not None and view == prev_view:
                    reached_end = True
                    break

                matches = [
                    c for c in cards
                    if exchange_match_rank(c['title'], includes, excludes) is not None
                    and (c['norm'] or c['title']) not in attempted
                ]
                for c in matches:
                    if not exchange_is_event_ticket(c) and budget != 0 and self._exchange_affordable(c, budget):
                        has_affordable_event = True
                tickets = sorted(
                    (c for c in matches if exchange_is_event_ticket(c)),
                    key=lambda c: (c['x1'], c['row']),
                )
                if tickets:
                    target = tickets[0]
                    attempted.add(target['norm'] or target['title'])
                    if self.exchange_buy_card(target) == 'bought':
                        bought += 1
                        page_bought = True
                        prev_view = None
                else:
                    prev_view = view
                    break
            if reached_end or bought > 0:
                break
            if not self.exchange_drag_shelf(EXCHANGE_STEP_PX):
                reached_end = True
                break
            drags += 1

        return bought, attempted, drags, has_affordable_event, reached_end, last_cards

    def _exchange_sweep_single_pass(self, label, includes, excludes, budget, single_currency):
        """
        Sweep left-to-right when all wanted items share one priority.

        In event shops, buys gold-priced sweep tickets (`*票券`) first, then
        buys affordable event-coin items in a single left-to-right pass.
        """
        if single_currency:
            (bought, attempted, drags, has_affordable_event,
             reached_end, last_cards) = self._exchange_buy_event_tickets(label, includes, excludes, budget)
            if budget == 0 or (reached_end and not has_affordable_event):
                if not has_affordable_event and last_cards:
                    for c in last_cards:
                        if (exchange_match_rank(c['title'], includes, excludes) is not None
                                and not exchange_is_event_ticket(c)
                                and not self._exchange_affordable(c, budget)):
                            logger.info(
                                f"[Exchange] {label}: skip {c['title']} (price={c.get('price')} > budget={budget})"
                            )
                logger.info(f'[Exchange] {label}: bought {bought} item(s)')
                return bought
            if drags > 0:
                self.exchange_scroll_home()
                initial_cards = None
            else:
                initial_cards = last_cards
        else:
            self.exchange_scroll_home()
            bought = 0
            attempted = set()
            initial_cards = None

        prev_view = None
        for _ in range(EXCHANGE_MAX_PAGES):
            page_bought = False
            for _ in range(EXCHANGE_PAGE_BUY_CAP):
                self.device.stuck_record_clear()
                self.device.click_record_clear()
                if initial_cards is not None:
                    cards = initial_cards
                    initial_cards = None
                else:
                    cards = self.exchange_scan_screen()
                view = tuple((c['row'], c['norm'] or c['title']) for c in cards)
                if not page_bought and prev_view is not None and view == prev_view:
                    logger.info(f'[Exchange] {label}: bought {bought} item(s)')
                    return bought

                matches = [
                    c for c in cards
                    if exchange_match_rank(c['title'], includes, excludes) is not None
                    and (c['norm'] or c['title']) not in attempted
                ]
                matches.sort(key=lambda c: (c['x1'], c['row']))
                target = next(
                    (c for c in matches if self._exchange_affordable(c, budget, single_currency=single_currency)),
                    None,
                )
                if target is None:
                    for c in matches:
                        logger.info(f"[Exchange] {label}: skip {c['title']} (price={c.get('price')} > budget={budget})")
                        attempted.add(c['norm'] or c['title'])
                    prev_view = view
                    break

                attempted.add(target['norm'] or target['title'])
                status = self.exchange_buy_card(target)
                budget, stop = self._exchange_after_buy(label, status, target, budget, single_currency)
                if status == 'bought':
                    bought += 1
                    page_bought = True
                    prev_view = None
                if stop:
                    logger.info(f'[Exchange] {label}: bought {bought} item(s)')
                    return bought
            if not self.exchange_drag_shelf(EXCHANGE_STEP_PX):
                break

        logger.info(f'[Exchange] {label}: bought {bought} item(s)')
        return bought

    def exchange_sweep(self, label, includes, excludes, single_currency=False):
        """
        Buy wanted items inside the open sub-tab, stopping cleanly when out of funds.

        Uses a single forward pass for single-tier event filters and priority-ordered
        seeking with one shared rescan for multi-tier filters.

        Pages:
            in: page_shop
            out: page_shop
        """
        budget = self._exchange_init_budget(label, single_currency)
        if single_currency and len(includes) == 1:
            return self._exchange_sweep_single_pass(label, includes, excludes, budget, single_currency)

        bought = 0
        attempted = set()
        items, pages = self.exchange_collect_all(
            includes, excludes, skipped=attempted, budget=budget, single_currency=single_currency,
        )
        items = self.exchange_order_items(items)
        current_page = len(pages) - 1
        rescan_used = False
        while items:
            target = items.pop(0)
            if not self._exchange_affordable(target, budget, single_currency=single_currency):
                logger.info(f"[Exchange] {label}: skip {target['title']} (price={target.get('price')} > budget={budget})")
                continue
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            live, current_page = self.exchange_seek_card(target, pages, current_page)
            if live is None:
                if rescan_used:
                    attempted.add(target['norm'] or target['title'])
                    continue
                rescan_used = True
                logger.info(f'[Exchange] {label}: {target["title"]} left the shelf, rescan')
                fresh, pages = self.exchange_collect_all(
                    includes, excludes, skipped=attempted, budget=budget, single_currency=single_currency,
                )
                current_page = len(pages) - 1
                items = self.exchange_order_items(self.exchange_merge_items(items, fresh))
                continue
            key = live['norm'] or live['title']
            attempted.add(key)
            if not self._exchange_affordable(live, budget, single_currency=single_currency):
                logger.info(f"[Exchange] {label}: skip {live['title']} (price={live.get('price')} > budget={budget})")
                continue
            status = self.exchange_buy_card(live)
            budget, stop = self._exchange_after_buy(label, status, live, budget, single_currency)
            if status == 'bought':
                bought += 1
            if stop:
                break
            current_page = None
        logger.info(f'[Exchange] {label}: bought {bought} item(s)')
        return bought

    def exchange_fail(self, message):
        """Postpone a failed exchange run without marking it successful."""
        logger.warning(message)
        self.config.task_delay(success=False)
        raise TaskFailed(message)

    def exchange_dismiss_lack(self, timeout=3):
        """Press the warning's confirm button and verify the inner modal leaves."""
        if not self.wait_overlay_settle(SHOP_LACK_CONFIRM, timeout=timeout):
            return False
        for _ in range(3):
            if self.appear(SHOP_LACK_CONFIRM, offset=30):
                self.device.click(SHOP_LACK_CONFIRM)
                if self.wait_overlay_gone(SHOP_LACK_CONFIRM, timeout=timeout):
                    return True
                continue
            return self.wait_overlay_gone(SHOP_LACK_CONFIRM, timeout=timeout)
        return False

    def exchange_close_dialog(self, timeout=6):
        """Close the purchase dialog and verify the shelf is ready for another click."""
        timer = Timer(timeout).start()
        for _ in self.loop():
            if self.appear(SHOP_DIALOG_TITLE, offset=30):
                if self.shop_close_dialog():
                    continue
            elif self.appear(SHOP_TITLE, offset=30):
                return self.wait_overlay_gone(SHOP_DIALOG_TITLE, timeout=timeout)
            if timer.reached():
                return False

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
            if not self.exchange_close_dialog(timeout=timeout):
                self.exchange_fail('[Exchange] Could not restore the shelf after detecting a paid item')
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
                if not self.exchange_dismiss_lack(timeout=3):
                    self.exchange_fail('[Exchange] Could not dismiss the insufficient-resource warning')
                if not self.exchange_close_dialog(timeout=timeout):
                    self.exchange_fail('[Exchange] Could not restore the shelf after insufficient resources')
                return 'insufficient'
            if self.appear(REWARD_POPUP_TITLE, offset=30):
                if not self.handle_reward_popup():
                    self.exchange_fail('[Exchange] Could not dismiss the purchase reward popup')
                if not self.exchange_close_dialog(timeout=timeout):
                    self.exchange_fail('[Exchange] Could not restore the shelf after purchase')
                return 'bought'
            if confirm_timer.reached():
                logger.warning(f"[Exchange] confirm timeout for {card['title']}")
                if not self.exchange_close_dialog(timeout=timeout):
                    self.exchange_fail('[Exchange] Could not restore the shelf after a confirmation timeout')
                return 'skipped'
