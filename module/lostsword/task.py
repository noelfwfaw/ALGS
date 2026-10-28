from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import get_color
from module.logger import logger
from module.lostsword.assets import REWARD_POPUP_TITLE, TASK_BTN_CLAIM_ALL
from module.lostsword.lostsword_ui import LostswordUI, page_task

"""
日常任务奖励领取 (daily / weekly / monthly task rewards).

Flow observed in game:

    page_main --菜单--> page_menu --任务--> page_task
    page_task  页签「每日 / 每周 / 史诗」，每个页签右下角各有一个「全部领取」
    page_task  全部领取 -> 「已获得道具。」弹窗（点空白关闭）
    page_task  关闭 X -> page_main（菜单跟着一起关）

The panel is a tabbed view, and "全部领取" only claims the tab that is open, so
all three tabs are visited. Claiming is idempotent: the button is bright when
there is something to claim and grey when there is not, and clicking a grey
button does nothing, so a tab without rewards costs one click and no popup.

The game switches tab on its own after a claim, to the next tab that has a red
dot, which is why the same tab can legitimately be reached twice in one run.
"""

# Clickable areas of the three tabs. The panel layout is fixed, so plain
# coordinates are enough; a miss lands on the empty header of the panel.
#
# They are click points, not assets: there is no template of them on disk, and
# `appear()` needs one - calling it here raised AttributeError every time the
# task ran (2026-10-28 12:54, the first run after these were split out of a
# bigger task). The open tab is found by the colour of its plate instead, see
# `TASK_TAB_MEAN`.
TASK_TAB_DAILY = Button(area=(78, 72, 152, 122), color=(0, 0, 0),  # alas-lint: allow - a click point on a blank part of a panel
                        button=(78, 72, 152, 122), name='TASK_TAB_DAILY')
TASK_TAB_WEEKLY = Button(area=(318, 72, 392, 122), color=(0, 0, 0),  # alas-lint: allow - a click point on a blank part of a panel
                         button=(318, 72, 392, 122), name='TASK_TAB_WEEKLY')
TASK_TAB_MONTHLY = Button(area=(548, 72, 622, 122), color=(0, 0, 0),  # alas-lint: allow - a click point on a blank part of a panel
                          button=(548, 72, 622, 122), name='TASK_TAB_MONTHLY')

# The open tab is drawn as a light plate with dark text, the others as dark
# background with light text, so the mean colour of the area tells them apart
# without a template: measured 140~200 for the open one and 73~79 for the two
# closed ones, on three captures (two references and the 12:54 error frame).
TASK_TAB_MEAN = 110

TASK_TABS = (
    ('daily', TASK_TAB_DAILY),
    ('weekly', TASK_TAB_WEEKLY),
    ('monthly', TASK_TAB_MONTHLY),
)


class LostswordTask(LostswordUI):
    """
    Claim the task rewards of every tab.

    `task_claim()` is also called by `LostswordUI.handle_session_claim()`, so
    the rewards are taken once per session even when the queue is cut short
    before this task gets its turn.

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
        logger.hr('Daily task rewards', level=1)
        if self.config.LostswordTask_Claim:
            self.task_claim()
        else:
            logger.info('LostswordTask.Claim is off, nothing to do')
        # 兜底排期：正常情况下每次启动游戏就已经领过，这里只在整天没启动过时生效。
        self.config.task_delay(server_update=True)

    def task_claim(self):
        """
        Claim every tab and go home.

        Pages:
            in: page_main
            out: page_main

        Returns:
            int: Number of reward popups handled.
        """
        claimed = 0
        for name, tab in TASK_TABS:
            # 关奖励弹窗的那一下有可能连带把面板关掉，每轮都重新确认一次，
            # 否则页签的点击会落在大厅上（那个位置是角色头像）。
            self.ui_ensure(page_task)
            logger.info(f'Claim {name} task rewards')
            # A tab that cannot be confirmed as open is still claimed: the claim
            # is idempotent, so a press that landed on the previous tab costs
            # nothing, while skipping the tab loses its rewards until tomorrow.
            self.task_open_tab(tab)
            claimed += self.task_claim_tab()

        self.ui_goto_main()
        if claimed:
            logger.info(f'Task rewards claimed: {claimed} popup(s)')
        else:
            logger.info('No task reward to claim')
        return claimed

    def task_open_tab(self, tab, timeout=6):
        """
        Open one tab of the task panel.

        The tabs carry no template of their own, so `appear()` cannot be used on
        them (it would try to load a file that does not exist). Two things stand
        in for it: 「全部领取」 is drawn in every state of the panel and guards
        the press, and the mean colour of the tab's own area says whether it is
        the open one (see `TASK_TAB_MEAN`).

        Args:
            tab (Button): Tab to open.
            timeout (int, float): Seconds.

        Returns:
            bool: If the tab is the open one.
        """
        timeout = Timer(timeout).start()
        # Not started: an unstarted timer counts as reached, so the first press
        # goes out on the first frame instead of a second and a half later.
        retry = Timer(1.5)

        for _ in self.loop():
            if sum(get_color(self.device.image, tab.area)) / 3 > TASK_TAB_MEAN:
                # Switching repaints the list below, and 「全部领取」 is read for
                # its colour, so let the panel stop changing first.
                self.wait_until_still(TASK_BTN_CLAIM_ALL.area, timeout=3)
                return True

            if retry.reached():
                retry.reset()
                if self.appear(TASK_BTN_CLAIM_ALL, offset=30):
                    self.device.click(tab)

            if timeout.reached():
                logger.warning(f'{tab.name} did not open')
                return False

    def task_claim_tab(self):
        """
        Press "全部领取" of the opened tab until the button turns grey.

        Returns:
            int: Number of reward popups handled.
        """
        claimed = 0
        for _ in range(3):
            if not self.task_claimable():
                break
            if self.appear(TASK_BTN_CLAIM_ALL, offset=(20, 20)):
                self.device.click(TASK_BTN_CLAIM_ALL)
            if not self.wait_overlay(REWARD_POPUP_TITLE, timeout=4):
                # 按钮显示可领但没出弹窗：多半是这一帧恰好在重绘，不要再点。
                break
            self.handle_reward_popup()
            claimed += 1
        return claimed

    def task_claimable(self):
        """
        Whether the opened tab has rewards left.

        "全部领取" is white when enabled and grey when everything is claimed,
        the template itself matches in both states (1.00 / 1.00), so the state
        is read from the mean colour of its area, not from a match.

        Returns:
            bool: True if the button is enabled.
        """
        self.device.screenshot()
        return self.appear(TASK_BTN_CLAIM_ALL)
