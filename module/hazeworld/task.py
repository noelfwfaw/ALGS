from module.base.button import Button
from module.base.utils import get_color
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
# and end the loop while the reward is still on the bar. So the claim has to be
# followed by a wait; what it waits for is the bar itself.
#
# It used to wait for the popup that sometimes comes with a claim, and gave up
# only when a ten second timer ran out. Most milestones pay out without that
# popup - four of them in the 07:52 run of 2026-10-28, forty one seconds of the
# task's forty six - so the wait was almost always spent on a sheet that was
# never going to be drawn. Watching the bar until it stops changing is the same
# wait, measured on the screen instead of guessed, and it ends as soon as the
# redraw is done.
MILESTONE_POPUP_TIMEOUT = 4


# The tap on a tab is swallowed while the reward popup of the previous tab is
# still closing: input stays locked for about a second after the tap that
# dismissed it. A swallowed tap is indistinguishable from a tab with nothing to
# claim by looking at the button alone - both leave it grey - so a tap that was
# lost has to be sent again. See `task_tab_selected()` for how the two are told
# apart, and `TASK_TAB_DARKNESS` for the measure.
TASK_TAB_TRIES = 2

# The tabs of the mission page. A selected tab is filled with a dark plate while
# the others are translucent and show the bright background behind them, so the
# selection is read from the fill. Measured on this page: the plate fills of the
# three tabs are 76 to 87, the unselected ones sit far above, and the battle
# pass reads its own tabs the same way with the same threshold.
TASK_TAB_DARKNESS = 100


class HazeworldTask(HazeworldUI):
    """
    Claim daily / weekly / monthly mission rewards.

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
        self.wait_until_settled(TASK_POINT_LABEL, timeout=5)

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

    def task_tab_selected(self, tab):
        """
        Whether a tab of the mission page is the selected one.

        The tab tap of this page is sometimes swallowed - input stays locked for
        about a second after the popup of the previous tab is dismissed - and a
        swallowed tap looks exactly like a tab with nothing to claim, because
        both leave the claim button grey. The fill of the tab tells them apart:
        the selected tab is drawn on a dark plate, an unselected one is
        translucent. See `TASK_TAB_DARKNESS`.

        Args:
            tab (Button): The tab.

        Returns:
            bool: If the tab is drawn on its dark plate.
        """
        color = get_color(self.device.image, tab.area)
        return max(color) < TASK_TAB_DARKNESS

    def task_claim_tab(self, tab, skip_first_screenshot=True):
        """
        Switch to a mission tab, claim its missions and its milestone rewards.

        The claim button is saturated when there is something to claim and grey
        when there is not, so the disabled state is the exit condition. It is
        read with a settle window: switching tabs on a grey button leaves it
        grey, so an early read reports "nothing to claim" for the tab that was
        just opened and skips its rewards (the weekly tab was lost this way).

        The tab tap itself is retried, but only when it did not land. It used to
        be retried on every empty tab, which cost a second settle window on a
        tab that had nothing to claim: the 09:12 run of 2026-10-28 spent thirty
        six seconds on three empty tabs, half of it re-reading a tab that was
        already open. `task_tab_selected()` answers "did the tap land", so a tab
        that is open and empty is believed the first time.

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

        for _ in range(TASK_TAB_TRIES):
            self.interval_clear(tab)
            # The tab is always on screen whatever is selected, so the press is
            # not guarded by a match; the plate is what tells whether it is
            # already the open one.
            if not self.task_tab_selected(tab):
                self.device.click(tab)  # alas-lint: allow - `task_tab_selected()` above is the guard: the asset of a tab only matches while it is selected, the fill is what describes both states
            count = self.claim_all(
                TASK_CLAIM_ALL,
                disabled=TASK_CLAIM_ALL_DISABLED,
                wait=TASK_CLAIM_SETTLE,
                skip_first_screenshot=False,
                available=self.task_claim_available,
            )
            if count:
                break
            # Nothing to claim, and the tab is the open one: that is the real
            # answer for this tab. Only a tab that is not open means the tap was
            # lost and the loop has to send it again.
            if self.task_tab_selected(tab):
                logger.info(f'{tab.name} has nothing to claim')
                break
            logger.info(f'{tab.name} is not open, tapping it again')
        else:
            logger.warning(f'Cannot open {tab.name} of the mission page')

        self.interval_clear(TASK_CLAIM_ALL)

        # Claiming the missions raises the point counter, so the bar can reach a
        # milestone that was out of reach a moment ago. The milestone claim has
        # to come after the mission claim for that reason.
        count += self.task_claim_milestone()
        return count

    def milestone_wait_reward(self, timeout=MILESTONE_POPUP_TIMEOUT):
        """
        Wait until the point bar has been redrawn after a claim, then close
        whatever the claim raised.

        Waiting on the bar rather than on a popup: the popup only comes with
        some milestones, and waiting for one that never appears costs the whole
        timeout on every claim. The bar, on the other hand, is always redrawn -
        the reward has to come off it - so "the bar stopped changing" is the
        signal that is always there. A popup that does come is caught after the
        wait, and the caller's own loop checks for one again before reading the
        bar, so a sheet that arrives late is still closed.

        Args:
            timeout (int, float): Seconds to watch the bar before giving up on
                it settling.

        Returns:
            bool: If a popup was closed.
        """
        self.wait_until_still(TASK_POINT_LABEL.area, timeout=timeout,
                              skip_first_screenshot=True)

        if self.handle_reward():
            return True
        if self.appear(POPUP_TOUCH_EXIT, offset=(20, 20),
                       similarity=MILESTONE_POPUP_SIMILARITY):
            # A sheet that is still fading in eats the tap, and the caller must
            # read an uncovered bar, so wait until it is really gone.
            self.device.click(POPUP_TOUCH_EXIT)
            self.wait_until_disappear(POPUP_TOUCH_EXIT, offset=(20, 20), timeout=3,
                                      settle=self.SETTLE_FRAMES)
            self.wait_until_still(TASK_POINT_LABEL.area, timeout=timeout)
            return True
        return False

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

        for _ in self.loop(skip_first=skip_first_screenshot):
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
                self.wait_until_disappear(POPUP_TOUCH_EXIT, offset=(20, 20), timeout=3,
                                          settle=self.SETTLE_FRAMES)
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
            self.device.click(Button(  # alas-lint: allow - guarded by the tag match above
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
