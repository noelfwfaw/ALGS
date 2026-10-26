from module.base.button import Button
from module.hazeworld.assets import (TASK_CLAIM_ALL,
                                     TASK_CLAIM_ALL_DISABLED, TASK_POINT_LABEL,
                                     TASK_TAB_DAILY, TASK_TAB_MONTHLY,
                                     TASK_TAB_WEEKLY, TEMPLATE_TASK_MILESTONE)
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

# The "claim all" button is painted in the theme colour of the tab, not in one
# fixed colour: orange on the daily tab, blue on the weekly tab. The colour
# stored in the asset is the daily one, so `appear(TASK_CLAIM_ALL)` only ever
# matched on daily and the weekly rewards were never claimed.
#
# What every enabled theme shares is a saturated fill, while the disabled button
# is plain grey on all three tabs. Measured: enabled 137, disabled 2. The gap is
# wide enough for a flat threshold.
CLAIM_SATURATION = 40

# The "可领取" tag of the milestone bar. Its left edge sits 40px right of the
# centre of the reward box it belongs to, and 12px above it, measured on the
# daily bar (tag left 866, tag centre y 628, box centre 824/640). The weekly and
# monthly bars use the same layout with a box 55 to 60 wide, so the same offset
# lands inside the box on all three.
MILESTONE_BOX_X = 40
MILESTONE_BOX_Y = 12
MILESTONE_SIMILARITY = 0.9
MILESTONE_MAX = 6


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

    def task_claim_available(self):
        """
        Whether the "claim all" button of the current tab can be pressed.

        The button is painted in the theme colour of the tab (orange on daily,
        blue on weekly), so there is no single colour to match with `appear()`.
        What all enabled themes share is a saturated fill, while the disabled
        button is plain grey on every tab, so the colour spread is measured
        instead. See `CLAIM_SATURATION`.

        Returns:
            bool: If there is something to claim.
        """
        return self.button_saturated(TASK_CLAIM_ALL, CLAIM_SATURATION)

    def task_claim_tab(self, tab, skip_first_screenshot=True):
        """
        Switch to a mission tab, claim its missions and its milestone rewards.

        The claim button is saturated when there is something to claim and grey
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
            available=self.task_claim_available,
        )
        self.interval_clear(TASK_CLAIM_ALL)

        # Claiming the missions raises the point counter, so the bar can reach a
        # milestone that was out of reach a moment ago. The milestone claim has
        # to come after the mission claim for that reason.
        count += self.task_claim_milestone()
        return count

    def task_claim_milestone(self, skip_first_screenshot=True):
        """
        Tap every milestone reward waiting on the point bar of this tab.

        The bar differs per tab: daily has one milestone at 100 points, weekly
        has two, monthly has three, and the boxes move with the tab. "一键领取"
        does not cover them, it only claims the mission list, so they stay
        unclaimed forever unless tapped one by one.

        The "可领取" tag is the only element that says both "this one can be
        claimed" and "where it is", so it is matched as a template and the box
        is tapped to the left of the match. The tag is gone once claimed, which
        makes it the exit condition as well.

        Pages:
            in: page_task
            out: page_task

        Returns:
            int: Times claimed.
        """
        logger.hr('Claim milestones', level=2)
        count = 0

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_reward():
                continue

            similarity, button = TEMPLATE_TASK_MILESTONE.match_result(self.device.image)
            if similarity < MILESTONE_SIMILARITY:
                break

            if count >= MILESTONE_MAX:
                logger.warning(f'Milestone claimed {count} times, stop')
                break

            left, top, right, bottom = button.area
            x = left - MILESTONE_BOX_X
            y = (top + bottom) // 2 + MILESTONE_BOX_Y
            logger.info(f'Milestone reward ({count + 1})')
            self.device.click(Button(
                area=(x - 12, y - 12, x + 12, y + 12),
                color=(),
                button=(x - 12, y - 12, x + 12, y + 12),
                name='TASK_MILESTONE',
            ))
            count += 1

        if count:
            logger.info(f'Milestone finished, claimed {count} time(s)')
        return count
