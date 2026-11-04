"""The engine behind the sub shops of the exchange shop (商城 → 兑换商店).

Every sub shop of the mall is the same screen with a different left sidebar
entry selected: 精英商店, 调度商店, 后勤商店 and so on. They all show a two-row
grid that scrolls sideways and they all sell through the same purchase dialog.
Only three things differ between them, and that is exactly what a subclass
sets:

- `TAB`: the sidebar entry that selects the shop (its selected look).
- `CONFIG_TASK`: the task whose `Filter` / `Purchases` settings are read.
- `CURRENCY_*`: where the balance of the currency the prices are paid in sits
  in the top bar, and whether the game abbreviates it (后勤商店 shows 1366K).

Where the cards are and how the shelf moves is `shop_grid.py`; what the filter
asks for is `shop_filter.py`; this module buys it.

购买顺序 = 商店内从左到右、同一列先上后下；每个道具每次买 1 个。已售罄跳过；
买之前先 OCR 余额和价签，买不起就跳过（更便宜的后面的仍会试）。商品多为月更，
但补货按周走，所以每个商店都每周跑一次（下周一 05:00）。
"""

import re

from module.base.button import Button
from module.base.timer import Timer
from module.coupon.text import read_text
from module.hazeworld.assets import (MALL_TAB_EXCHANGE, REWARD_POPUP,
                                     SHOP_DIALOG_CANCEL, SHOP_DIALOG_CONFIRM)
from module.hazeworld.hazeworld_ui import HazeworldUI
from module.hazeworld.page import page_mall
from module.hazeworld.schedule import next_week_refresh
from module.hazeworld.shop_filter import ShopFilter
from module.hazeworld.shop_grid import (SHOP_GOODS_AREA, SHOP_MAX_COLUMNS,
                                       SHOP_ROWS, ShopGrid)
from module.logger import logger
from module.ocr.ocr import Ocr

# The purchase dialog: its title 「是否购买...？」 sits here, whatever the item.
SHOP_DIALOG_TITLE = (470, 168, 900, 202)
# Its full extent, for the still-check before 确认: the dialog opens with a
# short animation and a press that lands inside it is eaten (measured: the
# confirm 0.2 s after the card press left the dialog open for good).
SHOP_DIALOG_AREA = (360, 150, 920, 540)
# How the price on the strip is read: dark digits on the white band.
SHOP_PRICE_LETTER = (60, 60, 60)
SHOP_PRICE_THRESHOLD = 200


class HazeworldShopBase(HazeworldUI, ShopGrid, ShopFilter):
    """
    Shared engine of the exchange sub shops. A subclass only names the shop:

    - `SHOP_TITLE`: how the shop is called in the log.
    - `TAB`: the sidebar entry of the shop, in its selected look.
    - `CONFIG_TASK`: task whose `Filter` / `Purchases` are the buy list.
    - `CURRENCY_AREA` / `CURRENCY_LETTER` / `CURRENCY_THRESHOLD` / `CURRENCY_UNITS`:
      where the balance of the price currency is drawn and whether the game
      abbreviates it (K / M), so a price is compared against the right number.
    """

    SHOP_TITLE = 'shop'
    TAB = None
    CONFIG_TASK = None
    CURRENCY_AREA = (890, 26, 968, 62)
    CURRENCY_LETTER = (255, 255, 255)
    CURRENCY_THRESHOLD = 170
    CURRENCY_UNITS = ()

    def shop_run(self):
        """
        Walk the shop once and buy what the filter asks for. The caller
        reschedules, so the same walk serves both sub shops.

        Pages:
            in: page_main
            out: page_main
        """
        logger.hr(self.SHOP_TITLE, level=1)
        self.shop_filter_init()

        self.ui_ensure(page_mall)
        self.shop_goto_tab()
        # The shelf keeps the scroll position it was left at: a run that ended
        # at the last column, or was interrupted mid way, would otherwise start
        # from there and buy nothing.
        self.shop_scroll_home()
        self.shop_sweep()
        self.ui_goto_main()

    def shop_delay(self):
        """Come back next Monday 05:00 - the shops restock weekly."""
        target = next_week_refresh()
        logger.attr('Shop next reset', str(target))
        self.config.task_delay(target=target)

    # ==================== money ====================

    @staticmethod
    def shop_read_text(image, area, letter, threshold):
        """OCR one short text - a number or a 售罄 banner - raw."""
        button = Button(area=area, color=(0, 0, 0), button=area, name='SHOP_TEXT')
        ocr = Ocr(button, lang='cnocr', letter=letter, threshold=threshold,
                  name='SHOP_TEXT')
        return str(ocr.ocr(image))

    @staticmethod
    def shop_parse_amount(text, units=()):
        """
        A balance the game may abbreviate: 1366K is 1366000.

        Args:
            text (str): OCR read of the balance.
            units (tuple): ((suffix, scale), ...) of the abbreviations in use.

        Returns:
            int | None: The balance, or None when no digit was read at all.
        """
        digits = re.sub(r'\D', '', text or '')
        if not digits:
            return None
        value = int(digits)
        for suffix, scale in units:
            if suffix.lower() in (text or '').lower():
                value *= scale
                break
        return value

    def shop_balance(self):
        """
        The balance of the currency this shop sells for; None when unreadable,
        so a broken read never blocks a purchase the user asked for.
        """
        text = self.shop_read_text(self.device.image, self.CURRENCY_AREA,
                                   self.CURRENCY_LETTER, self.CURRENCY_THRESHOLD)
        return self.shop_parse_amount(text, self.CURRENCY_UNITS)

    def shop_price(self, card):
        """The price on the white strip of a card; None when unreadable."""
        _, x1, x2, _name, _ = card
        y1, y2 = SHOP_ROWS[card[0]]['strip']
        area = (x1 + 4, y1 + 2, x2 - 4, y2 - 2)
        text = self.shop_read_text(self.device.image, area,
                                   SHOP_PRICE_LETTER, SHOP_PRICE_THRESHOLD)
        digits = re.sub(r'\D', '', text)
        return int(digits) if digits else None

    # ==================== navigation ====================

    def shop_goto_tab(self):
        """
        Open 兑换商店 and make sure this shop's sidebar entry is selected.

        Both levels are pressed until their selected look is on screen instead
        of assuming a default: the game lands on 精英商店 by itself today, but
        defaults move between versions, and every sub shop lives behind the
        same tab.
        """
        for check in (MALL_TAB_EXCHANGE, self.TAB):
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
                    self.device.click(check)  # alas-lint: allow - verified by appear(check) in this loop
        # The grid fades in after the tabs settle; the first profile on a
        # half-drawn frame finds nothing and would read as the list end.
        self.wait_until_settled(self.TAB, timeout=5)

    # ==================== buying ====================

    def shop_close_reward(self, timeout=6):
        """
        Wait for the "获得资源" popup of a purchase and close it, until it is
        really gone.

        The popup is drawn about half a second after the dialog goes away, so
        it has to be waited for. Tapping once right away closes nothing, and
        the popup then sits on screen eating every press and every drag: the
        shelf never moved, the sweep measured the same goods again and bought
        them a second time (measured 2026-11-04 on 后勤商店, 4 purchases for 2
        different items).

        The press that lands while the popup is still fading in is swallowed
        now and then, so it is repeated on a timer instead of every frame - a
        press per frame would go on landing after the popup has left, and the
        shop card underneath it opens the purchase dialog again.

        `handle_reward()` does the same thing for the other pages but presses
        on every call, which is why this waits with a plain appear instead.

        Returns:
            bool: If a popup was found and closed.
        """
        timer = Timer(timeout).start()
        press = Timer(1).start()
        clicked = False
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.appear(REWARD_POPUP, offset=(20, 20), similarity=0.9):
                clicked = True
                if press.reached():
                    press.reset()
                    logger.info('Purchase reward, touch to exit')
                    self.device.click(REWARD_POPUP)  # alas-lint: allow - the appear above just matched it
                continue
            if clicked:
                self.wait_until_still(SHOP_GOODS_AREA, timeout=2)
                return True
            if timer.reached():
                return False

    def shop_sweep(self):
        """
        Walk the list once, left to right, buying what the filter asks for:
        both cards of a column are bought before the next column is walked to.
        The sweep stops at the list end or at a purchase the game would not
        take.

        The walk can not simply advance one column after each stop. Every
        purchase resets the shelf to its first column (measured 2026-11-04:
        after each 确认 the goods were back at 296:原始核心结晶, while merely
        opening and cancelling the same dialog left them where they were), so
        the sweep counts the columns it has handled and walks that far from
        the start before every stop. Advancing one column instead bought the
        first column over and over - 40 purchases of the same two items.

        Once the walk clamps, the list's tail is on screen. Its first column
        is the one just bought, and the ones further right never reach the
        left edge at all (the clamp lands the goods off the column grid:
        measured at x 461 and 734 against a grid of 296 + 272 n), so the tail
        is bought where it lies, one walk back to the same view per column.

        There is no "have I seen these goods before" guard on purpose: the
        same item may sit in two neighbouring columns (Ⅲ型自选水晶 does), so
        titles can not tell a broken scroll from a real one.
        """
        bought = skipped = 0
        handled = 0
        while handled < SHOP_MAX_COLUMNS:
            reached = self.shop_walk_to(handled)
            columns = self.shop_columns(self.shop_cards())
            if not columns:
                logger.info('No card readable, the sweep is done')
                break
            logger.attr('Shop columns', ' '.join(
                f'{x}{"+" if top and bottom else "-"}' for x, top, bottom in columns))
            if reached < handled:
                logger.info('The shop list is at its end, buying the tail')
                for offset in range(1, len(columns)):
                    if offset > 1:
                        # The purchase reset the shelf; walk back to this view.
                        self.shop_walk_to(handled)
                        columns = self.shop_columns(self.shop_cards())
                        if offset >= len(columns):
                            break
                    results, stop = self.shop_buy_column(columns[offset])
                    bought += results.count('bought')
                    skipped += results.count('skipped')
                    if stop:
                        break
                break
            results, stop = self.shop_buy_column(columns[0])
            bought += results.count('bought')
            skipped += results.count('skipped')
            if stop:
                break
            handled += 1
        logger.attr('Shop sweep', f'bought {bought}, skipped {skipped}')

    def shop_buy_column(self, column):
        """
        Buy both cards of one column.

        Args:
            column (list): [x_left, top_card, bottom_card] of `shop_columns`.

        Returns:
            tuple: (results so far, stop) where the results are the strings of
            `shop_buy_card` seen in this column and `stop` says a purchase was
            refused, which ends the sweep.
        """
        results = []
        for card in column[1:]:
            if card is None:
                continue
            result = self.shop_buy_card(card)
            results.append(result)
            if result not in ('bought', 'skipped'):
                return results, True
        return results, False

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
        # The balance check comes before any press: a card the currency cannot
        # cover is skipped, and the sweep goes on to the cheaper cards behind
        # it instead of confirming into a rejection.
        price, balance = self.shop_price(card), self.shop_balance()
        if price is not None and balance is not None and balance < price:
            logger.info(f'Skip {name}: price {price} over balance {balance}')
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
                    logger.warning('The currency ran out, the sweep stops here')
                    self.device.click(SHOP_DIALOG_CANCEL)  # alas-lint: allow - closes the dialog just read
                    return 'insufficient'
                # The success popup is drawn about half a second after the
                # dialog goes away; tapping now closes nothing and leaves the
                # popup eating the next drag. Wait for it, then close it.
                self.shop_close_reward()
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
