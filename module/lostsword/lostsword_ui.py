from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.lostsword.assets import (BOSS_VICTORY, DUNGEON_BTN_BACK,
                                    DUNGEON_CLEAR, LOGIN_CHECK, MAIN_DEFEAT,
                                    REWARD_POPUP_TITLE, SUMMON_SKIP)
from module.lostsword.page import *  # noqa: F401,F403 - the pages, re-exported for the tasks
from module.lostsword.page import BOSS_RESULT_TAP, MAIN_DEFEAT_BACK
from module.ui.ui import UI


class LostswordUI(UI):
    page_main = page_main

    # Own pages, in the order they are declared above. The registry is shared
    # with every other game, and their check points only exist in their own
    # asset namespace.
    pages = (page_treasure_quick, page_boss_dialog, page_boss_ticket,
             page_mail, page_treasure, page_task, page_shop_dialog, page_shop,
             page_dungeon_dialog, page_dungeon, page_copy_stage, page_star,
             page_boss,
             page_arena_season,
             page_arena_preview, page_arena,
             page_event_start, page_event_stage, page_event,
             page_maze, page_talk, page_affection, page_character_detail,
             page_character,
             page_battle, page_menu, page_pass, page_round,
             page_summon_confirm, page_summon_result, page_summon,
             page_main)

    # 连续多少帧看不到才算"真的消失"：淡出动画期间元素已经不再匹配，但还在吃点击。
    SETTLE_FRAMES = 3

    def tap_point(self, x, y):
        """
        Press a point of this game with an adb tap.

        `device.click()` sends a minitouch press that this game ignores on some
        screens - measured on the copy sweep panel, the round table upgrade and
        the maze map: the same coordinates through `adb shell input tap` work
        every time, the minitouch one does nothing. So a press that has to land
        goes through adb, and the caller still waits for the result on screen;
        the tap only replaces the input channel, not the verification.

        Args:
            x (int): Pixel x.
            y (int): Pixel y.
        """
        self.device.adb_shell(['input', 'tap', str(int(x)), str(int(y))])  # alas-lint: allow

    def tap_asset(self, button):
        """
        Press the centre of an asset with an adb tap.

        Args:
            button (Button): Target.
        """
        x1, y1, x2, y2 = button.button
        self.tap_point((x1 + x2) // 2, (y1 + y2) // 2)

    def app_start(self):
        """
        Launch the game and walk through the boot screens until page_main.

        A running game must not be launched again: `am start` only brings it to
        front, so the boot loop below would wait for a title screen that never
        appears. If it runs but is not on any known page, it is stopped first so
        a cold boot is guaranteed.

        Daily task rewards are *not* claimed here, see `handle_session_claim()`.

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

    def handle_session_claim(self):
        """
        Claim the daily task rewards and the battle pass once per session.

        Called by the scheduler when the queue runs dry, i.e. after every queued
        task has been run, and never at launch: the rewards are worth nothing
        compared to the tasks the user queued, so they go last, both here and in
        the priority list.

        The task is scheduled last on purpose, but a task that waits for its own
        turn never runs when the queue is closed before it (last task of the
        day, manual stop, crash restart). This hook closes that gap: whatever
        brought the game up, the rewards are taken at the end of the session.

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

        # Read from the raw config: the scheduler calls this hook outside of any
        # task, so the bound config belongs to whatever ran last and neither
        # `LostswordTask` nor its arguments exist on it.
        if not deep_get(self.config.data, 'LostswordTask.LostswordTask.Claim', default=True):
            return True

        from module.lostsword.battle_pass import LostswordBattlePass
        from module.lostsword.task import LostswordTask

        try:
            LostswordTask(config=self.config, device=self.device).task_claim()
        except Exception as e:
            logger.warning(f'Daily task claim failed, ignored: {e}')
            return False

        # The battle pass is bundled for the same reason: its rewards are ready
        # the moment the day turns over, and waiting for a task slot of its own
        # means missing them whenever the queue is cut short.
        try:
            LostswordBattlePass(config=self.config, device=self.device).pass_claim()
        except Exception as e:
            logger.warning(f'Battle pass claim failed, ignored: {e}')

        return True

    def ui_additional(self):
        """
        Handle overlays that are not worth a page of their own.

        The reward popup is a full screen "tap to continue": it has no close
        button and no title of its own, it just covers everything. Tapping it is
        the only way out, and the tap has to land on the blank part below.

        The victory page of the boss raid is the same kind of screen ("胜利。请
        点击屏幕。"): a run that was interrupted there would otherwise leave the
        game on a page nothing knows.

        The defeat page of the main story ("DEFEAT BRITANNIA") is the same
        story: its 「返回」 is the only way out and it leads straight to the
        lobby through a loading screen, so any walk home that meets it must
        press that key instead of reporting an unknown page.

        A summon cutscene is handled here as well, for the same reason: no page
        matches while it plays, and the Skip key in its corner is the only way
        out. The summon task skips its own cutscenes, so this only fires when a
        run died in one and a later task has to walk home through it.

        Returns:
            bool: If handled.
        """
        if self.appear(SUMMON_SKIP, offset=30, interval=2):
            logger.info('Summon cutscene, skip it')
            self.tap_asset(SUMMON_SKIP)
            return True

        if self.appear(MAIN_DEFEAT, offset=30):
            logger.info('Defeat page, press 返回')
            self.device.click(MAIN_DEFEAT_BACK)
            return True

        if self.appear(REWARD_POPUP_TITLE, offset=30):
            logger.info('Reward popup, dismiss it')
            self.handle_reward_popup()
            return True

        if self.appear(BOSS_VICTORY, offset=30):
            logger.info('Battle result page, tap through it')
            self.device.click(BOSS_RESULT_TAP)
            return True

        if self.appear(DUNGEON_CLEAR, offset=30):
            logger.info('Squad dungeon clear page, leave it')
            self.device.click(DUNGEON_BTN_BACK)
            return True

        # The two dialogs of the boss raid cover the middle of the page only, so
        # the page underneath keeps matching and `ui_goto` believes it already
        # arrived. They are closed here so that any walk through this page can
        # still get rid of them.
        if self.appear_then_click(BOSS_TICKET_CLOSE, offset=30, interval=2):
            logger.info('Paid sweep dialog, close it')
            return True
        if self.appear_then_click(BOSS_DIALOG_CLOSE, offset=30, interval=2):
            logger.info('Sweep confirm dialog, close it')
            return True

        return False

    # ------------------------------------------------------------------
    # shared state waits
    # ------------------------------------------------------------------

    def battle_goto_normal(self, timeout=8):
        """
        Switch the battle page back to its 「普通」 tab.

        The game remembers the tab the page was left on: coming back from the
        arena landed on 「活动」 once (measured), and the 领主突袭 / 竞技场 cards
        only exist under 「普通」. Without this the page graph sees `page_battle`
        but every card click lands on whatever the other tab shows.

        Pages:
            in: page_battle
            out: page_battle

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If the 普通 tab is the open one.
        """
        from module.base.utils import get_color

        timeout = Timer(timeout).start()
        while 1:
            self.device.screenshot()
            color = get_color(self.device.image, BATTLE_TAB_NORMAL.area)
            if sum(color) / 3 > BATTLE_TAB_SELECTED_MEAN:
                # The card list keeps the offset it was left at; put it back to
                # the first card so every card asset sits where it was cut.
                self.battle_scroll(forward=False)
                return True
            # The tab is on screen whether it is the open one or not, so the
            # judgment here is the mean colour above and the press is the usual
            # interval-throttled one.
            if self.appear_then_click(BATTLE_TAB_NORMAL, offset=30, interval=1.5):
                continue
            if timeout.reached():
                logger.warning('Cannot switch the battle page back to 普通')
                return False

    def battle_scroll(self, forward, swipes=3):
        """
        Scroll the card list of the battle page to one of its ends.

        The list holds more cards than fit on screen (领主突袭 / 竞技场 / 小队副本 /
        星辰轮回 / 迷宫) and the game remembers where it was left: after a drag the
        cards sit at different x positions, and every card asset is anchored to
        its position. Scrolling to an end makes the layout predictable again.

        Pages:
            in: page_battle
            out: page_battle

        Args:
            forward (bool): True to drag towards the end of the list (later
                cards), False to drag back to the first card.
            swipes (int): How many drags to make at most. The list is short,
                three always reach the end from anywhere.
        """
        if forward:
            p1, p2 = (1000, 400), (300, 400)
        else:
            p1, p2 = (300, 400), (1000, 400)
        for _ in range(swipes):
            self.device.swipe(p1=p1, p2=p2)
            # The list snaps with an animation that has no check point, so wait
            # for the card band to stop moving instead of pausing a fixed time:
            # dragging again mid-snap stacks the momentum and overshoots.
            if not self.wait_until_still(BATTLE_TAB_NORMAL.area, timeout=2):
                logger.info('Card list did not settle, stop dragging')
                break
        self.device.screenshot()
        # Every drag here is deliberate and its result is checked by the caller;
        # counting them towards "too many click for a button" only means a task
        # that scrolls twice dies halfway (measured 2026-10-27 in the maze).
        self.device.click_record_clear()

    def wait_overlay(self, button, timeout=5):
        """
        Wait until an overlay is on screen.

        Args:
            button (Button): Check point of the overlay.
            timeout (int, float): Seconds.

        Returns:
            bool: If appeared.
        """
        return self.wait_until_appear(button, offset=30, timeout=timeout)

    def wait_overlay_settle(self, button, frames=None, timeout=8):
        """
        Wait until an overlay is fully drawn, not just matching.

        `wait_overlay()` returns on the first frame the check point matches,
        which is the first frame of the fade-in: the panel is still sliding in
        and eats clicks for a moment after that. The 「免费」 button of the shop
        dialog lost exactly one press that way (measured 2026-10-27: pressed
        0.2 s after the title matched, no reward popup, the daily gift stayed
        unclaimed until the next day). Requiring the match to hold for a few
        frames is the cheapest way to know the animation is over.

        Args:
            button (Button): Check point of the overlay.
            frames (int): Consecutive frames with a match needed.
            timeout (int, float): Seconds.

        Returns:
            bool: If the overlay settled.
        """
        return self.wait_until_appear(
            button, offset=30, timeout=timeout, settle=frames or self.SETTLE_FRAMES)

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
        return self.wait_until_disappear(
            button, offset=30, timeout=timeout, settle=frames or self.SETTLE_FRAMES)

    def handle_reward_popup(self, timeout=8, button=None):
        """
        Dismiss the "已获得道具。" reward popup and wait until it is gone.

        The popup is dismissed by tapping a blank spot, and that spot belongs to
        whatever is underneath, so the tap has to be repeated until the popup
        really leaves: one press is regularly swallowed while the panel is still
        fading in.

        Pages:
            in: any
            out: any

        Args:
            timeout (int, float): Seconds.
            button (Button): Where to tap. Defaults to the blank strip below the
                golden band; pages that have a clickable button there pass their
                own safe point.

        Returns:
            bool: If the popup left.
        """
        button = button or REWARD_POPUP_CLOSE
        timeout = Timer(timeout).start()
        for _ in self.loop():
            # Click - throttled by the interval, so a popup that ignores the tap
            # does not turn into a click record overflow.
            if self.appear(REWARD_POPUP_TITLE, offset=30, interval=2):
                self.device.click(button)
                continue

            # End - matched again without the interval: the interval returns
            # False while cooling down, and reading that as "gone" would leave
            # the loop with the popup still on screen.
            if not self.appear(REWARD_POPUP_TITLE, offset=30):  # alas-lint: allow - a "is gone" test
                return self.wait_until_disappear(
                    REWARD_POPUP_TITLE, offset=30, timeout=3, settle=self.SETTLE_FRAMES)

            if timeout.reached():
                logger.warning('Reward popup is still on screen')
                return False
