"""任务领取 of 交错战线 (Cross Core).

The task page opens from the 「任务」 tab of the bottom bar. Its 「一键领取」
sits at the top right and **is shared by 日常 and 周常** - only the page tab
changes, the button keeps its position (2026-11-08 用户原话：「任务那里的一键
领取也是同一个位置」). So the run is:

    日常页 → 一键领取点到变暗 → 点「周常」页签 → 同样点到变暗 → 回大厅

「剧情任务」 is not touched, it has no one-press claim.

Two details the screenshots settled:

1. Lit / greyed can not be told by template matching. The two templates match
   each other at 0.850 / 0.855 (`TM_CCOEFF_NORMED` compares structure, not
   colour), right on the default 0.85 threshold. Both states are therefore read
   from gold pixels: 1991 when lit, 0 when grey. The two `*_DIM` templates are
   only used to answer "is the task page drawn".
2. Which tab is selected is also a gold-pixel question - the selected tab gets
   a golden frame and its text turns gold (717~739 pixels), the other tab keeps
   none. The page remembers the tab the player left it on, so the daily tab is
   opened explicitly instead of assuming it is the default.

Rewards reset daily at 03:00 and weekly at Monday 03:00, so the task schedules
itself on the next server update; the weekly plate is simply grey most days.
"""

from module.base.timer import Timer
from module.crosscore.assets import (MAIN_TASK, TASK_CLAIM, TASK_CLAIM_DIM,
                                     TASK_TAB_DAILY, TASK_TAB_WEEK)
from module.crosscore.crosscore_ui import CrosscoreUI
from module.crosscore.page import page_main
from module.crosscore.utils import CLAIM_GOLD_PIXELS, gold_pixels
from module.logger import logger

# The plate of a task tab, including the golden frame it gains when selected.
# 日常 is the upper one, 周常 the lower one (same width).
DAILY_TAB_AREA = (12, 222, 160, 280)
WEEK_TAB_AREA = (12, 300, 160, 356)


class CrosscoreTask(CrosscoreUI):
    """
    Claim the daily and the weekly task rewards.

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
        logger.hr('交错任务', level=1)
        self.ui_ensure(page_main)

        if not self.task_enter():
            self.config.task_delay(minute=15)
            return

        daily = self.task_claim_tab(TASK_TAB_DAILY, DAILY_TAB_AREA, '日常')
        weekly = self.task_claim_tab(TASK_TAB_WEEK, WEEK_TAB_AREA, '周常')
        self.back_to_main()
        logger.info(f'Task rewards claimed: daily {daily}, weekly {weekly}')
        self.config.task_delay(server_update=True)

    def task_enter(self):
        """
        Open the task page from the bottom bar.

        Returns:
            bool: If the task page is on screen.
        """
        for _ in self.loop(timeout=30):
            if self.handle_item_popup():
                continue
            if self.handle_lobby_popup():
                continue
            if self.task_page_appear():
                self.wait_until_still(TASK_CLAIM.area, timeout=3)
                return True
            if self.appear(MAIN_TASK, offset=(20, 20), interval=3):
                logger.info('Open the task page')
                self.device.click(MAIN_TASK)

        logger.warning('Cannot open the task page')
        return False

    def task_page_appear(self):
        """
        Whether the task page is drawn, in either state of its claim button.

        `TASK_CLAIM_DIM` also matches the lit button at 0.855, which is why the
        two states are told apart by colour, but for "the page is here" either
        template is a hit - and neither matches the lobby or the mailbox at this
        position.
        """
        return self.appear(TASK_CLAIM, offset=(20, 20)) \
            or self.appear(TASK_CLAIM_DIM, offset=(20, 20))

    def task_claim_tab(self, tab, tab_area, name):
        """
        Open one tab and claim it until its button turns grey.

        Args:
            tab (Button): Tab to press.
            tab_area (tuple): Area of the tab plate, gold when selected.
            name (str): Tab name for the log.

        Returns:
            int: Times the claim button was pressed.
        """
        logger.hr(f'领取{name}任务', level=2)
        self.task_open_tab(tab, tab_area, name)
        return self.task_claim()

    def task_open_tab(self, tab, tab_area, name, timeout=8):
        """
        Press a tab until its plate is selected.

        The page remembers the last tab, so both tabs are opened explicitly.
        A tab that will not highlight is not fatal: claiming is idempotent and
        the button position is shared, so the claim goes ahead and the
        screenshot in the log shows which tab was really open.

        Args:
            tab (Button): Tab to press.
            tab_area (tuple): Area of the tab plate, gold when selected.
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
            # The claim button doubles as the guard for the tab tap: it is
            # shared by both tabs, so one of its two states always matches while
            # the page is up, and it can not match anywhere else.
            if self.appear(TASK_CLAIM, offset=(20, 20)) \
                    or self.appear(TASK_CLAIM_DIM, offset=(20, 20)):
                if gold_pixels(self.device.image, tab_area) > CLAIM_GOLD_PIXELS:
                    logger.info(f'<{name}> tab is selected')
                    self.wait_until_still(tab_area, timeout=3)
                    return True
                if retry.reached():
                    retry.reset()
                    logger.info(f'Open the <{name}> tab')
                    self.device.click(tab)

        logger.warning(f'The <{name}> tab did not highlight, claim it anyway')
        return False

    def task_claim(self, max_click=3):
        """
        Press 「一键领取」 until the button turns grey.

        Args:
            max_click (int): Safety limit, the claim is idempotent anyway.

        Returns:
            int: Times clicked.
        """
        claimed = 0

        for _ in self.loop(timeout=60):
            if self.handle_item_popup():
                continue

            if gold_pixels(self.device.image, TASK_CLAIM.area) <= CLAIM_GOLD_PIXELS:
                logger.info('No claimable task reward left')
                break

            if claimed >= max_click:
                logger.warning(f'Claim all pressed {claimed} times, give up')
                break

            # One click per 3 seconds: the popup needs a moment to show up and
            # the button stays lit in the frames before it.
            if self.appear(TASK_CLAIM, offset=(20, 20), interval=3):
                logger.info(f'Claim all, {claimed + 1} time(s)')
                self.device.click(TASK_CLAIM)
                claimed += 1

        return claimed
