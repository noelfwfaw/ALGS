from module.base.timer import Timer
from module.base.utils import get_color
from module.exception import GameStuckError
from module.hazeworld.assets import (BACK_ARROW, BATTLE_CORE_ENTRY,
                                    BATTLE_TAB_RESOURCE, BATTLE_TITLE,
                                    CORE_BTN_HOME, CORE_BTN_SWEEP,
                                    EXIT_CONFIRM, EX_TITLE_LABEL,
                                    FRIEND_TAB_LIST, LOGIN_ANNOUNCE,
                                    LOGIN_TOUCH_START, MAIL_BTN_CLAIM_ALL,
                                    MAIN_BTN_BATTLE, MAIN_BTN_EXERCISE,
                                    MAIN_ICON_FRIEND, MAIN_ICON_MAIL,
                                    MAIN_ICON_PASS, MAIN_ICON_ROOM,
                                    MAIN_ICON_TASK, PASS_BTN_RESOURCE,
                                    PROFILE_MEMBER, REWARD_POPUP,
                                    ROOM_BTN_COLLECT_ALL,
                                    ROOM_BTN_EXPEDITION,
                                    ROOM_EXP_PANEL_LABEL,
                                    SUPPORT_CARD, SUPPORT_ENTRY,
                                    SUPPORT_REWARD, SUPPORT_TITLE,
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

# The lobby is identified by two check points, because both of the obvious ones
# fail now and then: the side icons are drawn on the scene, which is animated,
# and their crop carries a piece of it, while the mail icon gets a badge when
# there is an unread letter. The "作战" button is opaque and always there.
page_main = Page([MAIN_BTN_BATTLE, MAIN_ICON_MAIL])
# The tab bar changes with the selected tab, the "积分点数" label does not.
page_task = Page(TASK_POINT_LABEL)
page_pass = Page(PASS_BTN_RESOURCE)
page_friend = Page(FRIEND_TAB_LIST)
page_mail = Page(MAIL_BTN_CLAIM_ALL)
# The expedition panel is a modal, but it behaves like a page: its label stays
# visible in every state, including under the result popup that covers the
# panel title. It is declared before the room page because the two share the
# screen: the room keeps its title and its bottom bar above and below the
# panel, so a room check point outside of the covered middle would match while
# the panel is open and `ui_ensure(page_room)` would report "already there"
# with the panel still covering the room.
page_expedition = Page(ROOM_EXP_PANEL_LABEL)
# The command room has no bottom tab bar, only the page title. The check point
# is the "collect all" button rather than the title, because the title stays
# readable above the expedition panel: it is the one element of the room the
# panel covers, and it is permanent (it stays drawn and keeps its colour after
# everything has been collected).
page_room = Page(ROOM_BTN_COLLECT_ALL)
# The exercise hall is a full page with its own title. The rank change popup
# covers most of it, but the title stays readable, so this page is matched
# while that popup is open too and has to be checked after it.
page_exercise = Page(EX_TITLE_LABEL)
# The player profile opened by tapping the name plate on page_main.
page_profile = Page(PROFILE_MEMBER)
# The support character panel of the profile, opened by tapping a character
# card. It covers the profile, so the profile check button is not visible here.
page_support = Page(SUPPORT_TITLE)
# The battle dungeon page. Its title is shared by every tab, so this page is
# only matched while the resource tab is closed. Pages are checked in
# declaration order, so page_battle_resource must come first: with that tab
# open both check buttons match and the more specific one has to win.
page_battle_resource = Page(BATTLE_CORE_ENTRY)
page_battle = Page(BATTLE_TITLE)
# The core material stage page of a single core type. The page title changes
# with the selected type, so the sweep button is the check button instead.
page_core = Page(CORE_BTN_SWEEP)

page_main.link(button=MAIN_ICON_TASK, destination=page_task)
page_main.link(button=MAIN_ICON_PASS, destination=page_pass)
page_main.link(button=MAIN_ICON_FRIEND, destination=page_friend)
page_main.link(button=MAIN_ICON_MAIL, destination=page_mail)
page_main.link(button=MAIN_ICON_ROOM, destination=page_room)
page_main.link(button=MAIN_BTN_EXERCISE, destination=page_exercise)
page_main.link(button=SUPPORT_ENTRY, destination=page_profile)
page_main.link(button=MAIN_BTN_BATTLE, destination=page_battle)
page_room.link(button=ROOM_BTN_EXPEDITION, destination=page_expedition)
page_profile.link(button=SUPPORT_CARD, destination=page_support)
page_battle.link(button=BATTLE_TAB_RESOURCE, destination=page_battle_resource)
page_battle_resource.link(button=BATTLE_CORE_ENTRY, destination=page_core)
# The house icon on the core pages jumps straight to the home page, while the
# back arrow only climbs one level. Going home in one hop keeps the walk short,
# and a short walk is what keeps the page graph stable: every extra hop is a
# chance to fire the next tap on a screen that is still fading.
page_core.link(button=CORE_BTN_HOME, destination=page_main)

for _page in [page_task, page_pass, page_friend, page_mail, page_room,
              page_exercise, page_profile, page_battle, page_battle_resource]:
    _page.link(button=BACK_ARROW, destination=page_main)
page_expedition.link(button=BACK_ARROW, destination=page_room)
page_support.link(button=BACK_ARROW, destination=page_profile)
page_core.link(button=BACK_ARROW, destination=page_battle_resource)


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

        The announcement only closes on the back key, but the back key on the
        title screen opens the "确认退出?" dialog, which logs the account out on
        the next launch when it is confirmed. So the key is sent at most once
        every two seconds and only while the announcement is on screen, and the
        dialog is cancelled the moment it shows up.

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
        back = Timer(2)

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

            # Must come before the title screen check, the title stays readable
            # behind this dialog.
            if self.handle_exit_confirm():
                continue

            # Announcement is a modal over the title screen, back dismisses it.
            # Only pressed on the positive condition, never on the main page.
            if self.appear(LOGIN_ANNOUNCE, offset=(20, 20)):
                if back.reached_and_reset():
                    logger.info('Announcement popup, dismiss it')
                    self.device.adb_shell(['input', 'keyevent', '4'])
                continue

            if self.appear_then_click(LOGIN_TOUCH_START, offset=(20, 20), interval=3):
                logger.info('Title screen, touch to start')
                continue

            if timeout.reached():
                logger.warning('Wait game boot timeout')
                raise GameStuckError('Game did not reach page_main after launch')

    def handle_exit_confirm(self):
        """
        Cancel the "确认退出?" dialog, which the back key opens.

        Confirming it quits the game and the next launch asks for the account
        again, so only "取消" is ever clicked.

        Pages:
            in: any
            out: any

        Returns:
            bool: If handled.
        """
        if self.appear(EXIT_CONFIRM, offset=(20, 20)):
            logger.info('Exit confirm dialog, cancel it')
            self.device.click(EXIT_CONFIRM)
            return True

        return False

    def handle_reward(self):
        """
        Close the "获得资源" popup, which asks to tap anywhere to exit.

        The popup is drawn the same way everywhere, but what is behind it is
        not: the room dims the whole page, the mission page draws the popup on
        a bright band, and the battle pass page has a light patch at the point
        that used to be compared. A mean colour check therefore fired on the
        pass page on every screenshot, so the title glyphs are matched instead.
        Measured: 0.996 to 1.0 with the popup, 0.19 to 0.51 without it.

        The tap lands on the title row. The items are drawn below it, and
        tapping an item opens its detail panel, which nothing would close.

        Pages:
            in: any
            out: any

        Returns:
            bool: If handled.
        """
        if self.appear(REWARD_POPUP, offset=(20, 20), similarity=0.9):
            logger.info('Reward popup, touch to exit')
            self.device.click(REWARD_POPUP)
            return True

        return False

    def handle_support_reward(self):
        """
        Close the reward popup of the support character panel.

        It is the same "获得资源" popup as `handle_reward()`, but the panel
        behind it draws a reward of its own at the same place, so it is checked
        before the generic one and tapped at its own blank corner.

        Pages:
            in: any
            out: any

        Returns:
            bool: If handled.
        """
        if self.appear(SUPPORT_REWARD, offset=(20, 20)):
            logger.info('Support reward popup, touch to exit')
            self.device.click(SUPPORT_REWARD)
            return True

        return False

    def ui_additional(self):
        """
        Popups that may appear on any page.

        Returns:
            bool: If handled.
        """
        if self.handle_exit_confirm():
            return True
        return self.handle_reward()

    def button_saturated(self, button, threshold=40):
        """
        Whether a button area is drawn in a strong colour.

        Hazeworld paints the same button in the theme colour of the context: the
        claim button of the mission page is orange on the daily tab and blue on
        the weekly one, the buttons of the expedition panel follow the selected
        expedition. No single colour in an asset covers them, but an active
        button is always saturated while a disabled one is plain grey.

        Args:
            button (Button): The button to measure.
            threshold (int): Colour spread of a saturated fill.

        Returns:
            bool: If the area is saturated.
        """
        color = get_color(self.device.image, button.area)
        return max(color) - min(color) > threshold

    def claim_all(self, claim, disabled=None, max_click=20, wait=0, available=None,
                  skip_first_screenshot=True):
        """
        Click the "claim all" button until there is nothing left to claim.

        Args:
            claim (Button): Claim all button, only matches when it is clickable.
            disabled (Button): The same button in disabled state, used as the
                positive exit condition. None to exit when `claim` disappears.
            max_click (int): Safety limit, to avoid clicking forever.
            wait (int, float): Seconds to keep looking for `claim` before the
                disabled state is accepted. Needed after a tab switch, see
                `HazeworldTask`.
            available (callable): Decides "there is something to claim" instead
                of `appear(claim)`. Needed when no single colour describes the
                button, see `HazeworldTask.task_claim_available`.
            skip_first_screenshot (bool):

        Returns:
            int: Times clicked.
        """
        count = 0
        # Just after a tab switch the button still shows the previous tab, so a
        # disabled button is only believed after `wait` seconds without the
        # clickable one showing up. Zero keeps the plain behaviour.
        settle = Timer(wait).start() if wait else None

        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.handle_reward():
                continue

            if disabled is not None and self.appear(disabled, offset=None):
                if settle is not None and not settle.reached():
                    continue
                logger.info('Nothing left to claim')
                break

            if available is not None:
                clickable = available()
            else:
                clickable = self.appear(claim, offset=None)

            if clickable:
                if count >= max_click:
                    logger.warning(f'Claim all clicked {count} times, stop')
                    break
                logger.info(f'Claim all ({count + 1})')
                self.device.click(claim)
                count += 1
                # The page is obviously the right one now, no need to wait for
                # the disabled state any more.
                settle = None
                continue

            # Neither the clickable nor the disabled button is on screen. That
            # is not a verdict while the settle window is open: right after a
            # tab switch the list is still sliding and both states read as
            # absent, which used to end the loop after a single frame and skip
            # the whole tab. Keep looking until the window closes.
            if settle is not None and not settle.reached():
                continue
            break

        logger.info(f'Claim all finished, clicked {count} times')
        return count
