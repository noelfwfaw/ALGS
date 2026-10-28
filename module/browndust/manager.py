"""
经营管理领取 (Brown Dust II).

Flow measured on the real device (2026-10-28, screenshots in `screenshots/browndust/`):

    page_main  --左侧竖栏第 2 行那个「经营管理」图标-->  面板（盖在大厅上的弹窗）
    面板       底部「一键获得」-->  REWARD 结算页（「获得3种」+ 道具一排）
                                  --点底部空白-->  回到同一个面板
    面板       领完之后「一键获得」变灰、奖励数字归 0、倒计时从 0 重新开始
    面板       底部「取消」-->  page_main

面板现在有三块：Lv.1 餐馆营业额现状（可领）、Lv.0 渔笼收获情况（钓鱼船 2 级后
解锁）、助手工作情况（分派助手后解锁）。后两块是灰字说明，面板高度已经把三块
都装下了。

四件不是"看起来那样"的事，都是量的：

1. **「一键获得」把「结算」也一起结了**。领之前「结算」右上角有个红色「!」
   徽标（那块 39x40 的区域里 57 个红像素），领完是 0，倒计时也归零。所以
   不需要再单独点「结算」—— 它只是餐馆那一块的"立即结账"入口。

2. **亮不亮才是"还有没有东西可领"的唯一判据**，跟邮箱「全部领取」一样。
   `MANAGER_CLAIM` 的文字模板在两种状态下都打 1.000（灰掉的只是颜色），而
   `luma>200` 的像素数在可领时是 1651，领完是 **0**。

3. **结算页会「假命中」面板的检查点**。REWARD 那一层是半透明覆盖，底下的面板
   还看得见，`MANAGER_CLAIM` 在结算页上照样 0.996 —— 所以"面板还在"必须再加
   一条"结算页没盖着"，见 `manager_panel_appear()`。

4. **面板不是页面**，它盖在大厅上、大厅只是被压暗，所以不进 `page.py` 的
   Page 图：进去要按那个图标、出来要按「取消」，而「取消」是坐标（面板下半部分
   随解锁的区块可能变长，那一行会挪），把坐标钉进 `link()` 会让 `ui_goto`
   在面板变长之后无限重试同一个错误位置。这里改成手写开/关，两个都给失败
   兜底，见 `manager_open()` / `manager_close()`。

顺便：面板打开时 `ui_additional()` 会把大厅弹窗那一套套上来（大厅图标还匹配 +
右上角图标被压暗 ⇒ "弹窗"），点左侧空白就能把它关掉 —— 和玩家手点效果一样。
所以万一任务中途崩在面板上，下一次 `ui_goto` 会自己把它清掉，不会卡住。
"""
from module.base.button import Button
from module.base.timer import Timer
from module.browndust.assets import HUNT_REWARD, MANAGER_CLAIM, MANAGER_ENTRY
from module.browndust.browndust_ui import BrowndustUI, page_main
from module.logger import logger

# 「一键获得」可不可点。实测可领 1651 个 luma>200 的像素，领完 0。
MANAGER_CLAIM_LUMA = 200
MANAGER_CLAIM_PIXELS = 100

# 面板底部两个胶囊按钮。「取消」是坐标：它没有自己的图案（米白胶囊上写两个
# 深色字，同一行还有一个「一键获得」），而且这块面板将来会随解锁的区块变长。
# 实测 (537, 596) 在按钮正中，按下去面板就散。
MANAGER_CANCEL = Button(area=(520, 585, 555, 605), color=(0, 0, 0),  # alas-lint: allow - a click point on the 取消 button, the coordinates are the measured label
                        button=(520, 585, 555, 605), name='MANAGER_CANCEL')
# 「取消」挪位时的兜底：点面板外面的遮罩。实测 (1000, 300) 是纯壁纸，既不在
# 右侧那列图标上（x>1100），也不在任何弹窗内容里，按一下面板就散。
MANAGER_OUTSIDE_TAP = Button(area=(980, 290, 1020, 310), color=(0, 0, 0),  # alas-lint: allow - tapping the overlay outside the panel, there is no button to match
                             button=(980, 290, 1020, 310), name='MANAGER_OUTSIDE_TAP')
# 结算页的点击点。和邮箱用的是同一个道理：这一页在 y≈650 写「点击画面即可
# 返回。」，底部那条空白带点得动，(620, 680) 实测有效。
MANAGER_REWARD_TAP = Button(area=(600, 660, 640, 700), color=(0, 0, 0),  # alas-lint: allow - the reward screen says 点击画面即可返回, there is no button to match
                            button=(620, 680, 620, 680), name='MANAGER_REWARD_TAP')

# 点图标到面板出来。实测 0.6~2 秒（淡入），给 10 秒是防网络卡。
MANAGER_PANEL_TIMEOUT = 10
# 点「一键获得」到结算页出现。
MANAGER_REWARD_TIMEOUT = 10
# 结算页是"点一下才走"，节流一下，免得被框架判成连点。
MANAGER_TAP_INTERVAL = 2
# 结算页点掉之后等回面板。
MANAGER_RESULT_TIMEOUT = 30
# 关面板之后等它散掉。淡出很快，但"取消"按空了的兜底要留够时间。
MANAGER_CLOSE_TIMEOUT = 5
# 领完一次之后再问一次。正常一次就领空（按钮直接变灰），多给两次是防"点被
# 吞掉"—— 按空时按钮还是亮的，下一轮自然会再按。
MANAGER_CLAIM_TRIES = 3


class BrowndustManager(BrowndustUI):
    """
    Claim the 经营管理 panel.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        self.ui_goto_main()
        if not self.manager_open():
            logger.warning('Skip 经营管理, the panel did not open')
            self.config.task_delay(server_update=True)
            return

        claimed = self.manager_claim_all()
        logger.info(f'[Manager claimed] {claimed}')
        self.manager_close()
        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def manager_panel_appear(self, offset=(20, 20)):
        """
        Whether the 经营管理 panel is on screen.

        The REWARD screen after 「一键获得」 is a translucent overlay drawn on
        top of the panel, and `MANAGER_CLAIM` still scores 0.996 through it, so
        "the panel is there" and "the reward screen is still up" would be the
        same answer without the second half.

        Args:
            offset: Template match offset.

        Returns:
            bool: If the panel is on screen and nothing is covering it.
        """
        if self.appear(HUNT_REWARD, offset=offset):
            return False
        return self.appear(MANAGER_CLAIM, offset=offset)

    def manager_claim_available(self):
        """
        Whether 「一键获得」 is drawn in its enabled (bright) state.

        The button keeps its shape and its template score after everything is
        claimed, it just goes grey, so the question has to be asked in luma:
        1651 bright pixels when there is something to claim, 0 when there is not.

        Returns:
            bool: True if there is something to claim.
        """
        return self.ui_bright_count(MANAGER_CLAIM.area, MANAGER_CLAIM_LUMA) >= MANAGER_CLAIM_PIXELS

    def manager_open(self):
        """
        Open the panel from the lobby.

        Two attempts at most, and the second one only when the screen is
        provably a clean lobby again: a press that got swallowed by the opening
        animation leaves the panel *fading in*, and pressing the entry position
        at that moment lands on the overlay outside the panel, which closes it.
        So a blind retry would fight itself - the retry waits for the lobby to be
        clean first.

        Pages:
            in: page_main
            out: page_main (panel open)

        Returns:
            bool: If the panel is open.
        """
        if self.manager_panel_appear():
            logger.info('The 经营管理 panel is already open')
            return True

        for attempt in range(2):
            if self.appear(MANAGER_ENTRY, offset=(20, 20)):
                logger.info(f'Open 经营管理 ({attempt + 1})')
                self.device.click(MANAGER_ENTRY)  # alas-lint: allow - guarded by the appear() above and verified by the wait below
                if self.wait_until_appear(MANAGER_CLAIM, offset=(20, 20),
                                          timeout=MANAGER_PANEL_TIMEOUT, settle=2):
                    # 面板是淡入的：淡到一半时「一键获得」还是半透明的，亮度判据会
                    # 读成"没有东西可领"。等这块画完再交给调用方去判。
                    self.wait_until_still(MANAGER_CLAIM.area, timeout=3)
                    return self.manager_panel_appear()

                # 按压被吞掉了。补一下的**前提**是屏幕上确实还是干净的大厅：
                # 面板正在淡入时点同一个坐标会落在面板外的遮罩上，把刚打开的面板
                # 关掉 —— 那样这一下就是在跟自己打架。
                if self.ui_page_appear(page_main, offset=(20, 20)):
                    logger.warning('The panel did not open, press the entry again')
                    continue
                logger.warning('The panel did not open and the lobby is not clean, give up')
                return False

            logger.warning('The 经营管理 entry is not on screen')
            return False

        return False

    def manager_close(self):
        """
        Close the panel and get back to a clean lobby.

        Pages:
            in: page_main (panel open)
            out: page_main

        Returns:
            bool: If the panel is gone.
        """
        if not self.manager_panel_appear():
            return True

        logger.info('Close 经营管理')
        self.device.click(MANAGER_CANCEL)  # alas-lint: allow - the panel being open is checked above, and the disappear below is the proof it took
        if self.wait_until_disappear(MANAGER_CLAIM, offset=(20, 20),
                                     timeout=MANAGER_CLOSE_TIMEOUT, settle=2):
            return True

        # 「取消」那一行会随面板变长而挪位（渔笼/助手解锁之后），按空了就点面板
        # 外面的遮罩 —— 实测一样能关掉。
        logger.warning('Press 取消 did nothing, tap outside the panel')
        self.device.click(MANAGER_OUTSIDE_TAP)  # alas-lint: allow - the target is the overlay, there is no button to guard with
        if self.wait_until_disappear(MANAGER_CLAIM, offset=(20, 20),
                                     timeout=MANAGER_CLOSE_TIMEOUT, settle=2):
            return True

        logger.warning('The 经营管理 panel did not close')
        return False

    def manager_claim_all(self):
        """
        Press 「一键获得」 until there is nothing left to claim.

        Pages:
            in: page_main (panel open)
            out: page_main (panel open)

        Returns:
            int: How many batches went through.
        """
        claimed = 0
        pressed = False
        for i in range(MANAGER_CLAIM_TRIES):
            if not self.manager_claim_available():
                break
            pressed = True
            logger.info(f'Claim all ({i + 1})')
            self.device.click(MANAGER_CLAIM)  # alas-lint: allow - the button being bright is checked right above, and the reward screen below is the proof it took
            # 先记上再判结果：按钮已经按下去了，这一批的奖励就已经进包，哪怕结算页
            # 没点掉，也**不能**当成"没领到"报出去（邮箱那次踩过）。
            claimed += 1
            if not self.manager_close_reward():
                logger.warning('The claim did not come back to the panel')
                break

        if not claimed and not pressed:
            logger.info('Nothing to claim in 经营管理')
        return claimed

    def manager_close_reward(self):
        """
        Sit through the REWARD screen and come back to the panel.

        Same shape as the mailbox one: the panel's own check point scores 0.996
        **through** the reward screen, so the screen is asked about first and the
        panel is only accepted once the banner is gone.

        Pages:
            in: page_main (panel open, reward screen opening)
            out: page_main (panel open)

        Returns:
            bool: If the panel is back.
        """
        if not self.wait_until_appear(HUNT_REWARD, offset=(20, 20),
                                      timeout=MANAGER_REWARD_TIMEOUT, settle=2):
            if self.manager_panel_appear():
                # 没有结算页（比如领的是纯货币），面板自己就刷新了。
                logger.info('No reward screen, the panel refreshed itself')
                return True
            logger.warning('Neither the reward screen nor the panel came back')
            return False

        tap = Timer(MANAGER_TAP_INTERVAL).start()
        for _ in self.loop(timeout=MANAGER_RESULT_TIMEOUT):
            if self.appear(HUNT_REWARD, offset=(20, 20)):
                if tap.reached():
                    tap.reset()
                    logger.info('Reward screen, tap to go back')
                    self.device.click(MANAGER_REWARD_TAP)  # alas-lint: allow - the reward screen has no button, it says 点击画面即可返回
                continue
            if self.manager_panel_appear():
                return True

        logger.warning('The reward screen did not go away')
        return False
