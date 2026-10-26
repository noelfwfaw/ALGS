from module.hazeworld.assets import (TASK_CLAIM_ALL,
                                     TASK_CLAIM_ALL_DISABLED, TASK_POINT_LABEL,
                                     TASK_TAB_DAILY, TASK_TAB_MONTHLY,
                                     TASK_TAB_WEEKLY)
from module.hazeworld.hazeworld_ui import HazeworldUI, page_task
from module.logger import logger

# The tab switch is client side, but the claim button and the mission list keep
# the previous tab's state until the slide-in animation finishes, and the button
# fades in, so it only turns orange on the last frames. Measured on a real
# weekly tab: 3.3s from the tab click to the first frame where the button reads
# as clickable. A tab with nothing to claim looks exactly like that stale frame,
# so the disabled button is only believed after this many seconds without the
# clickable one showing up.
TASK_CLAIM_SETTLE = 6


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
        when there is not, so the disabled state is the exit condition. It is
        read with a settle window: switching tabs on a grey button leaves it
        grey, so an early read reports "nothing to claim" for the tab that was
        just opened and skips its rewards (the weekly tab was lost this way).

        Args:
            tab (Button): Tab button of the mission page.
            skip_first_screenshot (bool):

        Pages:
            in: page_task
            out: page_task

        Returns:
            int: Times claimed.
        """
        logger.hr(f'Claim {tab.name}', level=2)
        self.interval_clear(tab)

        self.device.click(tab)
        count = self.claim_all(
            TASK_CLAIM_ALL,
            disabled=TASK_CLAIM_ALL_DISABLED,
            wait=TASK_CLAIM_SETTLE,
            skip_first_screenshot=False,
        )
        self.interval_clear(TASK_CLAIM_ALL)
        return count
