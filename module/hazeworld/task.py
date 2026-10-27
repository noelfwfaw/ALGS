from module.base.button import Button
from module.base.timer import Timer
from module.hazeworld.assets import (POPUP_TOUCH_EXIT, TASK_CLAIM_ALL,
                                     TASK_CLAIM_ALL_DISABLED, TASK_POINT_LABEL,
                                     TASK_TAB_DAILY, TASK_TAB_MONTHLY,
                                     TASK_TAB_WEEKLY, TEMPLATE_TASK_MILESTONE)
from module.hazeworld.hazeworld_ui import CLAIM_TIMES, HazeworldUI, page_task
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
# daily bar (tag left 863, tag centre y 630, box centre 824/642). The weekly and
# monthly bars use the same layout, so the same offset lands inside the box on
# all three.
#
# The tag is matched, not read by colour: it is a solid plate whose hue belongs
# to the game's current theme - it was gold when this task was written and a
# later patch repainted it cyan (2026-10-27), which silently turned every
# milestone claim into a no-op because the stored picture no longer matched
# anything. The asset is therefore refreshed from the live game whenever the
# theme changes, and the threshold is kept loose enough to accept the few pixels
# of drift between the three bars (daily 1.00, weekly 0.93) while staying far
# above the best false positive anywhere else on the page (0.67).
MILESTONE_BOX_X = 40
MILESTONE_BOX_Y = 12
MILESTONE_SIMILARITY = 0.85
MILESTONE_MAX = 6

# Crediting a milestone raises a popup of its own, and it is not the small
# "获得资源" card `handle_reward()` knows: it is a wide sheet laid over the whole
# point bar with a single reward in it and 「TOUCH TO EXIT」 under the box. The
# template of the small card scores 0.53 on it, so the hint line is matched
# instead - it is unique to this popup (1.00 with it, 0.53 without it anywhere
# else in the screenshots collected so far).
MILESTONE_POPUP_SIMILARITY = 0.85
MILESTONE_POPUP_MAX = 4
# A claim also repaints the bar, and both the repaint and its loading line hide
# the tag for a moment - long enough for the next frame to read "no reward left"
# and end the loop while the reward is still on the bar. The popup that comes
# with the claim is the reliable signal that the bar has been refreshed, so each
# claim waits for it instead of guessing a delay.
MILESTONE_POPUP_TIMEOUT = 10


# The tap on a tab is swallowed while the reward popup of the previous tab is
# still closing: input stays locked for about a second after the tap that
# dismissed it. A swallowed tap is indistinguishable from a tab with nothing to
# claim, because both leave the button grey, so the tap is retried once instead
# of trusting that first verdict. Cost: one extra settle window per empty tab.
TASK_TAB_TRIES = 2


class HazeworldTask(HazeworldUI):
    """
    Claim daily / weekly / monthly mission rewards.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        logger.hr('Task claim', level=1)
        self.task_claim()
        # Missions are finished during the day, not at the daily reset, and
        # they only count as claimed once the button is pressed, so the task
        # comes back on the four openings of the player rather than once a day.
        self.config.task_delay(server_update=CLAIM_TIMES)

    def task_claim(self):
        """
        Claim the tabs that are switched on, then go home.

        This is also what `HazeworldUI.handle_session_claim()` calls, so the
        tabs are read from the raw config rather than from
        `self.config.HazeworldTask_*`: the claim runs from the scheduler, whose
        config binding belongs to whatever task ran last and has no
        `HazeworldTask` attributes at all.

        Pages:
            in: page_main
            out: page_main

        Returns:
            int: Times claimed.
        """
        from module.config.deep import deep_get

        self.ui_ensure(page_task)
        # The task page fades in, and ui_ensure() returns on that half drawn
        # frame. Settle it before clicking a tab, or the click may be handled by
        # a page that is not drawn yet and the wrong tab gets claimed.
        self.appear_settled(TASK_POINT_LABEL, timeout=5)

        count = 0
        for key, tab in (('ClaimDaily', TASK_TAB_DAILY),
                         ('ClaimWeekly', TASK_TAB_WEEKLY),
                         ('ClaimMonthly', TASK_TAB_MONTHLY)):
            if not deep_get(self.config.data, f'HazeworldTask.HazeworldTask.{key}',
                            default=True):
                continue
            count += self.task_claim_tab(tab)

        self.ui_goto_main()
        return count

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

        The tab tap itself is retried once. The tap that dismissed the previous
        tab's reward popup keeps input locked for about a second, and a tab tap
        lands in that window often enough to matter: the tab then never switches
        and its rewards are skipped exactly the same way, with the same innocent
        looking log. See `TASK_TAB_TRIES`.

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
        count = 0

        for attempt in range(TASK_TAB_TRIES):
            # The tap that dismissed the previous tab's reward popup locks input
            # for about a second, so a tab tap right after it is lost and the
            # claim loop then reads the previous tab's grey button as "nothing to
            # claim" (the weekly and monthly rewards were skipped this way).
            # Tapping an open tab does nothing, so the tap is simply repeated.
            self.interval_clear(tab)
            self.device.click(tab)
            count = self.claim_all(
                TASK_CLAIM_ALL,
                disabled=TASK_CLAIM_ALL_DISABLED,
                wait=TASK_CLAIM_SETTLE,
                skip_first_screenshot=False,
                available=self.task_claim_available,
            )
            if count:
                break
        else:
            logger.info(f'{tab.name} has nothing to claim')

        self.interval_clear(TASK_CLAIM_ALL)

        # Claiming the missions raises the point counter, so the bar can reach a
        # milestone that was out of reach a moment ago. The milestone claim has
        # to come after the mission claim for that reason.
        count += self.task_claim_milestone()
        return count

    def milestone_wait_reward(self, timeout=MILESTONE_POPUP_TIMEOUT):
        """
        Wait for the popup of a milestone claim and close it.

        The popup is what tells that the claim went through: while it is up the
        point bar behind it is covered, and the tag cannot be read. Coming back
        only after it is gone means the next look at the bar is a real one.

        Args:
            timeout (int, float): Seconds to wait for it.

        Returns:
            bool: If a popup was closed.
        """
        timeout = Timer(timeout).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()

            if self.handle_reward():
                return True
            if self.appear(POPUP_TOUCH_EXIT, offset=(20, 20),
                           similarity=MILESTONE_POPUP_SIMILARITY):
                self.device.click(POPUP_TOUCH_EXIT)
                self.device.sleep(0.8)
                return True
            if timeout.reached():
                # Some milestones pay out without the sheet; the bar is simply
                # redrawn. Nothing to close then.
                return False
            self.device.sleep(0.5)

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
        popups = 0

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_reward():
                continue

            if self.appear(POPUP_TOUCH_EXIT, offset=(20, 20),
                           similarity=MILESTONE_POPUP_SIMILARITY):
                # The hint sits on the sheet itself, so tapping it is the same
                # as tapping anywhere else on the popup - and it is nowhere
                # near the reward box, whose tap would open the item detail.
                popups += 1
                if popups > MILESTONE_POPUP_MAX:
                    logger.warning('The milestone popup does not close')
                    break
                logger.info('Milestone reward popup, touch to exit')
                self.device.click(POPUP_TOUCH_EXIT)
                self.device.sleep(0.8)
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
            self.milestone_wait_reward()

        if count:
            logger.info(f'Milestone finished, claimed {count} time(s)')
        return count
