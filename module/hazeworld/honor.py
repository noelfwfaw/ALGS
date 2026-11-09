"""The 荣誉凭证 shop of the mall, 商城系统 → 荣誉凭证.

It is the fifth tab of the mall, a sibling of 兑换商店 rather than one of its
sub shops. The shelf, the price strips, the purchase dialog and the reward
popup are all the same as in those shops (two rows, cards 227 px wide on a
272 px pitch, price bands at y 389-423 and 643-677, measured 2026-11-04), so
the whole flow runs on the engine of `shop_base.py`. Only three things differ
and this module sets them:

- It is reached from the top tab bar, not from the exchange shop's sidebar,
  so `SHOP_PATH` has a single step.
- It is paid in 荣誉凭证, whose balance sits in the top bar right of the gold
  slot - the same slot the logistics shop reads, also abbreviated (2680K).
- It buys one card only: the first one, 定向调度券. The rest of the shelf is
  never touched, so there is no walking and no sweeping.

第一格永远在货架最左，而购买之后货架还会自己回到最左（v1.23.0 在相邻商店实测），
所以每一轮重新量一次货架、点同一个位置即可，不需要走位也不需要滚到底。
"""

from module.hazeworld.assets import MALL_TAB_HONOR
from module.hazeworld.shop_base import HazeworldShopBase
from module.logger import logger

# The balance of the 荣誉凭证 currency: the top bar slot right of the gold one,
# the same crop the logistics shop reads (measured 2680K there).
SHOP_HONOR_BALANCE = (1088, 26, 1200, 62)
# The game abbreviates the balance: 2680K is 2680000.
SHOP_HONOR_UNITS = (('K', 1000), ('M', 1000000))
# How many times one run may buy the first card. The card is limited to a
# couple per week (剩余 2 today); the cap only keeps a mis-read from looping.
SHOP_HONOR_MAX_BUY = 6


class HazeworldHonor(HazeworldShopBase):
    """商城系统 → 荣誉凭证，只买第一格的定向调度券，每周一次。"""

    SHOP_TITLE = 'Honor shop'
    SHOP_PATH = (MALL_TAB_HONOR,)
    # The grey unselected honour tab is the same drawing as the selected one,
    # so the shape match has to be confirmed by the area colour - without it
    # the task "arrives" on the mall home page and buys off the wrong shelf.
    SHOP_TAB_COLOR_CHECK = (MALL_TAB_HONOR,)
    CONFIG_TASK = 'HazeworldHonor'
    CURRENCY_AREA = SHOP_HONOR_BALANCE
    CURRENCY_UNITS = SHOP_HONOR_UNITS

    def shop_sweep(self):
        """
        Buy the first card of the shelf, again and again, until the game stops
        selling it - sold out, or the currency ran out.

        Nothing walks here: the first card is the leftmost one and a purchase
        resets the shelf there, so every round re-measures the shelf and taps
        the same spot. The filter still has the last word, so a week in which
        the game puts something else first is left alone instead of bought.
        The dialog is bought with 最大, so one round takes the whole stock.

        Returns:
            bool: If the sweep stopped because the card costs more than the
            balance, which makes the caller retry at the next server update.
        """
        bought = 0
        while bought < SHOP_HONOR_MAX_BUY:
            self.device.screenshot()
            columns = self.shop_columns(self.shop_cards())
            if not columns or columns[0][1] is None:
                logger.info('No card readable, the sweep is done')
                break
            result = self.shop_buy_card(columns[0][1])
            if result != 'bought':
                logger.attr('Shop sweep', f'bought {bought}')
                return result == 'insufficient'
            bought += 1
        logger.attr('Shop sweep', f'bought {bought}')
        return False

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        self.shop_run()
        self.shop_delay()
