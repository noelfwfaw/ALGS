"""通行证（勘探指南）of 交错战线 (Cross Core).

The pass page opens from the 「勘探指南」 icon on the left rail of the lobby. The
run is, in the order the user described it:

    「任务」→ 每日 / 每周 / 本期 依次把「领取奖励」点完 → 点框外关掉弹窗
    → 「全部领取」

Three things the screenshots settled (2026-11-08 用户导出的
`主页面.png` / `通行证页面.png` / `勘探任务.png`, all 1280x720):

1. 「领取奖励」在弹窗里每行一个，**位置会变**：点掉一个，下一个可领的顶上来，
   领完的那一行直接从列表消失（不留暗色按钮）。所以点击和匹配都用
   `offset=(20, 380)` 覆盖整列，`device.click()` 会按 `match()` 找到的位置点，
   不必写死某一行的坐标。
2. 「还有没有能领的」看整列的金色像素：金色只有「领取奖励」，一屏 2762 px；
   「前往」是白色，不计入。阈值沿用 `CLAIM_GOLD_PIXELS`。
3. 三个页签没有导出素材，是纯坐标按钮。当前在哪个页签看文字颜色：选中是金色
   （约 1030 px），未选中 0 px。纯坐标条目只点不认，点击都在
   `appear(PASS_POPUP)` 守卫内。

「全部领取」领的是通行证等级奖励，奖励弹窗就是全局的「获得物品」，
`CrosscoreUI.handle_item_popup()` 已经认识；领完后按钮整个消失，以此收尾。

## 顺序上唯一不能改的地方

`PASS_CLAIM_ALL` 在任务弹窗压暗时仍有 0.901 的结构相似度，所以每一轮循环都必须
先 `handle_item_popup()`、再读「全部领取」，否则会在弹窗上重复点它。
"""

from module.base.timer import Timer
from module.crosscore.assets import (PASS_CLAIM, PASS_CLAIM_ALL, PASS_CLOSE_TAP,
                                     PASS_ENTRY, PASS_POPUP, PASS_TAB_DAILY,
                                     PASS_TAB_PERIOD, PASS_TAB_WEEK, PASS_TASK)
from module.crosscore.crosscore_ui import CrosscoreUI
from module.crosscore.page import page_main
from module.crosscore.utils import CLAIM_GOLD_PIXELS, gold_pixels
from module.logger import logger

# 弹窗里四行任务的按钮都落在这条竖列上（x 900~1070，四行 y 192~236 / 308~353 /
# 424~469 / 540~585）。整列数金色像素：有「领取奖励」就有，全是「前往」就是 0。
CLAIM_COLUMN = (900, 180, 1070, 600)

# 三个页签的文字带。选中时文字变金色，未选中是灰色。
DAILY_TAB_BAND = (180, 150, 340, 182)
WEEK_TAB_BAND = (180, 221, 340, 254)
PERIOD_TAB_BAND = (180, 291, 340, 324)


class CrosscorePass(CrosscoreUI):
    """
    Claim the pass task rewards and the unlocked pass level rewards.

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
        logger.hr('交错通行证', level=1)
        self.ui_ensure(page_main)

        if not self.pass_enter():
            self.config.task_delay(minute=15)
            return

        if self.pass_open_tasks():
            tasks = self.pass_claim_tab(PASS_TAB_DAILY, DAILY_TAB_BAND, '每日')
            tasks += self.pass_claim_tab(PASS_TAB_WEEK, WEEK_TAB_BAND, '每周')
            tasks += self.pass_claim_tab(PASS_TAB_PERIOD, PERIOD_TAB_BAND, '本期')
            self.pass_close_tasks()
        else:
            tasks = 0
            logger.warning('Cannot open the task popup, skip task rewards')

        claimed = self.pass_claim_rewards()
        self.back_to_main()
        logger.info(f'Pass rewards claimed: tasks {tasks}, levels {claimed}')
        # 任务每天、每周一、以及整个赛季刷新；每天刷一次就够了。
        self.config.task_delay(server_update=True)

    def pass_enter(self):
        """
        Open the pass page from the lobby.

        Returns:
            bool: If the pass page is on screen.
        """
        for _ in self.loop(timeout=30):
            if self.handle_item_popup():
                continue
            if self.handle_lobby_popup():
                continue
            if self.appear(PASS_TASK, offset=(20, 20)):
                # 页面有两秒左右的淡入，中途读「任务」按钮会读到半透明帧。
                self.wait_until_still(PASS_TASK.area, timeout=3)
                return True
            # 4 秒一次：通行证页要加载三秒多，3 秒的间隔会在页面画出来之前再点一次
            # 左侧图标（2026-11-08 真机日志：20:43:42 点开，20:43:45 又点了一次）。
            if self.appear(PASS_ENTRY, offset=(20, 20), interval=4):
                logger.info('Open the pass page')
                self.device.click(PASS_ENTRY)

        logger.warning('Cannot open the pass page')
        return False

    def pass_open_tasks(self):
        """
        Press 「任务」 to raise the 「勘探任务」 popup.

        The 任务 button is covered by the popup, so it stops matching once the
        popup is up - that is what keeps the click from being repeated.

        Returns:
            bool: If the popup is on screen.
        """
        for _ in self.loop(timeout=20):
            if self.handle_item_popup():
                continue
            if self.appear(PASS_POPUP, offset=(20, 20)):
                self.wait_until_still(PASS_POPUP.area, timeout=3)
                return True
            if self.appear(PASS_TASK, offset=(20, 20), interval=3):
                logger.info('Open the task popup')
                self.device.click(PASS_TASK)

        logger.warning('The task popup did not open')
        return False

    def pass_claim_tab(self, tab, band, name):
        """
        Open one tab and claim it until it has nothing left.

        Args:
            tab (Button): Tab to press, a raw coordinate button.
            band (tuple): Text band of the tab, gold when selected.
            name (str): Tab name for the log.

        Returns:
            int: Times the claim button was pressed.
        """
        logger.hr(f'领取{name}任务', level=2)
        self.pass_open_tab(tab, band, name)
        return self.pass_claim()

    def pass_open_tab(self, tab, band, name, timeout=10):
        """
        Press a tab until its text turns gold.

        The popup remembers the last tab, so all three are opened explicitly.
        A tab that will not highlight is not fatal: the claim button position is
        shared by the tabs, and the screenshot in the log shows which was open.

        Args:
            tab (Button): Tab to press, a raw coordinate button.
            band (tuple): Text band of the tab, gold when selected.
            name (str): Tab name for the log.
            timeout (int): Seconds to keep trying.

        Returns:
            bool: If the tab is selected.
        """
        # Not started, so the first frame is judged before anything is pressed.
        retry = Timer(1.5)

        for _ in self.loop(timeout=timeout):
            if self.handle_item_popup():
                continue
            # The popup title guards the tab tap: it only exists while the popup
            # is open, and the tab button has no template of its own.
            if self.appear(PASS_POPUP, offset=(20, 20)):
                if gold_pixels(self.device.image, band) > CLAIM_GOLD_PIXELS:
                    logger.info(f'<{name}> tab is selected')
                    self.wait_until_still(band, timeout=2)
                    return True
                if retry.reached():
                    retry.reset()
                    logger.info(f'Open the <{name}> tab')
                    self.device.click(tab)

        logger.warning(f'The <{name}> tab did not highlight, claim it anyway')
        return False

    def pass_claim(self, max_click=20):
        """
        Press 「领取奖励」 until the column has no gold button left.

        Args:
            max_click (int): Safety limit, claiming is idempotent anyway.

        Returns:
            int: Times clicked.
        """
        claimed = 0
        # The reward popup is handled first: it darkens the column and would
        # read exactly like "nothing left to claim".
        idle = Timer(2).start()

        for _ in self.loop(timeout=120):
            if self.handle_item_popup():
                idle.reset()
                continue

            if gold_pixels(self.device.image, CLAIM_COLUMN) <= CLAIM_GOLD_PIXELS:
                # The list re-sorts after every claim, so one empty frame is not
                # enough - it has to stay empty before the tab is called done.
                if idle.reached():
                    logger.info('No claimable task left in this tab')
                    break
                continue

            idle.reset()
            if claimed >= max_click:
                logger.warning(f'Claim pressed {claimed} times, give up')
                break

            # interval keeps one click per 2 seconds: the popup needs a moment to
            # show up and the button is still lit in the frames before it.
            if self.appear(PASS_CLAIM, offset=(20, 380), interval=2):
                logger.info(f'Claim task reward, {claimed + 1} time(s)')
                self.device.click(PASS_CLAIM)
                claimed += 1

        return claimed

    def pass_close_tasks(self, timeout=10):
        """
        Close the task popup by tapping outside of it.

        The popup covers x 150~1112 / y 71~650; `PASS_CLOSE_TAP` sits in the
        bottom left corner of the blurred page behind it, where the page itself
        has nothing pressable either.

        Returns:
            bool: If the popup is closed.
        """
        for _ in self.loop(timeout=timeout):
            if self.handle_item_popup():
                continue
            # The 任务 button is the positive anchor: it is covered while the
            # popup is up, so seeing it again means the popup is gone.
            if self.appear(PASS_TASK, offset=(20, 20)):
                logger.info('The task popup is closed')
                return True
            if self.appear(PASS_POPUP, offset=(20, 20), interval=2):
                logger.info('Close the task popup, tap outside of it')
                self.device.click(PASS_CLOSE_TAP)

        logger.warning('The task popup is still open')
        return False

    def pass_claim_rewards(self, max_click=5):
        """
        Press 「全部领取」 until the button is gone.

        Args:
            max_click (int): Safety limit, claiming is idempotent anyway.

        Returns:
            int: Times clicked.
        """
        claimed = 0
        idle = Timer(2).start()

        for _ in self.loop(timeout=60):
            if self.handle_item_popup():
                idle.reset()
                continue

            if self.appear(PASS_CLAIM_ALL, offset=(20, 20)):
                idle.reset()
                if claimed >= max_click:
                    logger.warning(f'Claim all pressed {claimed} times, give up')
                    break
                if self.appear(PASS_CLAIM_ALL, offset=(20, 20), interval=3):
                    logger.info(f'Claim all pass rewards, {claimed + 1} time(s)')
                    self.device.click(PASS_CLAIM_ALL)
                    claimed += 1
            elif idle.reached():
                logger.info('No pass reward left')
                break

        return claimed
