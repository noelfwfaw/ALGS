from module.hazeworld.assets import (TASK_CLAIM_ALL,
                                     TASK_CLAIM_ALL_DISABLED, TASK_POINT_LABEL,
                                     TASK_TAB_DAILY, TASK_TAB_MONTHLY,
                                     TASK_TAB_WEEKLY)
from module.hazeworld.hazeworld_ui import HazeworldUI, page_task
from module.logger import logger


class HazeworldTask(HazeworldUI):
    """
    Claim daily / weekly / monthly mission rewards.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        logger.hr('Task claim', level=1)
        self.ui_ensure(page_task)
        # The task page fades in, and ui_ensure() returns on that half drawn
        # frame. Settle it before clicking a tab, or the click may be handled by
        # a page that is not drawn yet and the wrong tab gets claimed.
        self.appear_settled(TASK_POINT_LABEL, timeout=5)

        if self.config.HazeworldTask_ClaimDaily:
            self.task_claim_tab(TASK_TAB_DAILY)
        if self.config.HazeworldTask_ClaimWeekly:
            self.task_claim_tab(TASK_TAB_WEEKLY)
        if self.config.HazeworldTask_ClaimMonthly:
            self.task_claim_tab(TASK_TAB_MONTHLY)

        self.ui_goto_main()

        # Daily task, run again after the game refreshes.
        self.config.task_delay(server_update=True)

    def task_claim_tab(self, tab, skip_first_screenshot=True):
        """
        Switch to a mission tab and claim everything on it.

        The claim button is orange when there is something to claim and grey
        when there is not, so the disabled state is used as the exit condition.

        Args:
            tab (Button): Tab button of the mission page.
            skip_first_screenshot (bool):

        Pages:
            in: page_task
            out: page_task
        """
        logger.hr(f'Claim {tab.name}', level=2)
        self.interval_clear(tab)

        # Switch tab, then claim. Switching is client side and instant, the
        # claim loop takes a fresh screenshot before its first decision.
        self.device.click(tab)
        self.claim_all(
            TASK_CLAIM_ALL,
            disabled=TASK_CLAIM_ALL_DISABLED,
            skip_first_screenshot=False,
        )
        self.interval_clear(TASK_CLAIM_ALL)
