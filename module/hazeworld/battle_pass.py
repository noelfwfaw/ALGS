from module.base.timer import Timer
from module.base.utils import get_color
from module.hazeworld.assets import (PASS_CLAIM_ALL, PASS_TAB_DAILY,
                                    PASS_TAB_PERIOD, PASS_TAB_WEEKLY,
                                    PASS_VIEW_REWARD, PASS_VIEW_TASK)
from module.hazeworld.hazeworld_ui import CLAIM_TIMES, HazeworldUI, page_pass
from module.logger import logger

# The pass page holds two views behind one toggle at the bottom centre: the
# reward view, one card per level, and the task view, one list per tab.
#
# Claiming a task grants the points that level the pass up, and a level is what
# holds a reward, so the tasks have to be claimed before the rewards. Doing it
# the other way round claims only the levels that were already reached and
# leaves the rest of the reward waiting until the next run.

# The tabs of the task view, in the order their tasks are claimed.
PASS_TASK_TABS = (PASS_TAB_DAILY, PASS_TAB_WEEKLY, PASS_TAB_PERIOD)

# A selected tab is drawn on a solid dark plate, the others are translucent and
# show the bright background of the page. Measured: selected 60 to 65, the
# others 150 to 173.
PASS_TAB_DARKNESS = 100

# The "claim all" button is painted solid blue while there is something to
# claim and translucent while there is not. Measured: colour spread 171 and 26,
# the disabled one being closer to the sand of the background than to blue.
PASS_CLAIM_SATURATION = 100

# Switching a tab redraws the list, and a list that has not been drawn yet
# still shows the previous tab, including its claimable tasks. Same window as
# the mission page: the button is not believed to be disabled before it.
PASS_CLAIM_SETTLE = 6

# A tab or a view is a client side switch, it takes a moment to be drawn.
PASS_SWITCH_TIMEOUT = 10

# Seconds between two presses of the view toggle. The label of the view that is
# being left stays on screen while the other one slides in, so a press right
# after a press would flip the toggle back.
PASS_PRESS_INTERVAL = 2

# Seconds between two presses of a tab. One press is enough to select it, the
# pause is only for the case where the press was sent while the list was still
# sliding and got swallowed by the client.
PASS_TAB_RETRY = 2


class HazeworldPass(HazeworldUI):
    """
    Claim the battle pass: the task rewards of every tab, then the level
    rewards they unlock.

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
        logger.hr('Battle pass claim', level=1)
        self.pass_claim()
        # A pass task is only counted after it is claimed, and experience of a
        # claimed task is what levels the pass up, so this one follows the same
        # four openings as the mission page instead of the daily reset.
        self.config.task_delay(server_update=CLAIM_TIMES)

    def pass_claim(self):
        """
        Claim the switched on parts of the pass, then go home.

        Also called by `HazeworldUI.handle_session_claim()`, which is why the
        switches come from the raw config: the claim runs from the scheduler,
        whose config binding is whatever task ran last and has no
        `HazeworldPass` attributes.

        Pages:
            in: page_main
            out: page_main

        Returns:
            int: Times claimed.
        """
        from module.config.deep import deep_get

        self.ui_ensure(page_pass)
        count = 0
        if deep_get(self.config.data, 'HazeworldPass.HazeworldPass.ClaimTask',
                    default=True):
            count += self.pass_claim_task()
        if deep_get(self.config.data, 'HazeworldPass.HazeworldPass.ClaimAll',
                    default=True):
            count += self.pass_claim_reward()
        self.ui_goto_main()
        return count

    def pass_claim_task(self):
        """
        Claim the task rewards of the daily, weekly and period tab.

        Pages:
            in: page_pass
            out: page_pass

        Returns:
            int: Times claimed.
        """
        logger.hr('Pass tasks', level=2)
        if not self.pass_view(PASS_VIEW_TASK):
            return 0

        count = 0
        for tab in PASS_TASK_TABS:
            count += self.pass_claim_tab(tab)
        logger.info(f'Pass tasks finished, claimed {count} times')
        return count

    def pass_claim_tab(self, tab):
        """
        Claim all the finished tasks of one tab.

        Args:
            tab (Button): Tab of the task view.

        Pages:
            in: page_pass
            out: page_pass

        Returns:
            int: Times claimed.
        """
        if not self.pass_select_tab(tab):
            return 0
        # The plate turning dark is what `pass_select_tab()` waits for, but the
        # claim button is painted a few frames later - measured 3.3s on the
        # weekly tab - so reading it right away reports the previous tab's grey
        # button. Waiting for this area to stop changing is the same wait that
        # `PASS_CLAIM_SETTLE` used to spend in full on every tab, empty or not.
        self.wait_until_still(PASS_CLAIM_ALL.area, timeout=PASS_CLAIM_SETTLE)
        return self.claim_all(PASS_CLAIM_ALL, available=self.pass_claim_available)

    def pass_claim_reward(self):
        """
        Claim every level reward of the pass.

        Pages:
            in: page_pass
            out: page_pass

        Returns:
            int: Times claimed.
        """
        logger.hr('Pass rewards', level=2)
        if not self.pass_view(PASS_VIEW_REWARD):
            return 0

        # The view slides in, and its claim button is drawn with it.
        self.wait_until_still(PASS_CLAIM_ALL.area, timeout=PASS_CLAIM_SETTLE)
        count = self.claim_all(PASS_CLAIM_ALL, available=self.pass_claim_available)
        logger.info(f'Pass rewards finished, claimed {count} times')
        return count

    def pass_view(self, view, timeout=PASS_SWITCH_TIMEOUT):
        """
        Open one of the two views of the pass page.

        The toggle at the bottom centre carries the label of the view it opens,
        so a frame of the task view shows the "奖励" label and a frame of the
        reward view shows the "任务" one. Each crop is taken from a frame of the
        view it is named after, which makes `view` the confirmation and `other`
        the thing to press: whatever the toggle reads right now is exactly the
        button that leads to the view that is missing.

        The press itself is guarded twice. It is only sent while the label of
        the other view is on screen, so a frame that is still sliding is never
        pressed, and never twice within `PASS_PRESS_INTERVAL`, because the old
        label stays on screen for a moment after the press and a second press
        in that moment lands back on the view it was just leaving.

        Args:
            view (Button): The view to open, PASS_VIEW_TASK or PASS_VIEW_REWARD.
            timeout (int, float): Give up after this many seconds.

        Pages:
            in: page_pass
            out: page_pass

        Returns:
            bool: If the view is open.
        """
        logger.info(f'Open {view.name}')
        other = PASS_VIEW_REWARD if view is PASS_VIEW_TASK else PASS_VIEW_TASK
        timeout = Timer(timeout).start()
        interval = Timer(PASS_PRESS_INTERVAL)

        while 1:
            # End
            if self.appear(view, offset=(20, 20)):
                return True
            if timeout.reached():
                logger.warning(f'Cannot open {view.name} of the battle pass')
                return False

            if interval.reached() and self.appear(other, offset=(20, 20)):
                self.device.click(other)
                interval.reset()
            self.device.screenshot()

    def pass_select_tab(self, tab, timeout=PASS_SWITCH_TIMEOUT):
        """
        Press a tab of the task view until it is the selected one.

        A selected tab is filled with a dark plate, the others are translucent,
        so the selection is read from the fill instead of waited for. A press
        restarts the redraw of the list, so the tab is pressed once and then
        left alone for `PASS_TAB_RETRY` seconds: pressing on every frame would
        restart the redraw it is waiting for.

        The press is not guarded by a template match. The crop of a tab can only
        be taken while it is selected - that is the only state where the plate
        is solid enough to cut - which makes `appear()` refuse the tab exactly
        when it needs pressing. The two tabs that are not selected by default
        were never pressed at all, each waiting out the timeout on a tab the
        check below would have described correctly. So the press goes straight
        to the area of the tab, and `pass_tab_selected()` is both the guard and
        the confirmation.

        Args:
            tab (Button): The tab.
            timeout (int, float): Give up after this many seconds.

        Pages:
            in: page_pass
            out: page_pass

        Returns:
            bool: If the tab is selected.
        """
        logger.info(f'Select {tab.name}')
        timeout = Timer(timeout).start()
        # A press restarts the redraw of the list, so the tab must not be
        # pressed on every frame while it is still being drawn: the plate would
        # never settle. One press, then a pause before the next attempt.
        retry = Timer(PASS_TAB_RETRY)

        while 1:
            # End
            if self.pass_tab_selected(tab):
                return True
            if timeout.reached():
                logger.warning(f'Cannot select {tab.name} of the battle pass')
                return False

            if retry.reached():
                self.device.click(tab)  # alas-lint: allow - the asset of a tab only matches while it is selected, and `pass_tab_selected()` above is what tells the two states apart
                retry.reset()
            self.device.screenshot()

    def pass_tab_selected(self, tab):
        """
        Whether a tab of the task view is the selected one.

        Args:
            tab (Button): The tab.

        Returns:
            bool: If the tab is drawn on its dark plate.
        """
        color = get_color(self.device.image, tab.area)
        return max(color) < PASS_TAB_DARKNESS

    def pass_claim_available(self):
        """
        Whether the "claim all" button of the pass page is clickable.

        Returns:
            bool: If there is something to claim.
        """
        return self.button_saturated(PASS_CLAIM_ALL, PASS_CLAIM_SATURATION)
