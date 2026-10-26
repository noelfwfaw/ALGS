from module.base.button import Button
from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.lostsword.assets import (LOGIN_CHECK, MAIL_BTN_CLOSE, MAIL_TITLE,
                                    MAIN_BTN_BATTLE, MAIN_BTN_MENU,
                                    MAIN_BTN_SHOP, MAIN_BTN_TREASURE,
                                    MENU_BTN_CLOSE, MENU_BTN_MAIL,
                                    MENU_BTN_TASK, REWARD_POPUP_TITLE,
                                    SHOP_BTN_CLOSE, SHOP_DIALOG_CLOSE,
                                    SHOP_DIALOG_TITLE, SHOP_TITLE,
                                    TASK_BTN_CLAIM_ALL, TASK_BTN_CLOSE, TREASURE_BTN_CLAIM,
                                    TREASURE_BTN_CLOSE, TREASURE_BTN_QUICK,
                                    TREASURE_QUICK_CLOSE, TREASURE_QUICK_TITLE,
                                    TREASURE_TITLE)
from module.ui.page import Page
from module.ui.ui import UI

"""
Pages of Lost Sword (失落之剑).

Every panel of this game is a modal that dims the lobby without hiding it: the
bottom bar labels still match behind it (similarity 1.00), so the lobby cannot
be identified by them. `MAIN_BTN_BATTLE` is the battle icon of that bar, which
every panel *does* cover (similarity 0.22~0.27), so the lobby is only matched
when no overlay is open.

Pages are declared from the most specific to the least: `ui_get_current_page()`
returns the first page whose check point matches, and a panel stays drawn behind
the dialog that opens on top of it.
"""

# The quick-explore dialog. It covers the treasure panel title, so the two never
# match at the same time.
page_treasure_quick = Page(TREASURE_QUICK_TITLE)
# The mailbox. Identified by its own title: the panel is full screen, so nothing
# of the lobby is left to recognise, and the "一键领取" button looks the same
# whether there is mail to claim or not.
page_mail = Page(MAIL_TITLE)
# The treasure panel, identified by its own title rather than by the bottom bar
# entry: the entry is still on screen behind the panel.
page_treasure = Page(TREASURE_TITLE)
# The task panel. Its "全部领取" button is unique to the panel and stays on
# screen whether or not there is something to claim, which is what a check point
# needs; whether the button is enabled is read separately as a colour.
page_task = Page(TASK_BTN_CLAIM_ALL)
# The "购买商品" dialog of the shop. It does not hide the shop title behind it
# (the shop stays matched as well), so it has to come before the shop page, and
# it is a page of its own because a dialog left open would swallow every later
# click: routing through it lets `ui_ensure(page_shop)` close a stray one.
page_shop_dialog = Page(SHOP_DIALOG_TITLE)
# The shop. Its title is the only text that is always drawn: the top tab bar and
# the left column both change with what is selected.
page_shop = Page(SHOP_TITLE)
# The menu. Identified by the "任务" text of its icon grid: the icon itself
# carries a red dot that disappears once the tasks are claimed, which drops the
# match from 1.00 to 0.74, so only the text is used.
page_menu = Page(MENU_BTN_TASK)
# The lobby. The battle icon is opaque art and gets covered by every modal.
page_main = Page(MAIN_BTN_BATTLE)

page_main.link(button=MAIN_BTN_TREASURE, destination=page_treasure)
page_main.link(button=MAIN_BTN_MENU, destination=page_menu)
page_menu.link(button=MENU_BTN_MAIL, destination=page_mail)
page_menu.link(button=MENU_BTN_TASK, destination=page_task)
page_menu.link(button=MAIN_BTN_SHOP, destination=page_shop)
page_menu.link(button=MENU_BTN_CLOSE, destination=page_main)
# The mailbox X is its own round button, not the plain X of the menu and task
# panels, so it needs its own asset.
page_mail.link(button=MAIL_BTN_CLOSE, destination=page_main)
# Closing the task panel closes the menu behind it as well: one click lands on
# the lobby directly (verified, 3.7 difference against a clean lobby frame).
page_task.link(button=TASK_BTN_CLOSE, destination=page_main)
# The shop X is the round button in its own corner, 15 pixels left of the menu X.
page_shop.link(button=SHOP_BTN_CLOSE, destination=page_main)
page_shop_dialog.link(button=SHOP_DIALOG_CLOSE, destination=page_shop)
page_treasure.link(button=TREASURE_BTN_CLOSE, destination=page_main)
page_treasure.link(button=TREASURE_BTN_QUICK, destination=page_treasure_quick)
page_treasure_quick.link(button=TREASURE_QUICK_CLOSE, destination=page_treasure)

# The reward popup is a full screen "tap to continue": no close button, no other
# way out than tapping it. Its middle is a golden band that holds the item icons;
# tapping an icon opens the item detail page instead, which nothing handles. The
# band covers y 231~581 and x 166~1114, so the tap below lands on a blank part of
# the panel. One tap is consumed by the popup and by the panel underneath, so the
# caller must re-enter the panel instead of assuming it is still open.
REWARD_POPUP_CLOSE = Button(area=(975, 615, 1025, 655), color=(0, 0, 0),
                            button=(975, 615, 1025, 655), name='REWARD_POPUP_CLOSE')


class LostswordUI(UI):
    page_main = page_main

    # 连续多少帧看不到才算"真的消失"：淡出动画期间元素已经不再匹配，但还在吃点击。
    SETTLE_FRAMES = 3

    def app_start(self):
        """
        Launch the game and walk through the boot screens until page_main.

        A running game must not be launched again: `am start` only brings it to
        front, so the boot loop below would wait for a title screen that never
        appears. If it runs but is not on any known page, it is stopped first so
        a cold boot is guaranteed.

        Daily task rewards are claimed right after the game becomes playable,
        see `handle_daily_task()`.

        Pages:
            in: any
            out: page_main
        """
        if self.device.app_is_running():
            if self.ui_any_page_appear():
                logger.info('Game is running, walk to page_main')
                self.ui_goto_main()
                self.handle_daily_task()
                return
            logger.info('Game is running on an unknown page, restart it')
            self.device.app_stop()

        self.device.app_start()
        self.handle_app_boot()
        self.handle_daily_task()

    def handle_app_boot(self, skip_first_screenshot=True):
        """
        Walk through the boot screens.

        A cold start shows a black screen while the client loads (96~110 seconds
        measured, with the loading percentage at the bottom), then the title
        screen: a rotating key visual with "点击屏幕开始游戏。" in the middle and
        the "全球" server selector in the bottom left. The title screen only
        leaves on a tap, anywhere on screen.

        `LOGIN_CHECK` is that server selector: its area is the text in the
        bottom left, its button is the middle of the screen, so a single asset
        both identifies the title screen and taps through it. The text is UI, it
        stays while the key visual behind it rotates, which is why it matches
        0.95 on every title screen frame and 0.15~0.40 everywhere else.

        The emulator's own speed-up feature is the user's business, this loop
        just waits as long as the client needs.

        Pages:
            in: any
            out: page_main

        Returns:
            bool: True if page_main is reached.

        Raises:
            GameStuckError: If the game does not reach page_main in time.
        """
        logger.hr('App boot', level=2)
        timeout = Timer(300, count=3).start()

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

            if self.appear_then_click(LOGIN_CHECK, offset=(20, 20), interval=3):
                logger.info('Title screen, tap to start')
                continue

            if timeout.reached():
                logger.warning('Wait game boot timeout')
                raise GameStuckError('Game did not reach page_main after launch')

    def handle_daily_task(self):
        """
        Claim the daily task rewards once per game session.

        The task is scheduled last on purpose, but a task that waits for its own
        turn never runs when the queue is closed before it (last task of the
        day, manual stop, crash restart). Claiming it right after every launch
        closes that gap: whatever brought the game up, the rewards are taken.

        This is gated by `LostswordTask.Claim`, not by `Scheduler.Enable`: the
        point of bundling is that it happens even when the task itself is not
        in the queue. `Scheduler.Enable` only decides whether the task also gets
        a slot of its own.

        A failure here must not fail the task that launched the game, so it is
        logged and swallowed: the panel is entered from the lobby next time.

        Returns:
            bool: If the claim ran without an exception.
        """
        from module.config.deep import deep_get

        # Read from the raw config: `app_start()` usually runs inside the
        # `Restart` task, which binds neither `LostswordTask` nor its arguments,
        # so `self.config.LostswordTask_*` does not exist there.
        if not deep_get(self.config.data, 'LostswordTask.LostswordTask.Claim', default=True):
            return True

        from module.lostsword.task import LostswordTask
        try:
            LostswordTask(config=self.config, device=self.device).task_claim()
            return True
        except Exception as e:
            logger.warning(f'Daily task claim failed, ignored: {e}')
            return False

    def ui_additional(self):
        """
        Handle overlays that are not worth a page of their own.

        The reward popup is a full screen "tap to continue": it has no close
        button and no title of its own, it just covers everything. Tapping it is
        the only way out, and the tap has to land on the blank part below.

        Returns:
            bool: If handled.
        """
        if self.appear(REWARD_POPUP_TITLE, offset=30):
            logger.info('Reward popup, dismiss it')
            self.handle_reward_popup()
            return True
        return False

    # ------------------------------------------------------------------
    # shared state waits
    # ------------------------------------------------------------------

    def wait_overlay(self, button, timeout=5):
        """
        Wait until an overlay is on screen.

        Args:
            button (Button): Check point of the overlay.
            timeout (int, float): Seconds.

        Returns:
            bool: If appeared.
        """
        timeout = Timer(timeout).start()
        while 1:
            self.device.screenshot()
            if self.appear(button, offset=30):
                return True
            if timeout.reached():
                return False

    def wait_overlay_gone(self, button, frames=None, timeout=8):
        """
        Wait until an overlay is really gone, not just no longer matching.

        Elements stop matching on the first frame of their fade-out but still eat
        clicks until the animation ends, so the absence has to hold for a few
        frames before the caller may click underneath.

        Args:
            button (Button): Check point of the overlay.
            frames (int): Consecutive frames without a match needed.
            timeout (int, float): Seconds.

        Returns:
            bool: If it left.
        """
        frames = frames or self.SETTLE_FRAMES
        timeout = Timer(timeout).start()
        absent = 0
        while 1:
            self.device.screenshot()
            if self.appear(button, offset=30):
                absent = 0
            else:
                absent += 1
                if absent >= frames:
                    return True
            if timeout.reached():
                logger.warning(f'{button.name} is still on screen')
                return False

    def handle_reward_popup(self, timeout=8):
        """
        Dismiss the "已获得道具。" reward popup and wait until it is gone.

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If the popup left.
        """
        retry = Timer(2, count=3).start()
        timeout = Timer(timeout).start()
        self.device.click(REWARD_POPUP_CLOSE)

        absent = 0
        while 1:
            self.device.screenshot()
            if self.appear(REWARD_POPUP_TITLE, offset=30):
                absent = 0
                # 限速：连点会撞上 12 次连点保护，也可能把上一击吃掉。
                if retry.reached():
                    retry.reset()
                    self.device.click(REWARD_POPUP_CLOSE)
            else:
                absent += 1
                if absent >= self.SETTLE_FRAMES:
                    return True
            if timeout.reached():
                logger.warning('Reward popup is still on screen')
                return False
