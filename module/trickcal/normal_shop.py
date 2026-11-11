"""
Bulk purchase of the 普通商店 (Trickcal).

This is **not** the 尊享商店 (`shop.py`): different lobby icon, different page,
different job. The 尊享商店 hands out one free gift per period; the 普通商店
sells six items for gold and has 全选 + 一键购买 to take them all at once.

Flow read off the real frames (2026-11-12, `dev_tools/samples/trickcal_normal_shop/`):

    page_main  --bottom row 「商店」 (301,641)-(375,694)-->  page_normal_shop
    page_normal_shop  左侧「日常商店」橙色高亮 (0,106)-(180,154)
                      底部「全选 关/开」 (983,660)-(1078,690)
                      底部「一键购买」  (1125,656)-(1238,693)
    --一键购买-->  商品详情弹窗 (取消 / 购买，与尊享商店同一对素材)
    --购买-->      「獲得獎勵」弹窗 (REWARD_POPUP_GAIN)，点掉它两个弹窗一起关
    page_main  <--shared top-left arrow--

Three things are not what they look like:

1. **The 全选 pill cannot be read as a whole.** 「全选 关」 and 「全选 开」 are the
   same purple pill with one different character: measured 1.000 vs 0.974 on the
   off frame and 0.970 vs 0.999 on the on frame, so a template match on the pill
   cannot separate the states. Only the character itself separates them (1.000
   against 0.806~0.824), which is why `NORMAL_SHOP_SELECT_OFF` / `..._ON` are cut
   from (1038,658)-(1082,698) instead of using the exported pill.

2. **The page has seven tabs and they all share one title.** 日常商店 / 杂货商店 /
   战斗宝石商店 / 证书商店 / 推荐商店 / 边境商店 / 最佳女主角奖商店 - same page,
   same 全选 and 一键购买, different currency. The tab is therefore never the
   page check; it is a separate gate (`NORMAL_SHOP_TAB_DAILY`, the orange
   highlight) because this task buys **only** 日常商店 (user, 2026-11-12). A task
   that opened on another tab must not press 一键购买 - it would spend a
   different currency.

3. **一键购买 opens the same purchase dialog as the free packs of the 尊享商店**
   (user, 2026-11-12), so `handle_buy_popup()` is reused as-is. What comes after
   confirming is **not** the 「獲得獎勵」 panel: the measured run (2026-11-12 01:06)
   spent 179,000 gold and no reward panel ever matched in 30 seconds. The receipt
   is the green 「已購買」 stamp drawn over every card (1.000 on the bought frame,
   <=0.187 on every other frame) - that is the exit condition, and a reward panel
   is only dismissed when it happens to show up.

The purchase is not idempotent in the "costs nothing" sense: it spends gold. It
is idempotent in the "nothing left to buy" sense: a bought card is stamped and
cannot be bought again, so the stamp is checked **before** anything is pressed -
a second run of the same day returns immediately and spends nothing.
"""

from module.exception import TaskFailed
from module.logger import logger
from module.trickcal.assets import (NORMAL_SHOP_BUY_ALL, NORMAL_SHOP_SELECT,
                                    NORMAL_SHOP_SELECT_OFF, NORMAL_SHOP_SELECT_ON,
                                    NORMAL_SHOP_SOLD, NORMAL_SHOP_TAB_DAILY,
                                    NORMAL_SHOP_TITLE)
from module.trickcal.page import page_main, page_normal_shop
from module.trickcal.trickcal_ui import TrickcalUI

NORMAL_SHOP_OFFSET = (20, 20)
# 全选两态只差一个字，交叉分 0.81~0.82，自身 1.000：阈值取 0.90 两边都留余量。
NORMAL_SHOP_LABEL_SIMILARITY = 0.90
# 点 tab / 点全选之后等它生效。实测一次点击 1 秒内出结果。
NORMAL_SHOP_TOGGLE_TIMEOUT = 8
# 一键购买之后：详情弹窗 + 购买 + 奖励弹窗 + 页面回稳。6 件商品实测很快，
# 30 秒是防网络卡，不是常规等待。
NORMAL_SHOP_BUY_TIMEOUT = 30
# 弹窗淡出的那一两帧谁都不匹配，连着干净几帧才算真的关了（shop.py 踩过）。
NORMAL_SHOP_CLEAN_SETTLE = 2
# 按一下没反应是常态（153），2 秒重试一次。
NORMAL_SHOP_INTERVAL = 2


class TrickcalNormalShop(TrickcalUI):
    """
    Buy every item of the 日常商店 tab with 全选 + 一键购买.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main

        Raises:
            TaskFailed: If the 日常商店 tab could not be reached, or the purchase
                could not be confirmed. The next run is delayed first, so the
                scheduler does not retry the purchase right away.
        """
        self.ui_ensure(page_main)
        success, reason = self.normal_shop_buy()
        self.config.task_delay(server_update=True)
        if not success:
            raise TaskFailed(reason)

    def normal_shop_buy(self):
        """
        Walk into the normal shop, select everything, buy it, come back.

        Pages:
            in: page_main
            out: page_main

        Returns:
            (bool, str): Whether the purchase went through, and why it did not.
        """
        logger.hr('Normal shop', level=2)
        self.ui_ensure(page_normal_shop)
        if not self.normal_shop_daily_tab():
            self.ui_goto_main()
            return False, '没能停到「日常商店」，其他 tab 花的是别的货币，未购买'
        if self.normal_shop_sold():
            # 本周期已经买过：印章在，再点一次只会得到"没有可买的东西"。
            logger.info('「已购买」stamp is up, this tab is already bought')
            self.ui_goto_main()
            return True, ''
        if not self.normal_shop_select_all():
            self.ui_goto_main()
            return False, '「全选」没能切到开，未购买'
        if not self.normal_shop_purchase():
            self.ui_goto_main()
            return False, '一键购买没有出现「已购买」印章，见日志'
        self.ui_goto_main()
        return True, ''

    def normal_shop_sold(self):
        """
        Whether the first card of this tab is stamped 「已購買」.

        This is the receipt of the bulk purchase. The reward panel that a single
        pack of the 尊享商店 leaves behind does **not** show up here (real run
        2026-11-12 01:06: the gold was spent and no panel ever matched in 30s),
        so the stamp is the only positive proof. It scores 1.000 on the bought
        frame and at most 0.187 on every other frame of this game, and it stays
        on the card until the shop refreshes.

        Only the first card is checked: 一键购买 with 全选 takes the whole grid,
        so one stamp means the tab is done. A half-bought grid (the user took a
        single item by hand) still passes this gate and simply buys the rest.

        Returns:
            bool: True if the stamp is on screen.
        """
        return self.appear(NORMAL_SHOP_SOLD, offset=NORMAL_SHOP_OFFSET)

    def normal_shop_daily_tab(self):
        """
        Make sure the page is showing the 日常商店 tab.

        The orange highlight only exists while that tab is active, so it doubles
        as the gate and as the arrival check. The click goes to the same box: the
        tab sits at the same place in both states and the page check already
        passed, so this is a checked click, not a blind one.

        Returns:
            bool: True if 日常商店 is the active tab.
        """
        if self.appear(NORMAL_SHOP_TAB_DAILY, offset=NORMAL_SHOP_OFFSET):
            logger.info('Already on 日常商店')
            return True
        # 只有确认在普通商店页、且日常 tab 没高亮时才点，不点未知画面。
        # 正向写法：先确认页面，再在同一个分支里点击（过渡帧不满足就不点）。
        if self.appear(NORMAL_SHOP_TITLE, offset=NORMAL_SHOP_OFFSET):
            logger.info('Switch to 日常商店')
            self.device.click(NORMAL_SHOP_TAB_DAILY)  # alas-lint: allow - 上一条 appear() 就是这一帧的判据
            return self.wait_until_appear(NORMAL_SHOP_TAB_DAILY, offset=NORMAL_SHOP_OFFSET,
                                         timeout=NORMAL_SHOP_TOGGLE_TIMEOUT)
        logger.warning('Not on the normal shop page, do not switch tabs')
        return False

    def normal_shop_select_state(self):
        """
        Read the 全选 state from the two character templates.

        Both are checked on the same frame: each one scores 1.000 in its own
        state and 0.806~0.824 in the other, so at 0.90 exactly one of them hits.

        Returns:
            bool or None: True when on (everything ticked), False when off, None
            when neither template is convincing.
        """
        on = self.appear(NORMAL_SHOP_SELECT_ON, offset=(4, 4),
                         similarity=NORMAL_SHOP_LABEL_SIMILARITY)
        off = self.appear(NORMAL_SHOP_SELECT_OFF, offset=(4, 4),
                          similarity=NORMAL_SHOP_LABEL_SIMILARITY)
        if on == off:
            return None
        return on

    def normal_shop_select_all(self):
        """
        Leave the 全选 pill in the on state, pressing it only when it is off.

        The pill is a toggle, so it is never pressed on a guess: the state is
        read from the two character templates first, and only an off (or an
        unreadable) state leads to a press.

        Returns:
            bool: True if 全选 is on.
        """
        for _ in self.loop(timeout=NORMAL_SHOP_TOGGLE_TIMEOUT * 2):
            state = self.normal_shop_select_state()
            if state:
                logger.info('「全选」is on')
                return True
            if self.appear(NORMAL_SHOP_TITLE, offset=NORMAL_SHOP_OFFSET):
                logger.info(f'「全选」state={state}, press it')
                self.device.click(NORMAL_SHOP_SELECT)  # alas-lint: allow - 上一条 appear() 就是这一帧的判据
        logger.warning('「全选」could not be turned on')
        return False

    def normal_shop_purchase(self):
        """
        一键购买 -> purchase dialog -> 购买 -> 「已購買」 stamp.

        The purchase dialog is the same one the free packs of the 尊享商店 open, so
        it is answered by `handle_buy_popup()`. A reward panel is handled too when
        one does appear, but it is **not** the exit condition: the measured run
        ended with the gold spent and no panel at all, so waiting for it turned a
        successful purchase into a failure. The exit condition is the stamp.

        Returns:
            bool: True if the 「已購買」 stamp came up.
        """
        pressed = False
        for _ in self.loop(timeout=NORMAL_SHOP_BUY_TIMEOUT):
            if self.normal_shop_sold():
                logger.info('「已購買」stamp appeared, purchase done')
                return True
            if self.reward_popup_appear() is not None:
                self.dismiss_reward_popup(settle=NORMAL_SHOP_CLEAN_SETTLE)
                continue
            if self.buy_popup_appear():
                pressed = self.handle_buy_popup(confirm=True) or pressed
                continue
            if not pressed and self.appear(NORMAL_SHOP_BUY_ALL, offset=NORMAL_SHOP_OFFSET,
                                           interval=NORMAL_SHOP_INTERVAL):
                logger.info('Press 一键购买')
                self.device.click(NORMAL_SHOP_BUY_ALL)  # alas-lint: allow - 上一条 appear() 就是这一帧的判据
                continue
        if self.normal_shop_sold():
            logger.info('「已購買」stamp appeared late, purchase done')
            return True
        logger.warning(f'一键购买 pressed={pressed}, no 「已購買」stamp')
        return False
