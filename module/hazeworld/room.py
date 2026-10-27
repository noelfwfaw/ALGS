from module.hazeworld.assets import BACK_ARROW, ROOM_BTN_COLLECT_ALL
from module.hazeworld.hazeworld_ui import (HazeworldUI, page_expedition,
                                           page_room)
from module.hazeworld.room_data import EXPEDITION_HOURS, EXPEDITION_TASKS
from module.hazeworld.room_expedition import RoomExpedition
from module.logger import logger

# Come back a little after the expedition should be over, the finish time is
# rounded up to the second on the server.
EXPEDITION_MARGIN = 5


class HazeworldRoom(RoomExpedition, HazeworldUI):
    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
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
        self.wait_until_settled(ROOM_BTN_COLLECT_ALL, timeout=5)

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

