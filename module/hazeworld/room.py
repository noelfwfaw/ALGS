from module.hazeworld.assets import (BACK_ARROW, ROOM_BTN_COLLECT_ALL,
                                    ROOM_EXP_CLAIM, ROOM_EXP_REDISPATCH)
from module.hazeworld.hazeworld_ui import (HazeworldUI, page_expedition,
                                           page_room)
from module.logger import logger


class HazeworldRoom(HazeworldUI):
    """
    Command room: collect facility output and handle expeditions.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        logger.hr('Command room', level=1)
        self.ui_ensure(page_room)
        # The room scene fades in and ui_ensure() returns on the first frame
        # that matches, so wait for a frame where the collect button is really
        # drawn, or the first click is swallowed by the transition.
        self.appear_settled(ROOM_BTN_COLLECT_ALL, timeout=5)

        if self.config.HazeworldRoom_CollectAll:
            self.room_collect_all()

        if self.config.HazeworldRoom_Expedition:
            self.room_expedition()

        self.ui_goto_main()

        # Daily task, run again after the game refreshes.
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

        if self.appear(ROOM_BTN_COLLECT_ALL, offset=(20, 20)):
            logger.info('Collect all')
            self.device.click(ROOM_BTN_COLLECT_ALL)

        while 1:
            self.device.screenshot()
            if self.handle_reward():
                continue
            break

    def room_expedition(self, skip_first_screenshot=True, max_handle=10):
        """
        Claim finished expeditions and dispatch their team again.

        The panel is entered through the page graph, so a click eaten by the
        collect animation of the room is simply retried.

        Pages:
            in: page_room
            out: page_room
        """
        logger.hr('Expedition', level=2)
        self.ui_ensure(page_expedition)

        count = 0
        idle = 0
        while 1:
            self.device.screenshot()

            if self.handle_reward():
                idle = 0
                continue

            if count >= max_handle:
                logger.warning(f'Expedition handled {count} times, stop')
                break

            # Result popup of a finished expedition: send the team out again.
            if self.appear(ROOM_EXP_REDISPATCH, offset=(20, 20)):
                logger.info(f'Expedition finished, dispatch again ({count + 1})')
                self.device.click(ROOM_EXP_REDISPATCH)
                count += 1
                idle = 0
                continue

            # Mission detail of a finished expedition that is not claimed yet.
            if self.appear(ROOM_EXP_CLAIM, offset=(20, 20)):
                logger.info(f'Expedition finished, claim ({count + 1})')
                self.device.click(ROOM_EXP_CLAIM)
                count += 1
                idle = 0
                continue

            # One frame without an action button can be the panel still sliding
            # in, only trust a second one.
            idle += 1
            if idle >= 2:
                logger.info(f'Expedition finished, handled {count} time(s)')
                break

        # Claiming closes the panel on its own, so only close it if it is still
        # open. The collect button of the room page is the check here, it does
        # not match while the modal dims the room.
        self.ui_click(
            BACK_ARROW,
            check_button=ROOM_BTN_COLLECT_ALL,
            appear_button=BACK_ARROW,
            offset=(20, 20),
            retry_wait=3,
        )
