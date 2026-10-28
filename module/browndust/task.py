"""
日常/每周任务领取 (Brown Dust II).

Flow measured on the real device (2026-10-28, screenshots in
`screenshots/browndust/`):

    page_main  --底栏「任务」-->  page_task（落地在「每日任务」）
    page_task  --左侧「每周任务」-->  另一个页签
    page_task  --右下「全部获得」-->  REWARD 结算页（「获得N种」+ 道具一排）
                                      --点底部空白--> 回 page_task
    page_task  领完：每一行变成灰色 ✓、按钮变灰、顶上的区间奖励宝箱也领掉
    page_main  --左上角箭头-->

Three things are not what they look like, all measured rather than guessed:

1. **「全部获得」把顶上「区间奖励」的里程碑宝箱一起领了**。领之前进度条和三只
   宝箱都是灰的（第一只 `luma>200` 只有 380 个像素）；领完那一帧进度条变绿、三只
   全变亮（888/847/899），结算页里也多出宝箱、地球仪和宝石（「获得5种」）。
   所以**不要去点那些宝箱** —— 它们是展示，不是按钮，点了没有反应。

2. **按钮亮不亮才是"还有没有奖励可领"的判据**，跟邮箱的「全部领取」、经营管理
   的「一键获得」是同一个套路。可领时 `luma>200` 有 4982 个像素（区域均值 188），
   领完是 **0**（均值 76）。模板分数在这一对状态里是 1.000 和 0.970，完全分不开。

3. **结算页会命中任务页的检查点**：`TASK_CLAIM_ALL` 透过半透明覆盖层照样打
   0.963。所以"已到任务页"必须再加一条"没有结算页盖着"，见
   `BrowndustUI.ui_reward_clean()` —— 跟 `page_hunt`、`page_mail` 完全同一个理由。

列表是**会变的**：领完之后新任务会插到最上面（实机见到「前往「我的小屋」0/1」
从第三行跳到第一行），一屏也放不下全部任务。所以行号、行数、位置都不能当判据，
只能问"这一页还有没有东西可领"，一次「全部获得」就能把一整页领空。

页签：进任务页时**不一定**停在「每日任务」（邮箱就是记住上次看的那一页的），
所以两个页签都用白字判据确认一次（选中 320/343 个 `luma>200` 的像素，未选中 0）。
"""
from module.base.button import Button
from module.base.timer import Timer
from module.browndust.assets import (HUNT_REWARD, TASK_CLAIM_ALL, TASK_TAB_DAILY,
                                     TASK_TAB_WEEKLY)
from module.browndust.browndust_ui import BrowndustUI, page_task
from module.logger import logger

# 左侧两个页签。`button` 只是文字的框（用来数白像素），`point` 是点击点。
TASK_TABS = {
    'daily': ('每日任务', TASK_TAB_DAILY, (228, 120)),
    'weekly': ('每周任务', TASK_TAB_WEEKLY, (228, 176)),
}
# 页签选中态判据：白像素数。实测选中 320 / 343，未选中 0。
TASK_LABEL_LUMA = 200
TASK_LABEL_PIXELS = 100

# 「全部获得」可不可点。实测可领 4982 个 luma>200 的像素，领完 0。
TASK_CLAIM_LUMA = 200
TASK_CLAIM_PIXELS = 100

# 结算页的点击点：道具下面那条「点击画面即可返回。」再往下的空白带。
# 这一页背后还看得见任务列表（结算页是局部半透明），所以只能点最底下那条。
TASK_REWARD_TAP = Button(area=(600, 680, 640, 720), color=(0, 0, 0),  # alas-lint: allow - the reward screen says 点击画面即可返回, there is no button to match
                         button=(620, 700, 620, 700), name='TASK_REWARD_TAP')

# 点「全部获得」到结算页出现。实测一下就出来，给 10 秒是防网络卡。
TASK_REWARD_TIMEOUT = 10
# 点掉结算页之后再等回任务页。
TASK_RESULT_TIMEOUT = 30
# 结算页是"点一下才走"，节流一下，免得被框架判成连点。
TASK_TAP_INTERVAL = 2
# 领完一次之后再问还有没有。正常一次就领空一页；多给两次是防"领完之后又解锁
# 了下一个任务"（实机见到「前往我的小屋 0/1」就是边领边插进来的）。
TASK_CLAIM_TRIES = 3
# 切页签之后等选中态画出来。实测 0.6 秒就完成，给一屏动画的时间。
TASK_TAB_TIMEOUT = 10


class BrowndustTask(BrowndustUI):
    """
    Claim every finished daily and weekly quest.

    Pages:
        in: page_main
        out: page_main
    """

    def task_label_selected(self, button):
        """
        Whether a tab label is drawn in the selected (white) colour.

        Args:
            button (Button): Tab label asset.

        Returns:
            bool: True if selected.
        """
        return self.ui_bright_count(button.area, TASK_LABEL_LUMA) >= TASK_LABEL_PIXELS

    def task_claim_available(self):
        """
        Whether 「全部获得」 is drawn in its enabled (bright) state.

        Returns:
            bool: True if there is something to claim on this tab.
        """
        return self.ui_bright_count(TASK_CLAIM_ALL.area, TASK_CLAIM_LUMA) >= TASK_CLAIM_PIXELS

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        # 上一次崩在结算页上时，任务页的检查点照样在它底下匹配（0.963），
        # `ui_goto` 会以为"已经到任务页"然后拿着一个点不动的屏幕继续干活。
        # 所以先把手上的结算页点掉，再从大厅重新进。
        if self.appear(HUNT_REWARD, offset=(20, 20)):
            logger.info('A leftover reward screen, close it first')
            self.task_close_reward()

        self.ui_goto(page_task)
        claimed = 0
        for tab in ('daily', 'weekly'):
            if not self.task_open_tab(tab):
                logger.warning(f'The {TASK_TABS[tab][0]} tab did not open, skip it')
                continue
            claimed += self.task_claim_all()

        logger.info(f'[Task claimed] {claimed}')
        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def task_open_tab(self, tab):
        """
        Switch to one of the two tabs.

        Pages:
            in: page_task
            out: page_task

        Args:
            tab (str): daily / weekly.

        Returns:
            bool: If the tab is selected.
        """
        name, button, point = TASK_TABS[tab]
        if self.task_label_selected(button):
            logger.info(f'Already on the {name} tab')
            return True

        logger.info(f'Open the {name} tab')
        press = Timer(2)
        for _ in self.loop(timeout=TASK_TAB_TIMEOUT):
            if self.task_label_selected(button):
                # 切页签时整个列表都在重画，一帧命中不算数（硬约束 89）。
                self.wait_until_still(button.area, timeout=2)
                if self.task_label_selected(button):
                    return True
            if press.reached():
                press.reset()
                self.device.click_minitouch(point[0], point[1])  # alas-lint: allow - verified by the label's colour on the next round

        logger.warning(f'The {name} tab did not open')
        return False

    def task_claim_all(self):
        """
        Press 「全部获得」 until the tab stops offering anything.

        Pages:
            in: page_task
            out: page_task

        Returns:
            int: How many batches went through.
        """
        claimed = 0
        # 切页签之后整个列表都在重画（列表是滑入的），画到一半时读亮度会得到
        # "没东西可领"。先等它静止再问。
        self.wait_until_still(TASK_CLAIM_ALL.area, timeout=3)
        for i in range(TASK_CLAIM_TRIES):
            if not self.task_claim_available():
                break
            logger.info(f'Claim all the quests ({i + 1})')
            self.device.click(TASK_CLAIM_ALL)  # alas-lint: allow - the button being bright is checked right above, and the reward screen below is the proof it took
            # 先记上再判结果：按钮已经按下去了，这一批奖励就已经进包，哪怕结算页
            # 没点掉，也**不能**当成"没领到"报出去。
            claimed += 1
            if not self.task_close_reward():
                logger.warning('The claim did not come back to the task list')
                break
            # 领完之后这一页要重画（每行变成 ✓、新任务插到顶上），画到一半时
            # 读亮度会得到"没东西可领"，所以等它静止再问下一轮。
            self.wait_until_still(TASK_CLAIM_ALL.area, timeout=3)

        # `claimed == 0` 就是"一次都没点下去"（每次点下去都会 +1），所以这里
        # 不需要另一个标志位来区分"没奖"和"点了没回来" —— 后者上面已经 warning 了。
        if not claimed:
            logger.info('No quest reward to claim')
        return claimed

    def task_close_reward(self):
        """
        Sit through the REWARD screen and come back to the task list.

        Same shape as `hunt_start()` and `mail_close_reward()`: the task page's
        check point scores 0.963 **through** the reward screen, so the banner is
        asked about first and the list is only accepted once it is gone.

        Pages:
            in: page_task (reward screen opening)
            out: page_task

        Returns:
            bool: If the task list is back.
        """
        if not self.wait_until_appear(HUNT_REWARD, offset=(20, 20),
                                      timeout=TASK_REWARD_TIMEOUT, settle=2):
            if self.ui_page_appear(page_task, offset=(20, 20)):
                # 按钮亮着但一次奖励都没领到（比如只剩"前往某处"这种不给东西的
                # 任务）时不会弹结算页，直接回到列表。
                logger.info('No reward screen, already back to the task list')
                return True
            logger.warning('Neither the reward screen nor the task list came back')
            return False

        tap = Timer(TASK_TAP_INTERVAL).start()
        for _ in self.loop(timeout=TASK_RESULT_TIMEOUT):
            if self.appear(HUNT_REWARD, offset=(20, 20)):
                if tap.reached():
                    tap.reset()
                    logger.info('Reward screen, tap to go back')
                    self.device.click(TASK_REWARD_TAP)  # alas-lint: allow - the reward screen has no button, it says 点击画面即可返回
                continue
            if self.ui_page_appear(page_task, offset=(20, 20)):
                return True

        logger.warning('The reward screen did not go away')
        return False
