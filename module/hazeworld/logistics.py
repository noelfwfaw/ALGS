"""The exchange shop of the mall, 后勤商店: 商城 → 兑换商店 → 后勤商店.

后勤商店是兑换商店左侧栏的第三个入口，货架、购买弹窗、拖动行为和精英商店
完全一样，所以整条流程走 `shop_base.py` 的同一套引擎，这里只说明它与精英
商店不同的三处：

- 它的价格不是金币，而是后勤补给通货；余额显示在顶栏最右（金币那一格没有
  数字），游戏把大数字缩写，`1366K` 就是 1366000，所以要按后缀还原。
- 清单默认全买，只排除盾币：盾币是 1 点换无限量的兑换券，买它没意义。
- 补货按周走（面板上写「N日后重置购买次数」），所以每周一 05:00 跑一次。

Prices are read off the same white strip as in the elite shop; the card grid,
the OCR and the filter are the shared engine.
"""

from module.hazeworld.assets import EXCHANGE_TAB_LOGISTICS
from module.hazeworld.shop_base import HazeworldShopBase

# The balance of the logistics currency, in the top bar right of the gold slot.
# The narrow crop is the one that reads: a wider one also takes the dark plate
# behind it and the OCR then loses the digits (measured 1366K against
# 1366K / is66 / i3k for the wider crops).
SHOP_LOGISTICS_BALANCE = (1088, 26, 1200, 62)
# The game abbreviates: 1366K = 1366000.
SHOP_LOGISTICS_UNITS = (('K', 1000), ('M', 1000000))


class HazeworldLogistics(HazeworldShopBase):
    """商城 → 兑换商店 → 后勤商店，每周一次。"""

    SHOP_TITLE = 'Logistics shop'
    TAB = EXCHANGE_TAB_LOGISTICS
    CONFIG_TASK = 'HazeworldLogistics'
    CURRENCY_AREA = SHOP_LOGISTICS_BALANCE
    CURRENCY_UNITS = SHOP_LOGISTICS_UNITS

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        self.shop_run()
        self.shop_delay()
