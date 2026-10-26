from module.base.timer import Timer
from module.exception import GameStuckError
from module.hazeworld.assets import (BACK_ARROW, FRIEND_TAB_LIST,
                                    LOGIN_ANNOUNCE, LOGIN_TOUCH_START,
                                    MAIL_BTN_CLAIM_ALL, MAIN_ICON_FRIEND,
                                    MAIN_ICON_MAIL, MAIN_ICON_PASS,
                                    MAIN_ICON_ROOM, MAIN_ICON_TASK,
                                    PASS_BTN_RESOURCE, REWARD_CHECK,
                                    ROOM_BTN_EXPEDITION,
                                    ROOM_EXP_PANEL_LABEL, ROOM_TITLE_LABEL,
                                    TASK_POINT_LABEL)
from module.logger import logger
from module.ui.page import Page
from module.ui.ui import UI

"""
Pages of Hazeworld (苍雾世界).

The page graph is built the same way the framework expects: every page is
identified by a unique button, and `link()` records "click this -> go there".
`UI.ui_goto()` then finds the shortest path from wherever the game currently is.
"""

page_main = Page(MAIN_ICON_PASS)
# The tab bar changes with the selected tab, the "积分点数" label does not.
page_task = Page(TASK_POINT_LABEL)
page_pass = Page(PASS_BTN_RESOURCE)
page_friend = Page(FRIEND_TAB_LIST)
page_mail = Page(MAIL_BTN_CLAIM_ALL)
# The command room has no bottom tab bar, only the page title.
page_room = Page(ROOM_TITLE_LABEL)
# The expedition panel is a modal, but it behaves like a page: its label stays
# visible in every state, including under the result popup that covers the
# panel title.
page_expedition = Page(ROOM_EXP_PANEL_LABEL)

page_main.link(button=MAIN_ICON_TASK, destination=page_task)
page_main.link(button=MAIN_ICON_PASS, destination=page_pass)
page_main.link(button=MAIN_ICON_FRIEND, destination=page_friend)
page_main.link(button=MAIN_ICON_MAIL, destination=page_mail)
page_main.link(button=MAIN_ICON_ROOM, destination=page_room)
page_room.link(button=ROOM_BTN_EXPEDITION, destination=page_expedition)

for _page in [page_task, page_pass, page_friend, page_mail, page_room]:
    _page.link(button=BACK_ARROW, destination=page_main)
page_expedition.link(button=BACK_ARROW, destination=page_room)


class HazeworldUI(UI):
    """
    Shared UI base of every Hazeworld task.

    Provides the reward popup handler and the "claim all" loop, so each task
    module only describes which page and which button it uses.
    """

    page_main = page_main

    def app_start(self):
        """
        Launch the game and walk through the boot screens until page_main.

        A running game must not be launched again: `am start` only brings it to
        front, so the boot loop below would wait for a title screen that never
        appears and die on a stuck check. If it runs but is not on any known
        page, it is stopped first so a cold boot is guaranteed.

        Pages:
            in: any
            out: page_main
        """
        if self.device.app_is_running():
            if self.ui_any_page_appear():
                logger.info('Game is running, walk to page_main')
                self.ui_goto_main()
                return
            logger.info('Game is running on an unknown page, restart it')
            self.device.app_stop()

        self.device.app_start()
        self.handle_app_boot()

    def handle_app_boot(self, skip_first_screenshot=True):
        """
        Walk through the boot screens.

        A cold start shows a loading screen with lore text, then a full screen
        announcement that has to be dismissed, then the title screen waiting for
        a tap. Loading alone takes about 30 seconds, so the timeout is generous.

        Pages:
            in: any
            out: page_main

        Returns:
            bool: True if page_main is reached.

        Raises:
            GameStuckError: If the game does not reach page_main in time.
        """
        logger.hr('App boot', level=2)
        timeout = Timer(240, count=3).start()

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
                if not self.device.has_cached_image:
                    self.device.screenshot()
            else:
                self.device.screenshot()

            # End
            if self.ui_page_appear(page_main):
                logger.info('Game is at page_main')
                return True

            # Announcement is a modal over the title screen, back dismisses it.
            # Only pressed on the positive condition, never on the main page.
            if self.appear(LOGIN_ANNOUNCE, offset=(20, 20)):
                logger.info('Announcement popup, dismiss it')
                self.device.adb_shell(['input', 'keyevent', '4'])
                continue

            if self.appear_then_click(LOGIN_TOUCH_START, offset=(20, 20), interval=3):
                logger.info('Title screen, touch to start')
                continue

            if timeout.reached():
                logger.warning('Wait game boot timeout')
                raise GameStuckError('Game did not reach page_main after launch')

    def handle_reward(self):
        """
        Close the "获得资源" popup, which asks to tap anywhere to exit.

        Pages:
            in: any
            out: any

        Returns:
            bool: If handled.
        """
        if self.appear(REWARD_CHECK, offset=None):
            logger.info('Reward popup, touch to exit')
            self.device.click(REWARD_CHECK)
            return True

        return False

    def ui_additional(self):
        """
        Popups that may appear on any page.

        Returns:
            bool: If handled.
        """
        return self.handle_reward()

    def claim_all(self, claim, disabled=None, max_click=20, skip_first_screenshot=True):
        """
        Click the "claim all" button until there is nothing left to claim.

        Args:
            claim (Button): Claim all button, only matches when it is clickable.
            disabled (Button): The same button in disabled state, used as the
                positive exit condition. None to exit when `claim` disappears.
            max_click (int): Safety limit, to avoid clicking forever.
            skip_first_screenshot (bool):

        Returns:
            int: Times clicked.
        """
        count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_reward():
                continue

            if disabled is not None and self.appear(disabled, offset=None):
                logger.info('Nothing left to claim')
                break

            if self.appear(claim, offset=None):
                if count >= max_click:
                    logger.warning(f'Claim all clicked {count} times, stop')
                    break
                logger.info(f'Claim all ({count + 1})')
                self.device.click(claim)
                count += 1
                continue

            break

        logger.info(f'Claim all finished, clicked {count} times')
        return count
