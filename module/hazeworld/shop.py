"""The exchange shop of the mall, 精英商店: 商城 → 兑换商店 → 精英商店.

进兑换商店时游戏默认就停在精英商店，但每一层仍要核对（版本会改默认页）。

The cards are bought with gold, shown un-abbreviated in the top bar, so the
balance check reads it as is. Everything else - the two-row grid, the OCR of
the titles, the filter, the purchase dialog - is the shared engine in
`shop_base.py`; this module only names the shop.

购买顺序 = 购买清单从上往下，先买高优先级的；每张卡在弹窗里点 MAX，一次把余量和
余额允许的数量全部买下；余额不够买下一张想要的卡时停手，第二天 05:00 再来。商品
多为月更，但补货按周走，所以清单买完时每周跑一次（下周一 05:00）。
"""

from module.hazeworld.assets import EXCHANGE_TAB_ELITE, MALL_TAB_EXCHANGE
from module.hazeworld.shop_base import HazeworldShopBase


class HazeworldShop(HazeworldShopBase):
    """商城 → 兑换商店 → 精英商店，每周一次。"""

    SHOP_TITLE = 'Elite shop'
    SHOP_PATH = (MALL_TAB_EXCHANGE, EXCHANGE_TAB_ELITE)
    CONFIG_TASK = 'HazeworldShop'

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        self.shop_run()
        self.shop_delay()
