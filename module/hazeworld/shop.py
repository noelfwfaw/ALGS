"""The exchange shop of the mall, 精英商店: 商城 → 兑换商店 → 精英商店.

进兑换商店时游戏默认就停在精英商店，但每一层仍要核对（版本会改默认页）。

The cards are bought with gold, shown un-abbreviated in the top bar, so the
balance check reads it as is. Everything else - the two-row grid, the OCR of
the titles, the filter, the purchase dialog - is the shared engine in
`shop_base.py`; this module only names the shop.

购买顺序 = 商店内从左到右、同一列先上后下；每个道具每次买 1 个。已售罄跳过；
买之前先 OCR 金币余额和价签，买不起就跳过（更便宜的后面的仍会试）。商品多为
月更，但精英演习券一类每周补货，所以本任务每周跑一次（下周一 05:00）。
"""

from module.hazeworld.assets import EXCHANGE_TAB_ELITE
from module.hazeworld.shop_base import HazeworldShopBase


class HazeworldShop(HazeworldShopBase):
    """商城 → 兑换商店 → 精英商店，每周一次。"""

    SHOP_TITLE = 'Elite shop'
    TAB = EXCHANGE_TAB_ELITE
    CONFIG_TASK = 'HazeworldShop'

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        self.shop_run()
        self.shop_delay()
