from module.base.timer import Timer
from module.base.utils import get_color
from module.logger import logger
from module.lostsword.assets import (REWARD_POPUP_TITLE, SHOP_BTN_CLAIM_FREE,
                                     SHOP_DIALOG_CLOSE, SHOP_DIALOG_TITLE,
                                     SHOP_GIFT_DAILY, SHOP_GIFT_MONTHLY,
                                     SHOP_GIFT_WEEKLY, SHOP_TAB_DAILY,
                                     SHOP_TAB_GOODS, SHOP_TAB_MONTHLY,
                                     SHOP_TAB_WEEKLY)
from module.lostsword.lostsword_ui import LostswordUI, page_shop

"""
商店 (shop), the free gifts only.

Flow observed in game:

    page_main  --菜单-->  page_menu  --商店图标-->  page_shop（默认开在「推荐」）
    page_shop  --顶部「商品」-->  左侧出现 每日 / 每周 / 每月 三行
    page_shop  --第一张卡片-->  购买商品对话框  --底部「免费」-->  已获得道具。弹窗
    page_shop  --右上圆 X-->  page_main

Every one of the three tabs starts with a free gift card at the same place, so a
single routine serves all of them; only the tab has to be switched first.

Whether a gift is still available is read from the red badge at the right edge of
its tab, not from the card: a claimed card keeps its 「免费」 price row and only
gains a 售罄 band over the item art, while the badge disappears outright. The
badge also survives the tab being unselected, so the three tabs can be checked
without opening the purchase dialog first.

The purchase dialog is a trap of its own: a card whose gift is used up still
opens it, just with 「已购买过该商品。」 in place of the 「免费」 button. A run that
walks into that state has to close the dialog again, otherwise every later click
lands on a modal. That is why the dialog is a page of the page graph and is
matched by its title, which does not change, rather than by its button.

The reward popup is a full screen "tap to continue" handled by LostswordUI, and
the same tap also closes the purchase dialog underneath it, so the page has to be
re-ensured instead of assumed.
"""

# name, tab button, free gift card, red badge of the tab.
# The badges sit at the right edge of the tab rows: x 262~293, y 133 / 225 / 317,
# 92 pixels apart, the same offset as the rows themselves.
SHOP_TABS = (
    ('daily', SHOP_TAB_DAILY, SHOP_GIFT_DAILY, (262, 133, 293, 164)),
    ('weekly', SHOP_TAB_WEEKLY, SHOP_GIFT_WEEKLY, (262, 225, 293, 256)),
    ('monthly', SHOP_TAB_MONTHLY, SHOP_GIFT_MONTHLY, (262, 317, 293, 348)),
)

# The badge of this game is the same red circle everywhere (mail, shop, menu).
# A badge is about 400 pixels, so 100 detects one and still reads 0 when there is
# nothing left.
SHOP_BADGE_COLOR = (221, 86, 62)
SHOP_BADGE_PIXELS = 100

# The selected tab is drawn on a cream pill (mean 212~230), an idle one on the
# dark panel (mean 47~90). Any value in between is a transition frame.
SHOP_TAB_SELECTED_MEAN = 150


class LostswordShop(LostswordUI):
    """
    Claim the daily / weekly / monthly free gift of the shop.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        logger.hr('Shop free gifts', level=1)
        self.ui_ensure(page_shop)
        if not self.shop_goto_goods():
            # Re-enter once before giving up: leaving and coming back closes any
            # dialog the shop was left with (the graph routes through it), and
            # that is the only observed reason for the tab bar to stop reacting.
            logger.warning('Goods tab did not open, re-enter the shop')
            self.ui_goto_main()
            self.ui_ensure(page_shop)
            if not self.shop_goto_goods():
                # The other top tabs have no free gift, and their left column is
                # a different list whose first row sits exactly where 每日 sits.
                # Going on would click the first card of 促销, a paid one.
                logger.warning('Goods tab is unavailable, nothing claimed')
                self.ui_goto_main()
                self.config.task_delay(server_update=True)
                return

        claimed = 0
        for name, tab, card, badge in SHOP_TABS:
            # Dismissing the reward popup closes the purchase dialog with it, and
            # the shop page is the only thing guaranteed to be behind them.
            self.ui_ensure(page_shop)
            if not self.shop_select_tab(tab):
                logger.warning(f'{name} tab did not open, skipped')
                continue
            if not self.shop_tab_unclaimed(badge):
                logger.info(f'{name}: no free gift left')
                continue
            logger.info(f'Claim the {name} free gift')
            claimed += self.shop_claim_card(card)

        logger.info(f'Free gifts claimed: {claimed}')
        self.ui_goto_main()
        # The game day turns over at 00:00 and `Scheduler.ServerUpdate` of this
        # task is pinned to it (see argument/override.yaml), so one pass a day is
        # enough: the weekly and monthly gift are caught by the same pass on the
        # morning they refresh.
        self.config.task_delay(server_update=True)

    def shop_goto_goods(self, timeout=10):
        """
        Open the 「商品」 tab, the only one that has the free gifts.

        The shop remembers the tab it was left on, so this also runs when the
        tab is already open; clicking the open tab does not change anything.

        Pages:
            in: page_shop
            out: page_shop

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If the tab is open.
        """
        self.device.click(SHOP_TAB_GOODS)
        timeout = Timer(timeout).start()
        retry = Timer(1.5, count=3).start()
        while 1:
            self.device.screenshot()
            if self.shop_tab_selected(SHOP_TAB_GOODS):
                return True
            # A click can be eaten by the panel sliding in, and the tab bar does
            # not lock input afterwards, so a plain retry is safe.
            if retry.reached():
                retry.reset()
                self.device.click(SHOP_TAB_GOODS)
            if timeout.reached():
                logger.warning('Cannot open the goods tab')
                return False

    def shop_select_tab(self, tab, timeout=8):
        """
        Switch the left column to one of 每日 / 每周 / 每月.

        Pages:
            in: page_shop
            out: page_shop

        Args:
            tab (Button): Tab to open.
            timeout (int, float): Seconds.

        Returns:
            bool: If the tab is open.
        """
        self.device.click(tab)
        timeout = Timer(timeout).start()
        retry = Timer(1.5, count=3).start()
        while 1:
            self.device.screenshot()
            if self.shop_tab_selected(tab):
                return True
            if retry.reached():
                retry.reset()
                self.device.click(tab)
            if timeout.reached():
                logger.warning(f'{tab.name} did not open')
                return False

    def shop_tab_selected(self, tab):
        """
        Whether a tab is the opened one.

        The tab is drawn on a cream pill when selected and on the dark panel
        otherwise, so the mean brightness of its area tells the two apart. The
        template itself matches in both states, a colour would not survive the
        sliding highlight, but the brightness step is 4x.

        Args:
            tab (Button): Tab to check, on the current screenshot.

        Returns:
            bool: If the tab is the selected one.
        """
        color = get_color(self.device.image, tab.area)
        return sum(color) / 3 > SHOP_TAB_SELECTED_MEAN

    def shop_tab_unclaimed(self, badge):
        """
        Whether a tab still holds an unclaimed free gift.

        Args:
            badge (tuple): Area of the red badge at the right edge of the tab.

        Returns:
            bool: If the badge is there.
        """
        return self.image_color_count(badge, color=SHOP_BADGE_COLOR,
                                      threshold=30, count=SHOP_BADGE_PIXELS)

    def shop_claim_card(self, card, timeout=6):
        """
        Open the purchase dialog of a card and take its free gift.

        Pages:
            in: page_shop
            out: page_shop

        Args:
            card (Button): The free gift card.
            timeout (int, float): Seconds to wait for each dialog.

        Returns:
            int: 1 if a reward popup was claimed, else 0.
        """
        self.device.click(card)
        # The dialog is identified by its title, not by its confirm button: the
        # button is the one thing that changes when the purchase limit is used
        # up (it turns into 「已购买过该商品。」), and that is exactly the state
        # this routine has to be able to leave again.
        if not self.wait_overlay(SHOP_DIALOG_TITLE, timeout=timeout):
            logger.warning('Purchase dialog did not open')
            return 0

        if self.appear(SHOP_BTN_CLAIM_FREE, offset=30):
            self.device.click(SHOP_BTN_CLAIM_FREE)
            if self.wait_overlay(REWARD_POPUP_TITLE, timeout=timeout):
                self.handle_reward_popup()
                return 1
            logger.warning('No reward popup after confirming')
            self.shop_close_dialog()
            return 0

        logger.info('Free gift already bought, close the dialog')
        self.shop_close_dialog()
        return 0

    def shop_close_dialog(self):
        """
        Close the "购买商品" dialog.

        Pages:
            in: page_shop_dialog
            out: page_shop

        Returns:
            bool: If the dialog left.
        """
        if self.appear(SHOP_DIALOG_CLOSE, offset=30):
            self.device.click(SHOP_DIALOG_CLOSE)
            return self.wait_overlay_gone(SHOP_DIALOG_TITLE, timeout=5)
        return False
