"""Pages of resonance.

Every page is identified by a unique button, and `link()` records "click this
-> go there"; `UI.ui_goto()` then finds the shortest path from wherever the game
currently is.
"""

from module.resonance.assets import (
    DAILY_CHECK, DAILY_ENTRY, DAILY_HOME, MAIN_CHECK, OP_BACK, OP_DETAIL, OP_HUB, OP_TAB, OP_TEAM,
    EXCHANGE_HQ_TAB, EXCHANGE_HUB, PASS_ENTRY, PASS_REWARDS_SELECTED, PASS_TASKS_SELECTED,
    SHOP_ENTRY, SHOP_HQ, SHOP_HQ_TAB,
)
from module.ui.page import Page


# Page's registry is shared across games.
page_resonance_main = Page(MAIN_CHECK)
page_main = page_resonance_main
page_daily = Page(DAILY_CHECK)
page_resonance_operations = Page(OP_HUB)
page_resonance_operation_detail = Page(OP_DETAIL)
page_resonance_operation_team = Page(OP_TEAM)
page_resonance_pass = Page((PASS_REWARDS_SELECTED, PASS_TASKS_SELECTED))
page_resonance_shop = Page((SHOP_HQ, SHOP_HQ_TAB))
page_resonance_exchange = Page(EXCHANGE_HUB)

page_main.link(DAILY_ENTRY, page_daily)
page_daily.link(DAILY_HOME, page_main)
page_daily.link(OP_TAB, page_resonance_operations)
page_resonance_operations.link(DAILY_HOME, page_main)
page_resonance_operation_detail.link(OP_BACK, page_resonance_operations)
page_resonance_operation_team.link(OP_BACK, page_resonance_operation_detail)
page_main.link(PASS_ENTRY, page_resonance_pass)
page_resonance_pass.link(DAILY_HOME, page_main)
page_main.link(SHOP_ENTRY, page_resonance_shop)
page_resonance_shop.link(DAILY_HOME, page_main)
page_resonance_exchange.link(EXCHANGE_HQ_TAB, page_resonance_shop)
page_resonance_exchange.link(DAILY_HOME, page_main)
