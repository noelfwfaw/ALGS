"""
Free gifts of the 尊享商店 (Trickcal).

Flow read off the exported frames (2026-11-11, `screenshots/trickcal/`):

    page_main  --bottom row, 2nd icon (161,637)-(229,695)-->  page_shop
    page_shop  水晶叶商店 tab (181,422)-(229,483)  -->  每日免费礼包  (top-left card)
    page_shop  每周礼包   tab (184,543)-(233,608)  -->  每周免费礼包
    page_shop  每月礼包   tab (317,543)-(373,609)  -->  每月免费礼包
    every card: free price chip (678,313)-(786,336)
        --tap-->  item detail 取消 (410,596)-(622,664) / 购买 (660,596)-(872,664)
        --tap 购买-->  獲得獎勵 panel  --tap the hint line-->  back to the grid
    already claimed this period: the same card, dimmed, stamped 「售罄」
        (652,200)-(742,286) - nothing to tap, the next tab gets its turn
    page_main  <--shared top-left arrow (24,17)-(66,63)--

The three tabs share one viewport, the free pack is always the top-left card, and
the three cards differ in their art. So **the card is the tab identity**: the tab
icons themselves look the same selected or not - they match on all three frames
(measured), so they are click targets only and never page checks. That also means
a tab switch has to be verified by waiting for the *card*, not by "I clicked the
tab": the grid refreshes asynchronously and a frame or two later still shows the
previous tab's cards (`水晶叶商店.png` was captured exactly like that - its first
row costs ¥6/¥30/¥68 while the tab label is already highlighted).

The two panels between the chip and the gift
--------------------------------------------

Tapping the 0-price chip does **not** claim anything: it opens the item detail - a
panel titled with the pack's name, one description line, the 0 price and two
buttons, 取消 and 购买 (real frames 2026-11-11 23:03 / 23:20). Pressing 购买 then
draws the 「獲得獎勵」 panel **over that same detail**, and tapping the reward
panel away closes both at once (user, 2026-11-11 23:20 - that is why this task
never closes the detail itself). Consequences:

1. **Both panels are one widget for all three packs.** The detail only changes
   its title and description line; 取消 and 购买 are the same art at the same
   position (both 1.000 on the daily frame, at most 0.185 on every other frame).
   The reward panel's header 「獲得獎勵」 is likewise one template
   (`REWARD_POPUP_GAIN`, 1.000 here, <=0.40 elsewhere). So the handlers live in
   `TrickcalUI` / `RewardPopup` and the three packs reuse them instead of each
   carrying a copy.
2. **The detail is opaque and covers the 「尊享商店」 title**, so with it open
   `page_shop` reads as unknown and every tap on a tab icon lands on the panel.
   Leaving it open and moving on - which is what this task used to do - is not
   "continuing", it is clicking blind. `ui_additional()` also cancels it, so an
   orphaned panel cannot deadlock `ui_goto()` later.
3. **A pack that is already taken this period is stamped 「售罄」** (real frame
   2026-11-11 23:26): the art stays but is dimmed under a black band and a gold
   stamp, the countdown line and 「可購買0/1」 stay, and - measured, this is the
   trap - **the 0-price chip still matches at its old position**. So the chip can
   never tell "not claimed" from "claimed", and the dimmed card no longer matches
   its own template either (rgb and luma both False). The stamp is the only
   positive check: `SHOP_SOLD_OUT`, 1.000 on that frame and <=0.186 elsewhere.
   Because the dimmed card fails, a sold-out pack would otherwise read as "this
   tab never loaded", which is the one hard failure below - so the stamp also
   serves as arrival evidence in `shop_goto_tab()`, held for a few frames
   because its position is the same on all three packs.
   The other repeat path is a pack that still looks normal but 购买 no longer
   produces the reward panel. There is no counter to read (「可購買 n/1」 and the
   0 are text, no OCR asset), so the reward panel is the receipt and a missing one
   is logged instead of retried.

Why the order is gated (user, 2026-11-11)
-----------------------------------------

The three packs are one chain, not three independent claims: same page, same
grid, and the next step's tab icon is only reachable once this step's panels are
closed. So a pack whose own **tab was never selected** does not pass the chain
on: the card is the tab identity, and if it never shows up, switching to the
next tab is a click into an unknown screen. That is the one hard failure; it is
reported through `TaskFailed`, with the next run delayed first so the scheduler
does not retry today's claim immediately (three failures in a row would take the
whole process down).

Everything else stays soft: a pack with no free chip, a detail that never opens,
a purchase with no reward panel - all logged, the detail cancelled if it is still
up, and the next pack still gets its turn.

Shared pieces, not re-developed: both popups are `handle_reward_popup()` /
`handle_buy_popup()`, and the way out is the shared `BACK` arrow, the same two
the friend and task tasks use.
"""

from module.exception import TaskFailed
from module.logger import logger
from module.trickcal.assets import (SHOP_BUY_CANCEL, SHOP_BUY_CONFIRM,
                                    SHOP_FREE_BUY, SHOP_FREE_DAILY,
                                    SHOP_FREE_MONTHLY, SHOP_FREE_WEEKLY,
                                    SHOP_SOLD_OUT, SHOP_TAB_DAILY,
                                    SHOP_TAB_MONTHLY, SHOP_TAB_WEEKLY)
from module.trickcal.page import page_main, page_shop
from module.trickcal.trickcal_ui import TrickcalUI

SHOP_OFFSET = (20, 20)
# 切 tab 之后等卡片出现。列表是异步刷新的，第一帧基本还是旧内容。
SHOP_TAB_TIMEOUT = 15
# 「售罄」印章三档位置相同，证明不了是哪一档：必须连着这么多帧都看到它才算到达，
# 否则刚点完 tab 的那一两帧旧画面（上一档的印章还挂着）会被读成"这一档也售罄"。
SHOP_SOLD_SETTLE = 3
# 点价格条之后等商品详情页。实测 0.3s 内出来，8 秒是防网络卡。
SHOP_DETAIL_TIMEOUT = 8
# 按下「购买」之后等「獲得獎勵」面板（实测很快），8 秒是防网络卡。
SHOP_CLAIM_TIMEOUT = 8
# 面板淡出的那一两帧谁都不匹配，所以要连着这么多帧都干净才判"关掉了"。
SHOP_CLEAN_SETTLE = 2
# 收尾：把还开着的详情页按「取消」关掉，5 秒够它淡出。
SHOP_CLOSE_TIMEOUT = 5

# 一档礼包的结果，只用来数这一轮领到几档。
SHOP_CLAIMED = 'claimed'
SHOP_SKIPPED = 'skipped'


class TrickcalShop(TrickcalUI):
    """
    Claim the free gift of the daily / weekly / monthly shop tab.

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
            TaskFailed: If a pack's own tab was never selected. The next run is
                delayed first, so the scheduler does not retry today's claim
                right away (three failures in a row would take the whole
                process down).
        """
        self.ui_ensure(page_main)
        success, reason = self.shop_free_gifts()
        # 先排下一次再报错：不排的话调度器会立刻重跑同一个任务，
        # 三次之后直接 exit(1)（alas.py 的三振），而这一天本来就领不到了。
        self.config.task_delay(server_update=True)
        if not success:
            raise TaskFailed(reason)

    def shop_free_gifts(self):
        """
        Three packs, one free gift each, in the order the user asked for.

        Pages:
            in: page_main
            out: page_main

        Returns:
            (bool, str): Whether every pack's tab could be entered, and the
            reason when one could not.
        """
        logger.hr('Shop free gifts', level=2)
        self.ui_ensure(page_shop)
        claimed = 0
        # 进商店默认停在哪个 tab 不确定（截图里有过渡帧停在别的列表），所以三个
        # tab 都要显式切，切没切到看卡片，不看 tab 高亮。
        for tab, card, name in (
            (SHOP_TAB_DAILY, SHOP_FREE_DAILY, '每日免费礼包'),
            (SHOP_TAB_WEEKLY, SHOP_FREE_WEEKLY, '每周免费礼包'),
            (SHOP_TAB_MONTHLY, SHOP_FREE_MONTHLY, '每月免费礼包'),
        ):
            # 这一档的页签没进去就停在这里：卡片是页签身份，它一直没出现说明画面
            # 根本没切过来，继续点下一档只是盲点（用户 2026-11-11 要求）。
            if not self.shop_goto_tab(tab, card):
                self.shop_leave()
                logger.error(f'[Shop claimed] {claimed}/3')
                return False, f'{name} 没选中（「{card.name}」一直没出现），周/月方案未执行'
            if self.shop_claim_free(card, name) == SHOP_CLAIMED:
                claimed += 1
        self.ui_goto_main()
        logger.info(f'[Shop claimed] {claimed}/3')
        return True, ''

    def shop_goto_tab(self, tab, card):
        """
        Switch to one tab and wait until its free pack card is really there.

        Pages:
            in: page_shop
            out: page_shop

        Args:
            tab (Button): The tab icon of that section.
            card (Button): The free pack card that only that tab shows.

        Returns:
            bool: True when the card is on screen.
        """
        sold = 0
        for _ in self.loop(timeout=SHOP_TAB_TIMEOUT):
            if self.appear(card, offset=SHOP_OFFSET):
                return True
            # 本周期已经领过的那一档画着「售罄」：卡片被压暗，卡片素材当场失配
            # （真机 23:26 实测 rgb / luma 都是 False）。印章是唯一的到达证据，
            # 但它三档位置相同，所以要连着 SHOP_SOLD_SETTLE 帧都看到才认。
            if self.shop_sold_out():
                sold += 1
                if sold >= SHOP_SOLD_SETTLE:
                    logger.info(f'{card.name} is sold out, stay on this tab')
                    return True
            else:
                sold = 0
            # tab 图标每帧都在屏上（三个 tab 的图标互不遮挡），先确认再点；
            # 目标没出现就继续点 —— 点一下没反应是常态，不是失败（153）。
            if self.appear(tab, offset=SHOP_OFFSET):
                logger.info(f'Switch to {tab.name}')
                self.device.click(tab)
        logger.warning(f'{card.name} never showed up')
        return False

    def shop_sold_out(self):
        """
        Whether the free pack in the top-left slot is stamped 「售罄」.

        This is the honest "already claimed this period" check (real frame
        2026-11-11 23:26): the claimed pack keeps its art but is dimmed and
        stamped, so `SHOP_FREE_DAILY` stops matching while **`SHOP_FREE_BUY` (the
        0-price chip) keeps matching at the same place** - the chip alone can
        never tell "not claimed" from "claimed". The stamp is 1.000 on that frame
        and at most 0.186 on every other frame of this game.

        Returns:
            bool: True if the stamp is on screen.
        """
        return self.appear(SHOP_SOLD_OUT, offset=SHOP_OFFSET)

    def shop_claim_free(self, card, name):
        """
        One pack: price chip -> item detail -> 购买 -> 「獲得獎勵」 panel.

        Pages:
            in: page_shop
            out: page_shop

        Args:
            card (Button): The free pack card of this tab.
            name (str): Chinese name of the pack, for the log.

        Returns:
            str: `SHOP_CLAIMED` when the reward panel was tapped away,
            `SHOP_SKIPPED` when there was nothing to claim this period.
        """
        # 节流计时器是按按钮名全局存的，会跨档生效：上一档点过的按钮在这一档的
        # 头两秒里重试全被吃掉，一次都点不出去（离线回放暴露过）。每档重新开窗口。
        self.interval_clear((SHOP_FREE_BUY, SHOP_BUY_CONFIRM))
        if self.shop_sold_out():
            # 「售罄」是本周期已经领过的正面判据，先于卡片/价格条：卡片被压暗
            # 已经不匹配，而 0 价价格条**仍然匹配**（真机 23:26），靠价格条判"已领"
            # 会把售罄的礼包再买一次。
            logger.info(f'{name}: sold out, claimed this period')
            return SHOP_SKIPPED
        card_ok = self.appear(card, offset=SHOP_OFFSET)
        chip_ok = self.appear(SHOP_FREE_BUY, offset=SHOP_OFFSET)
        if not (card_ok and chip_ok):
            # 卡片和价格条都不在（刚进商店的过渡帧就是这种画面）：没有可点的东西。
            logger.info(f'{name}: card={card_ok}, free price chip={chip_ok}, skip')
            return SHOP_SKIPPED
        logger.info(f'Claim {name}')
        if not self.shop_open_detail(name):
            # 价格条点了、详情页没弹：可能这一档今天已经领过，客户端不再给详情页。
            # 没有面板挡着，下一档照常走（"没弹窗"不是"没点中"，153）。
            logger.warning(f'{name}: no item detail, already taken this period')
            return SHOP_SKIPPED
        if not self.shop_wait_reward(name):
            # 没有奖励面板就没有回执。详情页还开着的话先取消掉：它是整屏的，
            # 留着会把下一档切页签的点击全部吃掉。
            self.shop_close_detail()
            logger.warning(f'{name}: 购买 pressed but no reward panel, treat as claimed before')
            return SHOP_SKIPPED
        # 收尾兜底：万一还有一次点击穿透到列表上，打开了别的礼包的详情页，关掉它。
        # 只取消、绝不购买，这一档的账已经结了。
        if self.buy_popup_appear():
            logger.warning(f'{name}: a stray tap opened another pack, cancel it')
            self.shop_close_detail()
        return SHOP_CLAIMED

    def shop_open_detail(self, name):
        """
        Tap the 0-price chip until the item detail shows up.

        The chip is re-tapped every 2s while it is still on screen: a tap aimed
        at a card that is still animating is swallowed (153), and the panel is
        the only proof that this pack was really opened.

        Pages:
            in: page_shop
            out: page_shop (with the item detail up)

        Args:
            name (str): Chinese name of the pack, for the log.

        Returns:
            bool: True when the item detail is on screen.
        """
        for _ in self.loop(timeout=SHOP_DETAIL_TIMEOUT):
            if self.buy_popup_appear():
                logger.info(f'{name}: item detail opened')
                return True
            if self.appear(SHOP_FREE_BUY, offset=SHOP_OFFSET, interval=2):
                self.device.click(SHOP_FREE_BUY)  # alas-lint: allow - 上一条 appear() 就是这一帧的判据
        logger.warning(f'{name}: the price chip was tapped but no item detail showed up')
        return False

    def shop_wait_reward(self, name, timeout=None):
        """
        Press 购买, then tap the 「獲得獎勵」 panel away.

        Closing that panel closes the item detail under it as well (user,
        2026-11-11 23:20), so this loop owns the whole post-click stretch: press
        购买 while the detail is up, stop pressing the moment the reward panel
        appears (a second 购买 must never be sent through it), tap the panel, and
        return once the grid is clean again.

        One implementation for daily / weekly / monthly: the detail and the
        reward panel are the same widgets for all three packs, only the titles
        change.

        Pages:
            in: page_shop (with the item detail up)
            out: page_shop

        Args:
            name (str): Chinese name of the pack, for the log.
            timeout (int): Upper bound owned by this loop, `SHOP_CLAIM_TIMEOUT`
                by default. Read at call time, not as a default argument: a
                default snapshots the constant at import and silently ignores
                both a later patch and a config change (the offline replay
                shortens it, and used to be ignored).

        Returns:
            bool: True if the reward panel showed up and was tapped away.
        """
        if timeout is None:
            timeout = SHOP_CLAIM_TIMEOUT
        pressed = False
        reward_seen = False
        clean = 0
        for _ in self.loop(timeout=timeout):
            # 奖励面板在详情页上面：它一出现就只点它，不再按购买。
            # ❗一次点击 + 等它真的淡出，绝不连点：面板淡出的那一两帧点击会穿透到
            # 下面的商品列表，点到别的礼包、甚至点到它 300 的价格条（用户 23:44）。
            if self.reward_popup_appear() is not None:
                reward_seen = True
                clean = 0
                self.dismiss_reward_popup(settle=SHOP_CLEAN_SETTLE)
                continue
            if self.buy_popup_appear():
                # 按一下没反应是常态（153），节流在 handle_buy_popup() 里。
                pressed = self.handle_buy_popup(confirm=True) or pressed
                clean = 0
                continue
            clean += 1
            # 面板淡出的那一两帧谁都不匹配。真机 23:34 就是拿单帧"不匹配"提前判了关闭，
            # 面板其实还挂着，后面切页签的点击全被它吃掉 —— 所以要连着干净几帧才算关了。
            if reward_seen and clean >= SHOP_CLEAN_SETTLE:
                logger.info(f'{name} claimed, reward panel closed')
                return True
        if reward_seen:
            logger.warning(f'{name}: reward panel would not close, one more try')
            self.dismiss_reward_popup()
            if self.reward_popup_appear() is None:
                logger.info(f'{name} claimed, reward panel closed late')
                return True
            logger.error(f'{name}: reward panel is still up, stop this pack')
            return False
        logger.warning(f'{name}: 购买 pressed={pressed}, no reward panel')
        return False

    def shop_close_detail(self, timeout=None):
        """
        Cancel the item detail if it is still open - never buy it.

        Pages:
            in: page_shop / item detail
            out: page_shop

        Args:
            timeout (int): Upper bound owned by this loop, `SHOP_CLOSE_TIMEOUT`
                by default, read at call time for the same reason as
                `shop_wait_reward()`.

        Returns:
            bool: True if no detail is on screen when this returns.
        """
        if timeout is None:
            timeout = SHOP_CLOSE_TIMEOUT
        # 取消也可能刚从别的路径按过（`ui_additional()`），重开窗口再关。
        self.interval_clear(SHOP_BUY_CANCEL)
        for _ in self.loop(timeout=timeout):
            if not self.buy_popup_appear():
                return True
            logger.info('Cancel the item detail')
            self.handle_buy_popup(confirm=False)
        return False

    def shop_leave(self):
        """
        Close whatever is left open and go back to the lobby.

        The item detail hides the 「尊享商店」 title, so with it up
        `ui_goto_main()` has no page to start from and would wait for a page it
        can never recognise (151).

        Pages:
            in: page_shop / item detail
            out: page_main
        """
        self.shop_close_detail()
        self.ui_goto_main()
