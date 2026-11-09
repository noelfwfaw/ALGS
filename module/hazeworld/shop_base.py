"""The engine behind the shops of 商城 (商城系统 → 兑换商店 / 荣誉凭证).

The shops of the mall are all the same screen with a different tab and sidebar
entry selected: 精英商店 and 后勤商店 behind 兑换商店, and 荣誉凭证 one tab to
their right. They all show a two-row grid that scrolls sideways and they all
sell through the same purchase dialog. Only these things differ between them,
and that is exactly what a subclass sets:

- `SHOP_PATH`: the tabs to press to reach the shop, outermost first.
- `CONFIG_TASK`: the task whose `Filter` / `Purchases` settings are read.
- `CURRENCY_*`: where the balance of the currency the prices are paid in sits
  in the top bar, and whether the game abbreviates it (后勤商店 shows 1366K).

Where the cards are and how the shelf moves is `shop_grid.py`; what the filter
asks for is `shop_filter.py`; this module buys it.

购买顺序 = 购买清单从上往下，先买高优先级的；每张卡在弹窗里点 MAX，一次把货架
余量和余额允许的数量全部买下；余额不够买下一张想要的卡时停手，第二天 05:00 再来
（货币每天都会涨），不再傻等一周。商品多为月更，但补货按周走，所以清单买完时
每周跑一次（下周一 05:00）。
"""

import re

from module.base.button import Button
from module.base.timer import Timer
from module.coupon.text import read_text
from module.hazeworld.assets import (REWARD_POPUP, SHOP_DIALOG_CANCEL,
                                     SHOP_DIALOG_CONFIRM, SHOP_DIALOG_MAX)
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
    Shared engine of the mall shops. A subclass only names the shop:

    - `SHOP_TITLE`: how the shop is called in the log.
    - `SHOP_PATH`: the tabs that lead to the shop, outermost first, each as its
      selected look. 兑换商店 opens on 精英商店 by itself today, but the default
      moves between versions, so the sidebar entry is pressed too whenever the
      path has one.
    - `CONFIG_TASK`: task whose `Filter` / `Purchases` are the buy list.
    - `CURRENCY_AREA` / `CURRENCY_LETTER` / `CURRENCY_THRESHOLD` / `CURRENCY_UNITS`:
      where the balance of the price currency is drawn and whether the game
      abbreviates it (K / M), so a price is compared against the right number.
    """

    SHOP_TITLE = 'shop'
    SHOP_PATH = ()
    # Tabs of `SHOP_PATH` whose selected look is the same drawing as the grey
    # unselected one, so a shape match can not tell them apart and the area
    # colour has to agree too. 荣誉凭证 is one: on the mall home page its grey
    # tab scores 1.000 against the selected template (measured 2026-11-04).
    # Leaving the other tabs out keeps them working through the open animation,
    # which moves their average colour around by 15.
    SHOP_TAB_COLOR_CHECK = ()
    CONFIG_TASK = None
    CURRENCY_AREA = (890, 26, 968, 62)
    CURRENCY_LETTER = (255, 255, 255)
    CURRENCY_THRESHOLD = 170
    CURRENCY_UNITS = ()
    # Set by `shop_run()`: the sweep stopped because the next wanted card costs
    # more than the balance, so the next run is tomorrow rather than next week.
    shop_out_of_money = False

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
        self.shop_out_of_money = bool(self.shop_sweep())
        self.ui_goto_main()

    def shop_delay(self):
        """Come back next Monday 05:00 - the shops restock weekly."""
        if self.shop_out_of_money:
            # The currency keeps growing every day, so a short balance is a
            # reason to come back tomorrow, not to idle for a whole week.
            logger.info('The next wanted card costs more than the balance, '
                        'retry at the next server update')
            self.config.task_delay(server_update=True)
            return
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

    def shop_tab_selected(self, tab):
        """
        Whether `tab` is on screen in its selected look.

        A shape match alone is not enough for every tab: `appear` with an
        offset compares the drawing only, so the grey unselected honour tab
        scores 1.000 against its selected version (measured 2026-11-04 on the
        mall home page) and the shop would be "reached" without ever pressing
        it. Tabs listed in `SHOP_TAB_COLOR_CHECK` are therefore checked on
        their area colour as well.
        """
        if self.appear(tab, offset=(20, 20)):
            if tab.name not in [button.name for button in self.SHOP_TAB_COLOR_CHECK]:
                return True
            return tab.appear_on(self.device.image)
        return False

    def shop_goto_tab(self):
        """
        Open the mall and press every tab of `SHOP_PATH` in turn.

        Every level is pressed until its selected look is on screen instead of
        assuming a default: 兑换商店 lands on 精英商店 by itself today, but
        defaults move between versions, and every sub shop lives behind the
        same tab.
        """
        for check in self.SHOP_PATH:
            timeout = Timer(8).start()
            press_timer = Timer(2.5).start()
            pressed = 0
            while 1:
                self.device.stuck_record_clear()
                self.device.screenshot()
                if self.shop_tab_selected(check):
                    break
                if timeout.reached():
                    logger.warning(f'{check} did not become selected')
                    break
                if press_timer.reached() and pressed < 3:
                    press_timer.reset()
                    pressed += 1
                    # The press is retried until the check above holds.
                    self.device.click(check)  # alas-lint: allow - verified by shop_tab_selected in this loop
        # The grid fades in after the tabs settle; the first profile on a
        # half-drawn frame finds nothing and would read as the list end.
        self.wait_until_settled(self.SHOP_PATH[-1], timeout=5)

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
        Buy the wanted cards by priority, one card at a time, each in the
        largest quantity the game allows.

        The filter list is the priority: every line is bought out before the
        next one is touched, so a short balance still spends what there is on
        the thing that matters most (`shop_find()`).

        最大 pulls the quantity up to the stock and the balance (measured
        2026-11-09: 剩余 98 at 300 each with 73285 gold became 98 for 29400),
        so a card leaves the shelf in one purchase: either sold out, or the
        balance no longer covers a second one. Both end that card, so the loop
        always makes progress.

        The walk can not advance one column after each stop. Every purchase
        resets the shelf to its first column (measured 2026-11-04: after each
        确认 the goods were back at 296:原始核心结晶, while merely opening and
        cancelling the same dialog left them where they were), so every search
        walks from the start again.

        Returns:
            bool: If the sweep stopped because the next wanted card costs more
            than the balance. The caller then comes back at the next server
            update instead of next week.
        """
        bought = 0
        for rank in range(self.shop_rule_count):
            while 1:
                card = self.shop_find(rank)
                if card is None:
                    break
                # The balance check comes before any press: confirming a card
                # the currency cannot cover only opens a rejection dialog.
                price, balance = self.shop_price(card), self.shop_balance()
                if price is not None and balance is not None and balance < price:
                    logger.info(f'The card {card[3]} costs {price}, balance {balance}')
                    logger.attr('Shop sweep', f'bought {bought}')
                    return True
                if self.shop_buy_card(card) != 'bought':
                    logger.attr('Shop sweep', f'bought {bought}')
                    return False
                bought += 1
        logger.attr('Shop sweep', f'bought {bought}')
        return False

    def shop_find(self, rank):
        """
        Walk from the start of the shelf and return the first card of `rank`
        that still has something to sell.

        The card is returned with the shelf left at the view it was read from,
        so the caller can press it without walking again. A card of another
        priority is not bought here: the line above it has not been cleared.

        Args:
            rank (int): Line of the filter, 0 is the first.

        Returns:
            tuple or None: The card, or None when no card of this rank is left.
        """
        handled = 0
        while handled < SHOP_MAX_COLUMNS:
            reached = self.shop_walk_to(handled)
            columns = self.shop_columns(self.shop_cards())
            if not columns:
                logger.info('No card readable, the shop is done')
                return None
            logger.attr('Shop columns', ' '.join(
                f'{x}{"+" if top and bottom else "-"}' for x, top, bottom in columns))
            for column in columns:
                for card in column[1:]:
                    if card is None:
                        continue
                    if self.shop_filter_rank(card) != rank:
                        continue
                    if self.shop_sold_out(card):
                        logger.info(f'Skip {card[3]}: sold out')
                        continue
                    return card
            if reached < handled:
                # The tail is on screen with the walk clamped; `columns` above
                # already covers it (one walk back to the same view per
                # column), so the list has been read to its end.
                logger.info('The shop list is at its end')
                return None
            handled += 1
        return None

    def shop_sold_out(self, card):
        """
        Args:
            card (tuple): (row, x_left, x_right, name_a, name_b).

        Returns:
            bool: If the card carries the 售罄 banner.
        """
        row, x1, x2 = card[0], card[1], card[2]
        sy1, sy2 = SHOP_ROWS[row]['sold']
        sold = read_text(self.device.image, (x1 + 30, sy1, x2 - 30, sy2))
        return '售罄' in sold

    def shop_buy_card(self, card):
        """
        Buy one card in one purchase; 'bought', 'insufficient' or 'skipped'.

        The dialog's 最大 is pressed before 确认, so this buys the whole stock
        the currency covers instead of a single piece.
        """
        row, x1, x2, name, _ = card
        if not self.shop_filter_match(card):
            logger.info(f'Skip {name}: not on the filter')
            return 'skipped'
        if self.shop_sold_out(card):
            logger.info(f'Skip {name}: sold out')
            return 'skipped'
        # The balance check comes before any press: confirming a card the
        # currency cannot cover only opens a rejection dialog. The sweep has
        # already checked it once, this covers a balance that moved meanwhile.
        price, balance = self.shop_price(card), self.shop_balance()
        if price is not None and balance is not None and balance < price:
            logger.info(f'Skip {name}: price {price} over balance {balance}')
            return 'insufficient'

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

        # 最大 pulls the quantity up to the stock and the balance. The dialog
        # was stilled above, so this press is not eaten by its open animation.
        self.device.click(SHOP_DIALOG_MAX)  # alas-lint: allow - the dialog was just confirmed by its title OCR
        self.wait_until_still(SHOP_DIALOG_AREA, timeout=2)
        self.device.screenshot()

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
