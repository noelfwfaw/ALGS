"""The exchange shop of the mall: 商城 → 兑换商店 → 精英商店.

进兑换商店时游戏默认就停在精英商店，但每一层仍要核对（版本会改默认页）。

The elite shop is a two-row grid that scrolls sideways, about four columns on
screen. Drags do not land the cards on a fixed grid (a 264 px drag moved the
list about 280 px), so nothing here may assume a position: every stop measures
where each card actually is from its white price strip - a bright band across
the bottom of every card that the dark gaps between cards interrupt - and the
name is OCR'd right above where that strip says the card is.

One OCR pass misreads one character now and then (调度券 came back as 调渡券,
as 调券, and correctly, depending on how much of the card frame the crop kept),
so every title is read twice, at two crop margins, and the filter matches when
either read hits an include and neither read hits an exclusion. Includes also
tolerate one missing character (调度券 hides inside the misread 调渡券 as soon
as the whole character set but one is there); exclusions stay strict, a fuzzy
exclusion would tar neighbours such as 精英调度券 with 演习券's brush.

Purchases (config `HazeworldShop.Purchases`) are a filter in the style of the
AzurLane one: entries separated by `>`, each entry matched as a substring of
the OCR'd name, an entry prefixed with `!` excludes. A card is bought when it
matches at least one entry and no exclusion, so monthly renames survive as
long as one keyword does. The default leaves out 盾币 (a one-gold currency
conversion without a purchase limit) and 精英演习券.

购买顺序 = 商店内从左到右、同一列先上后下；每个道具每次买 1 个。已售罄跳过；
买之前先 OCR 金币余额和价签，买不起就跳过（更便宜的后面的仍会试）。商品多
为月更，但精英演习券一类每周补货，所以本任务每周跑一次（下周一 05:00）。
"""

import re

import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.coupon.text import read_text
from module.hazeworld.assets import (EXCHANGE_TAB_ELITE, MALL_TAB_EXCHANGE,
                                     SHOP_DIALOG_CANCEL, SHOP_DIALOG_CONFIRM)
from module.hazeworld.hazeworld_ui import HazeworldUI
from module.hazeworld.page import page_mall
from module.hazeworld.schedule import next_week_refresh
from module.logger import logger
from module.ocr.ocr import Ocr

# Every card is a button of the same shape; only its x moves. Row 0 is the top
# row of the grid, row 1 the bottom one.
#
# NAME: where the card title is printed, OCR'd per card.
# STRIP: the white price band across the card bottom - the gaps between cards
#   break it, so a brightness profile over this band yields the cards' real x.
# SOLD: the 已售罄 band over a sold-out card, OCR'd for 售罄.
# TAP: y of the card centre, where the tap that opens the dialog goes.
SHOP_ROWS = (
    {'name': (196, 232), 'strip': (390, 420), 'sold': (300, 340), 'tap': 306},
    {'name': (443, 479), 'strip': (642, 672), 'sold': (548, 588), 'tap': 553},
)
# Left of this the sidebar of the shop covers the cards: a card starting here
# is only partly on screen and its tap would land on the sidebar.
SHOP_SAFE_LEFT = 240
SHOP_SAFE_RIGHT = 1280
# A price strip run shorter than this is the sliver of a card sliding out.
SHOP_MIN_CARD_WIDTH = 200
# The purchase dialog: its title 「是否购买...？」 sits here, whatever the item.
SHOP_DIALOG_TITLE = (470, 168, 900, 202)
# Its full extent, for the still-check before 确认: the dialog opens with a
# short animation and a press that lands inside it is eaten (measured: the
# confirm 0.2 s after the card press left the dialog open for good).
SHOP_DIALOG_AREA = (360, 150, 920, 540)
# The gold balance of the top bar, right aligned towards x=965. Digits only.
SHOP_GOLD_AREA = (890, 26, 968, 62)
# How the price on the strip is read: dark digits on the white band.
SHOP_PRICE_LETTER = (60, 60, 60)
SHOP_PRICE_THRESHOLD = 200
# The two crop margins a card title is read with: the tight crop keeps more of
# the characters but picks up the decorative brackets of the card frame, the
# wide one is safe from the brackets but can clip a long title. Between the
# two reads every keyword of the default filter survives at least once.
SHOP_NAME_MARGINS = (12, 25)
# Duration of the hold in every drag - without it the swipe carries momentum
# and the landing position becomes a guess.
SHOP_DRAG_HOLD = 0.4
# Area the drags run through, clear of the sidebar and of the goods.
SHOP_DRAG_Y = 400


class HazeworldShop(HazeworldUI):
    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Exchange shop', level=1)
        self.shop_filter_init()

        self.ui_ensure(page_mall)
        self.shop_goto_elite()
        self.shop_sweep()
        self.ui_goto_main()

        target = next_week_refresh()
        logger.attr('Shop next reset', str(target))
        self.config.task_delay(target=target)

    # ==================== filter ====================

    def shop_filter_init(self):
        """
        Split `HazeworldShop.Purchases` into include and exclude substrings.

        An empty include list buys nothing - a filter the user blanked must
        not turn into "buy everything on sight".
        """
        raw = str(self.config.HazeworldShop_Purchases or '')
        self.shop_include = []
        self.shop_exclude = []
        for part in re.split(r'[>＞]', raw):
            part = part.strip()
            if not part:
                continue
            if part.startswith('!'):
                self.shop_exclude.append(part[1:])
            else:
                self.shop_include.append(part)
        logger.attr('Shop filter', f'{len(self.shop_include)} include, '
                                   f'{len(self.shop_exclude)} exclude')

    def shop_filter_match(self, card):
        """
        Args:
            card (tuple): (row, x_left, x_right, name_a, name_b).

        Returns:
            bool: If the card should be bought - an include may hit either
            read, but an exclusion on any read wins.
        """
        names = card[3:]
        if any(word in name for name in names for word in self.shop_exclude):
            return False
        return any(self.shop_keyword_hit(word, name)
                   for name in names for word in self.shop_include)

    @staticmethod
    def shop_keyword_hit(word, name):
        """
        One include keyword against one OCR read, with one character of slack:
        the OCR drops and swaps single characters (度 came back as 渡), but the
        rest of the keyword is still there. Counted as a character multiset, so
        a keyword never matches by repeating one lucky character.

        Args:
            word (str): Filter entry.
            name (str): OCR'd card title.

        Returns:
            bool: If the keyword is in the name, or all but one of its
            characters are.
        """
        if word in name:
            return True
        if len(word) < 2:
            return False
        missing = sum(1 for ch in set(word) if name.count(ch) < word.count(ch))
        return missing == 1

    # ==================== money ====================

    @staticmethod
    def shop_read_int(image, area, letter, threshold):
        """OCR one number, digits only; None when nothing was read."""
        button = Button(area=area, color=(0, 0, 0), button=area, name='SHOP_NUM')
        ocr = Ocr(button, lang='cnocr', letter=letter, threshold=threshold,
                  name='SHOP_NUM')
        text = re.sub(r'\D', '', str(ocr.ocr(image)))
        return int(text) if text else None

    def shop_gold(self):
        """The gold balance in the top bar; None when unreadable, so a broken
        read never blocks a purchase the user asked for."""
        return self.shop_read_int(self.device.image, SHOP_GOLD_AREA,
                                  (255, 255, 255), 170)

    def shop_price(self, card):
        """The price on the white strip of a card; None when unreadable."""
        _, x1, x2, _name, _ = card
        row = SHOP_ROWS[card[0]]
        y1, y2 = row['strip']
        area = (x1 + 4, y1 + 2, x2 - 4, y2 - 2)
        return self.shop_read_int(self.device.image, area,
                                  SHOP_PRICE_LETTER, SHOP_PRICE_THRESHOLD)

    # ==================== navigation ====================

    def shop_goto_elite(self):
        """
        Open 兑换商店 and make sure 精英商店 is the selected sub shop: the
        game lands there by itself today, but each tab is pressed until its
        selected look is on screen, because defaults move between versions.
        """
        for check, press in [(MALL_TAB_EXCHANGE, MALL_TAB_EXCHANGE),
                             (EXCHANGE_TAB_ELITE, EXCHANGE_TAB_ELITE)]:
            timeout = Timer(8).start()
            press_timer = Timer(2.5).start()
            pressed = 0
            while 1:
                self.device.stuck_record_clear()
                self.device.screenshot()
                if self.appear(check, offset=(20, 20)):
                    break
                if timeout.reached():
                    logger.warning(f'{check} did not become selected')
                    break
                if press_timer.reached() and pressed < 3:
                    press_timer.reset()
                    pressed += 1
                    # The press is retried until the appear(check) above holds.
                    self.device.click(press)  # alas-lint: allow - verified by appear(check) in this loop
        # The grid fades in after the tabs settle; the first profile on a
        # half-drawn frame finds nothing and would read as the list end.
        self.wait_until_settled(MALL_TAB_EXCHANGE, timeout=5)

    # ==================== measuring ====================

    def shop_cards(self):
        """
        The cards on screen, measured from their price strips.

        Returns:
            list[tuple]: (row, x_left, x_right, name_a, name_b) of every card
            wide enough to be read, top row first, left to right. The two
            names are the same title read at two crop margins.
        """
        out = []
        image = self.device.image
        for row, spec in enumerate(SHOP_ROWS):
            y1, y2 = spec['strip']
            band = image[y1:y2, :, :].astype(np.int16)
            profile = (band.mean(axis=2) > 170).sum(axis=0)
            runs, start = [], None
            for x, value in enumerate(profile):
                if value > 10 and start is None:
                    start = x
                elif value <= 10 and start is not None:
                    if x - start >= SHOP_MIN_CARD_WIDTH:
                        runs.append((start, x))
                    start = None
            if start is not None and SHOP_SAFE_RIGHT - start >= SHOP_MIN_CARD_WIDTH:
                runs.append((start, SHOP_SAFE_RIGHT))
            for x1, x2 in runs:
                if x1 < SHOP_SAFE_LEFT:
                    continue
                ny1, ny2 = spec['name']
                names = tuple(
                    read_text(image, (x1 + m, ny1, x2 - m, ny2))
                    for m in SHOP_NAME_MARGINS)
                out.append((row, x1, x2) + names)
        return out

    def shop_columns(self, cards):
        """
        Group cards into columns: a top and a bottom card sharing an x.

        Returns:
            list[[int, tuple, tuple]]: [x_left, top_card, bottom_card], sorted
            left to right. A half of the pair may stay None.
        """
        columns = []
        for card in cards:
            for column in columns:
                if abs(card[1] - column[0]) < 40:
                    column[1 + card[0]] = card
                    break
            else:
                entry = [card[1], None, None]
                entry[1 + card[0]] = card
                columns.append(entry)
        return sorted(columns, key=lambda c: c[0])

    @staticmethod
    def shop_signature(columns):
        """
        What "the same goods as before" is judged on: every column's x and
        the title of its top card. An x alone can not tell a broken scroll
        from a working one - a successful advance lands the next column at
        the very x the last one sat at.
        """
        return '|'.join(
            f'{x}:{top[3] if top else ""}'
            for x, top, _ in columns)

    # ==================== scrolling ====================

    def shop_drag(self, delta):
        """
        Drag the goods sideways. `delta` > 0 moves them left (forward), the
        direction the sweep travels in.
        """
        x1 = 1000 if delta > 0 else 500
        x2 = max(280, min(1100, x1 - delta))
        self.device.drag((x1, SHOP_DRAG_Y), (x2, SHOP_DRAG_Y),
                         hold_duration=SHOP_DRAG_HOLD, name='SHOP_DRAG')

    def shop_settled_cards(self):
        """Screenshot once the goods have stopped moving, then measure."""
        self.wait_until_still((240, 180, 1280, 690), timeout=4)
        self.device.screenshot()
        return self.shop_columns(self.shop_cards())

    def shop_scroll_home(self):
        """
        Drag the list back to its start, so the sweep begins at card one.

        Returns:
            bool: If the start was reached.
        """
        for _ in range(15):
            self.device.screenshot()
            before = self.shop_signature(self.shop_columns(self.shop_cards()))
            if not before:
                continue
            self.shop_drag(-700)
            after = self.shop_signature(self.shop_settled_cards())
            if after == before:
                logger.info('Shop list is at its start')
                return True
        logger.warning('Shop list did not reach its start')
        return False

    def shop_advance(self, columns, current_x):
        """
        Bring the next column to where the processed one sat.

        Args:
            columns (list): The columns measured before the purchases.
            current_x (int): x of the column just processed.

        Returns:
            bool: If the next column is in place. False ends the sweep -
            nothing sits further right, or the list clamped.
        """
        right = [c[0] for c in columns if c[0] > current_x + 40]
        if not right:
            logger.info('No column further right, shop sweep is done')
            return False
        anchor = right[0]
        # The goods travel left by `delta`, so bringing the column at `anchor`
        # to `current_x` means moving them by the distance between the two.
        delta = anchor - current_x
        for _ in range(4):
            self.shop_drag(delta)
            landed = self.shop_settled_cards()
            if not landed:
                logger.info('The shop list is empty here, sweep is done')
                return False
            for x, _, _ in landed:
                if abs(x - current_x) < 45:
                    return True
            # Correct from wherever the goods actually went: the column that
            # used to sit at `anchor` is the one nearest to it now.
            nearest = min((c[0] for c in landed), key=lambda v: abs(v - anchor))
            if abs(nearest - anchor) < 10:
                logger.info('The shop list did not move, it is at its end')
                return False
            delta = nearest - current_x
        logger.warning('Shop advance did not converge')
        return False

    # ==================== buying ====================

    def shop_sweep(self):
        """
        Walk the list once, left to right, buying what the filter asks for:
        every column is bought before the list moves on. The sweep stops at
        the list end, at a purchase the game would not take, or when the very
        same goods show up where the last stop measured them - that means the
        scrolling broke. A working advance lands the next column at the x the
        last one sat at, so the x alone never means "back where we were".
        """
        bought = skipped = 0
        abort = False
        last_signature = None
        while not abort:
            self.device.screenshot()
            cards = self.shop_cards()
            if not cards:
                logger.info('No card readable, the sweep is done')
                break
            columns = self.shop_columns(cards)
            signature = self.shop_signature(columns)
            if signature == last_signature:
                logger.warning('The sweep sees the same goods again, '
                               'it stops here')
                break
            last_signature = signature
            x, top, bottom = columns[0]
            if x < SHOP_SAFE_LEFT:
                if not self.shop_advance(columns, x):
                    break
                continue
            for card in (top, bottom):
                if card is None:
                    continue
                result = self.shop_buy_card(card)
                if result == 'bought':
                    bought += 1
                elif result == 'skipped':
                    skipped += 1
                else:
                    abort = True
                    break
            if not abort:
                if not self.shop_advance(columns, x):
                    break
        logger.attr('Shop sweep', f'bought {bought}, skipped {skipped}')

    def shop_buy_card(self, card):
        """
        Buy one card, once; 'bought', 'insufficient' or 'skipped'.
        """
        row, x1, x2, name, _ = card
        if not self.shop_filter_match(card):
            logger.info(f'Skip {name}: not on the filter')
            return 'skipped'
        sy1, sy2 = SHOP_ROWS[row]['sold']
        sold = read_text(self.device.image, (x1 + 30, sy1, x2 - 30, sy2))
        if '售罄' in sold:
            logger.info(f'Skip {name}: sold out')
            return 'skipped'
        # The balance check comes before any press: a card the gold cannot
        # cover is skipped, and the sweep goes on to the cheaper cards behind
        # it instead of confirming into a rejection.
        price, gold = self.shop_price(card), self.shop_gold()
        if price is not None and gold is not None and gold < price:
            logger.info(f'Skip {name}: price {price} over gold {gold}')
            return 'skipped'

        logger.info(f'Buy {name}')
        ty = SHOP_ROWS[row]['tap']
        card_button = Button(area={'hazeworld': (x1 + 12, ty - 40, x2 - 12, ty + 40)},
                             color={'hazeworld': (0, 0, 0)},
                             button={'hazeworld': (x1 + 40, ty - 20, x2 - 40, ty + 20)},
                             name='SHOP_CARD')
        self.device.click(card_button)  # alas-lint: allow - first press, the dialog-title OCR below verifies and re-presses
        giveup = Timer(9).start()
        press = Timer(2.5).start()
        pressed = 0
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            title = read_text(self.device.image, SHOP_DIALOG_TITLE)
            if '购买' in title:
                # The dialog opens with a short animation; a confirm that lands
                # inside it is eaten and the dialog then never closes.
                self.wait_until_still(SHOP_DIALOG_AREA, timeout=2)
                self.device.screenshot()
                break
            if '不足' in title or '失败' in title:
                logger.warning(f'Cannot buy {name}: {title}')
                self.device.click(SHOP_DIALOG_CANCEL)  # alas-lint: allow - closes the error dialog just read
                return 'insufficient'
            if giveup.reached():
                logger.info(f'No dialog for {name}, treated as sold out')
                return 'skipped'
            if press.reached() and pressed < 2:
                press.reset()
                pressed += 1
                self.device.click(card_button)  # alas-lint: allow - re-press, verified by the title OCR above

        self.device.click(SHOP_DIALOG_CONFIRM)  # alas-lint: allow - the dialog was just confirmed by its title OCR
        closed = Timer(6).start()
        confirmed_again = False
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            title = read_text(self.device.image, SHOP_DIALOG_TITLE)
            if '购买' not in title:
                if '不足' in title:
                    logger.warning('Gold ran out, the sweep stops here')
                    self.device.click(SHOP_DIALOG_CANCEL)  # alas-lint: allow - closes the dialog just read
                    return 'insufficient'
                # A success popup may sit where the dialog was.
                self.handle_reward()
                return 'bought'
            if closed.reached() and not confirmed_again:
                # The first confirm may have landed in the open animation.
                confirmed_again = True
                closed.reset()
                self.device.click(SHOP_DIALOG_CONFIRM)  # alas-lint: allow - one retry of the press the dialog ate
                continue
            if closed.reached():
                logger.warning(f'The dialog for {name} did not close')
                self.device.click(SHOP_DIALOG_CANCEL)  # alas-lint: allow - last-resort close after the wait gave up
                return 'insufficient'
