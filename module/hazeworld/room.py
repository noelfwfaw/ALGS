from datetime import timedelta

from module.base.button import Button
from module.base.timer import Timer
from module.hazeworld.assets import (BACK_ARROW, EXP_BTN_RECOMMEND,
                                    EXP_BTN_START, EXP_HOURS_12, EXP_HOURS_4,
                                    EXP_HOURS_8, EXP_TASK_1, EXP_TASK_2,
                                    EXP_TASK_3, EXP_TASK_4, EXP_TASK_5,
                                    ROOM_BTN_COLLECT_ALL,
                                    ROOM_EXP_CLAIM,
                                    ROOM_EXP_RESULT_CANCEL)
from module.hazeworld.hazeworld_ui import (HazeworldUI, page_expedition,
                                           page_room)
from module.logger import logger
from module.ocr.ocr import Duration

# Config value of HazeworldRoom_TeamNTask -> the bar of that expedition in the
# left column. Keep in sync with the option list in argument.yaml.
EXPEDITION_TASKS = {
    'Training': EXP_TASK_1,
    'Defense': EXP_TASK_2,
    'Attack': EXP_TASK_3,
    'Firepower': EXP_TASK_4,
    'Support': EXP_TASK_5,
}

EXPEDITION_HOURS = {
    4: EXP_HOURS_4,
    8: EXP_HOURS_8,
    12: EXP_HOURS_12,
}

# "剩余时间 01:36:26" under the roster of a team that is out. Only the panel of
# the selected expedition carries it, so it is read after the bar is selected,
# and it is the only honest answer to "when does this team come back": the
# duration in the settings describes the dispatch the script makes, not the one
# that is already running.
#
# The digits are dark on the white panel, and a crop that hugs them loses one
# now and then, so a few pixels of the panel are kept on every side.
EXP_REMAIN = Duration(
    Button(area=(888, 596, 978, 618), color=(), button=(888, 596, 978, 618),
           name='EXP_REMAIN'),
    letter=(30, 30, 30),
    threshold=128,
)

# No expedition lasts longer than the longest duration on offer, so a countdown
# beyond that is a misread rather than a team that is out for a year.
EXPEDITION_MAX = max(EXPEDITION_HOURS)
REMAIN_READS = 3

# The buttons of the panel are painted in the theme colour of the selected
# expedition: blue on the training one, orange on the defence one. No single
# colour covers them, so they are recognised by "the fill is saturated", which
# every theme has and a greyed out button has not. Measured: drawn 156 to 183,
# grey 0.
DISPATCH_SATURATION = 40

# One dispatch is a handful of client side taps, a missing start button after
# this long means it was refused (no characters meet the requirement).
DISPATCH_TIMEOUT = 30

# Selecting a tab takes effect on the next frame, but a tap that lands while
# the panel is still switching is swallowed by the client. The tab is therefore
# pressed again until its fill shows that it is selected.
#
# The presses are spaced out: a panel that is not reacting (a popup on top of
# it, a team that cannot be changed) would otherwise be hit on every frame,
# which is 12 taps in 3 seconds and trips the click guard of the framework.
SELECT_TIMEOUT = 10
SELECT_INTERVAL = 1.5
SELECT_TRIES = 4

# Claiming a finished expedition opens the "远征探索" result popup instead of
# returning to the panel, and the popup fades in: on the frame right after the
# claim neither of its buttons is drawn yet. What is on screen right after a
# press is therefore not a verdict, the popup is looked for this long.
RESULT_SETTLE = 4

# Every press restarts `RESULT_SETTLE`, so a panel that keeps offering a claim
# would keep the loop below alive forever. There are two teams, four presses is
# a claim and a close for each of them.
CLAIM_MAX = 8

# Come back a little after the expedition should be over, the finish time is
# rounded up to the second on the server.
EXPEDITION_MARGIN = 5

# "推荐" is pressed a few times before the start button, because the first press
# can land on the roster of the previously selected expedition.
RECOMMEND_TRIES = 3
# Safety limit of the start button, well below the click guard of the framework.
START_TRIES = 4
# Seconds between two taps of the panel. The roster of the team animates in
# after "推荐", and the start button does nothing until it has.
CLICK_INTERVAL = 2.5


class HazeworldRoom(HazeworldUI):
    """
    Command room: collect facility output and run the expeditions.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        logger.hr('Command room', level=1)
        self.ui_ensure(page_room)
        # The game draws 「LOADING......」 over the bottom bar for a second or two
        # after a page switches, and every press that lands in that window is
        # swallowed - the task then logs "Collect all" while nothing happens and
        # walks straight on to the expedition.
        self.ui_wait_loading()
        # The room scene fades in and ui_ensure() returns on the first frame
        # that matches, so wait for a frame where the collect button is really
        # drawn, or the first click is swallowed by the transition.
        self.appear_settled(ROOM_BTN_COLLECT_ALL, timeout=5)

        if self.config.HazeworldRoom_CollectAll:
            self.room_collect_all()

        delay = None
        if self.config.HazeworldRoom_Expedition:
            self.ui_ensure(page_expedition)
            self.ui_wait_loading()
            delay = self.room_expedition()
            self.room_expedition_close()

        self.ui_goto_main()

        if delay is not None:
            # An expedition is not a daily task: it comes back after the number
            # of hours it was sent out for, and only then can it be claimed and
            # sent again. Waiting for the server update would leave the team
            # idle for the rest of the day.
            #
            # With two teams the next run is the one that comes back first, and
            # a team that is already out contributes what is left of its
            # countdown. Its configured duration says nothing about that: a team
            # sent out an hour ago for eight hours is back in seven, not eight,
            # and scheduling it from the settings is how a team ends up waiting
            # for a run that happens hours after it landed.
            self.config.task_delay(minute=delay.total_seconds() / 60 + EXPEDITION_MARGIN)
        else:
            self.config.task_delay(server_update=True)

    def room_collect_all(self, skip_first_screenshot=True):
        """
        Press "collect all" once, then clear the popup it may raise.

        The button keeps its appearance after being pressed, so it cannot be
        used as an exit condition and is pressed once per run.

        Pages:
            in: page_room
            out: page_room
        """
        logger.hr('Collect all', level=2)
        if skip_first_screenshot:
            skip_first_screenshot = False
        else:
            self.device.screenshot()

        self.ui_wait_loading()
        self.device.screenshot()

        if self.appear(ROOM_BTN_COLLECT_ALL, offset=(20, 20)):
            logger.info('Collect all')
            self.device.click(ROOM_BTN_COLLECT_ALL)

        while 1:
            self.device.screenshot()
            if self.handle_reward():
                continue
            break

    def room_expedition(self):
        """
        Claim finished expeditions, then send every configured team out again.

        Pages:
            in: page_expedition
            out: page_expedition

        Returns:
            datetime.timedelta or None: Time until the first team is back,
                None when no team is out.
        """
        logger.hr('Expedition', level=2)
        self.expedition_claim_finished()

        delays = []
        for team in (1, 2):
            task = getattr(self.config, f'HazeworldRoom_Team{team}Task')
            button = EXPEDITION_TASKS.get(task)
            if button is None:
                logger.info(f'Expedition team {team} is not configured')
                continue

            length = int(getattr(self.config, f'HazeworldRoom_Team{team}Hours'))
            delay = self.expedition_dispatch(button, EXPEDITION_HOURS[length], length)
            if delay is not None:
                delays.append(delay)

        if not delays:
            return None
        return min(delays)

    def expedition_dispatch(self, task, hours, length, skip_first_screenshot=True):
        """
        Send one team out on the given expedition for the given duration.

        The team itself is filled by "推荐", which picks characters that meet
        every requirement of the expedition, so nothing is chosen by hand.

        Args:
            task (Button): Bar of the expedition in the left column.
            hours (Button): Duration button.
            length (int): Duration in hours, used for logging.
            skip_first_screenshot (bool):

        Pages:
            in: page_expedition
            out: page_expedition

        Returns:
            datetime.timedelta or None: Time until the team is back, None when
                the team could not be sent out.
        """
        logger.hr(f'Dispatch {task.name} for {length}h', level=2)
        if skip_first_screenshot:
            skip_first_screenshot = False
        else:
            self.device.screenshot()

        # The task has to be selected before the panel is read: the buttons
        # describe the selected expedition only, so leaving the panel on the
        # other team's running expedition reads "already running" for a team
        # that is idle. A panel that does not switch at all is reported instead
        # of being read, the buttons below would belong to another expedition.
        if not self.expedition_select(task):
            return None
        if self.expedition_running():
            logger.info('Expedition is out')
            return self.expedition_remaining(length)

        # The duration is a property of the dispatch, not of the expedition, and
        # it is locked while the team is out, which is why the running check
        # comes first. It also changes the rewards and the requirements of the
        # panel, so it is picked before the team is filled.
        if not self.expedition_select(hours):
            return None

        if not self.expedition_start():
            return None
        return timedelta(hours=length)

    def expedition_remaining(self, length):
        """
        Read how long the selected expedition is still out for.

        The panel redraws its countdown only when an expedition is selected,
        and the game is not drawn while it sits in the background, so the text
        is read here rather than when the page is opened.

        A dropped digit yields a shorter countdown that still looks valid, so a
        reading is only accepted within the time an expedition can last. When
        none of the reads is acceptable the configured duration is used: that
        wakes up late, but a countdown that cannot be read at all would
        otherwise decide the whole schedule.

        Args:
            length (int): Hours the team was sent out for, from the settings.

        Returns:
            datetime.timedelta: Time until the team is back.
        """
        for _ in range(REMAIN_READS):
            remain = EXP_REMAIN.ocr(self.device.image)
            if timedelta() < remain <= timedelta(hours=EXPEDITION_MAX):
                logger.info(f'Expedition is back in {remain}')
                return remain
            self.device.screenshot()

        logger.warning(f'Cannot read the countdown of the {length}h expedition, delay by the settings')
        return timedelta(hours=length)

    def expedition_select(self, button, timeout=SELECT_TIMEOUT):
        """
        Press a tab of the expedition panel until it is the selected one.

        A tap lands only once the previous selection has been drawn, so the tab
        is pressed again until its fill turns saturated. Being selected is the
        positive condition, pressing an already selected tab changes nothing,
        so this is a plain state loop.

        The presses are spaced by `SELECT_INTERVAL` and limited to `SELECT_TRIES`
        instead of being sent on every frame: a panel that never reacts, such as
        one with a popup on top of it, would otherwise be tapped a dozen times
        in three seconds, which is what the click guard of the framework treats
        as a stuck game.

        Args:
            button (Button): The tab.
            timeout (int, float): Give up after this many seconds.

        Returns:
            bool: If the tab is selected.
        """
        logger.info(f'Select {button.name}')
        timeout = Timer(timeout).start()
        interval = Timer(SELECT_INTERVAL)
        tries = 0

        while 1:
            # End
            if self.expedition_button_drawn(button):
                return True
            if timeout.reached() or tries >= SELECT_TRIES:
                logger.warning(f'Cannot select {button.name}')
                return False

            if interval.reached():
                self.device.click(button)
                tries += 1
                interval.reset()
            self.device.screenshot()

    def expedition_running(self):
        """
        Whether the selected expedition has already been sent out.

        A team that is out replaces the start and the recommend button with the
        countdown and the cancel button, and neither of the two is drawn in a
        theme colour, so a frame with both missing reads "out". A single such
        frame can be the panel still switching to the selected expedition, so
        the state has to hold for a moment before it is believed.

        Returns:
            bool: If the team is out.

        Pages:
            in: page_expedition
            out: page_expedition
        """
        # The panel repaints when another expedition is picked, and the game
        # keeps its loading line up during that switch. Reading the buttons in
        # that window finds neither of them and would call an idle team "out" -
        # which is how the second team ended up never being sent.
        self.ui_wait_loading()
        timeout = Timer(3).start()

        while 1:
            # End
            if self.expedition_button_drawn(EXP_BTN_START) \
                    or self.expedition_button_drawn(EXP_BTN_RECOMMEND):
                return False
            if timeout.reached():
                return True

            self.device.screenshot()

    def expedition_start(self):
        """
        Fill the team with "推荐" and send it out with "开始".

        The order is fixed instead of read from the screen: the start button is
        drawn in the theme colour even with no character picked, and right after
        the tab switch the panel still shows the previous expedition's roster,
        so neither the button nor the slots tell the two states apart.

        Pages:
            in: page_expedition
            out: page_expedition

        Returns:
            bool: If the team is out.
        """
        timeout = Timer(DISPATCH_TIMEOUT).start()
        interval = Timer(CLICK_INTERVAL)
        recommend = 0
        start = 0

        while 1:
            self.device.screenshot()

            # End
            if not self.expedition_button_drawn(EXP_BTN_START) \
                    and not self.expedition_button_drawn(EXP_BTN_RECOMMEND):
                logger.info('Expedition is out')
                return True

            if timeout.reached():
                logger.warning('Expedition did not start, the requirements are not met?')
                return False

            if not interval.reached():
                continue
            interval.reset()

            if recommend < RECOMMEND_TRIES:
                recommend += 1
                logger.info(f'Fill the team ({recommend})')
                self.device.click(EXP_BTN_RECOMMEND)
                continue

            start += 1
            if start > START_TRIES:
                logger.warning('Expedition did not start, the requirements are not met?')
                return False
            logger.info('Start the expedition')
            self.device.click(EXP_BTN_START)

    def expedition_button_drawn(self, button):
        """
        Whether a button of the expedition panel is drawn in its theme colour.

        Args:
            button (Button): The button.

        Returns:
            bool: If the pixel area of the button is saturated.
        """
        return self.button_saturated(button, DISPATCH_SATURATION)

    def expedition_claim_finished(self, skip_first_screenshot=True):
        """
        Claim every expedition that has come back, and close its result popup.

        A bar whose expedition is over turns the big button of the panel into
        "点击领取". Pressing it does not return to the panel: the game opens the
        "远征探索" popup with the rewards and two buttons, 取消 and 再次派遣.

        The popup is closed with 取消 and the team is sent out again by the
        dispatch code below, with the expedition and the duration of the
        settings. 再次派遣 would start a new expedition with the duration of the
        previous one, which after a settings change makes the schedule and the
        game disagree about when the team is back.

        The popup must not be left on screen: it covers the panel, every tap of
        the dispatch lands on the popup instead, and the run ends in
        `GameTooManyClickError`. It fades in, so the frames right after a press
        show neither of its buttons, which is why the loop keeps looking for
        `RESULT_SETTLE` seconds after the last press instead of ending on the
        first frame that has nothing on it.

        Pages:
            in: page_expedition
            out: page_expedition

        Returns:
            bool: If anything was handled.
        """
        count = 0
        # Not started, so `reached()` is true until the first press: an empty
        # panel ends the loop on its first frame.
        settle = Timer(RESULT_SETTLE)

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_reward():
                settle.reset()
                continue

            if count >= CLAIM_MAX:
                logger.warning(f'Claimed {count} times, the panel keeps offering more')
                break

            if self.appear(ROOM_EXP_RESULT_CANCEL, offset=(20, 20)):
                logger.info('Expedition result popup, close it')
                self.device.click(ROOM_EXP_RESULT_CANCEL)
                count += 1
                settle.reset()
                continue

            if self.appear(ROOM_EXP_CLAIM, offset=(20, 20)):
                logger.info('Expedition finished, claim it')
                self.device.click(ROOM_EXP_CLAIM)
                count += 1
                settle.reset()
                continue

            if settle.reached():
                break

        return count > 0

    def room_expedition_close(self):
        """
        Leave the panel, claiming closes it on its own in some cases.

        Pages:
            in: page_expedition
            out: page_room
        """
        self.ui_click(
            BACK_ARROW,
            check_button=ROOM_BTN_COLLECT_ALL,
            appear_button=BACK_ARROW,
            offset=(20, 20),
            retry_wait=3,
        )
