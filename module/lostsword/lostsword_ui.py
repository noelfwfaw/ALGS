from module.base.button import Button
from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.lostsword.assets import (AFFECTION_BTN_DONE,
                                    AFFECTION_BTN_TALK, AFFECTION_TAP,
                                    ARENA_BTN_CHALLENGE_1,
                                    ARENA_BTN_CHALLENGE_2,
                                    ARENA_BTN_CHALLENGE_3, ARENA_BTN_CLOSE,
                                    ARENA_BTN_ENTER, ARENA_BTN_SEASON,
                                    ARENA_BTN_SKIP, ARENA_BTN_TEAM,
                                    ARENA_CARD,
                                    ARENA_PROMO_TAG, ARENA_SEASON_FOOTER,
                                    ARENA_TITLE, ARENA_VICTORY,
                                    BOSS_BTN_CLOSE,
                                    BOSS_BTN_TEAM, BOSS_CARD,
                                    BOSS_DIALOG_CLOSE, BOSS_DIALOG_TITLE,
                                    BOSS_TICKET_CLOSE, BOSS_TICKET_TITLE,
                                    BATTLE_TITLE, BOSS_VICTORY, CHAR_BTN,
                                    CHAR_BTN_AFFECTION, CHAR_TITLE,
                                    DUNGEON_BTN_BACK, DUNGEON_CARD,
                                    DUNGEON_CLEAR, DUNGEON_DIALOG_CLOSE,
                                    COPY_BTN_SELECT, COPY_BTN_SWEEP,
                                    DUNGEON_DIALOG_TITLE,
                                    DUNGEON_TITLE,
                                    EVENT_BTN_SELECT, EVENT_BTN_START,
                                    EVENT_TAB, EVENT_TAB_SELECTED,
                                    LOGIN_CHECK, MAIL_BTN_CLOSE, MAIL_TITLE,
                                    STAR_CARD, STAR_TITLE,
                                    MAIN_BTN_BATTLE, MAIN_BTN_MENU,
                                    MAIN_BTN_SHOP, MAIN_BTN_TREASURE,
                                    MENU_BTN_CLOSE, MENU_BTN_MAIL,
                                    MENU_BTN_TASK, PASS_BTN, PASS_TITLE,
                                    REWARD_POPUP_TITLE, ROUND_BTN,
                                    ROUND_BTN_UPGRADE,
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
# The "是否进行扫荡?" dialog of the boss raid. The dialog does not cover the
# boss page behind it (its "队伍编排" button stays matched), so this has to come
# before that page. It is a page of its own because a dialog left open swallows
# every later click: routing through it lets `ui_ensure(page_boss)` close a stray
# one instead of clicking into a modal.
page_boss_dialog = Page(BOSS_DIALOG_TITLE)
# The 「一键扫荡」 dialog, the paid sweep: it opens when 「扫荡」 is pressed with no
# free try left, and it spends a Boss Raid Ticket if its own 「扫荡」 button is
# pressed. The task never wants it (one tap too far and the user's tickets are
# gone), but it has to be a page of the graph all the same, so that a run that
# stumbles into it closes it instead of leaving a modal on screen.
page_boss_ticket = Page(BOSS_TICKET_TITLE)
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
# The boss raid detail page (领主突袭). Its "队伍编排" button is drawn in every
# state of the page: the sweep counter changes, the "最高分数" row only appears
# after today's battle, but that button stays. Measured 1.00 here, 0.21 on the
# battle tab and 0.19 on the victory page.
page_boss = Page(BOSS_BTN_TEAM)
# The event tab of the battle page. The 「战斗」 heading of `page_battle` stays on
# screen here, so this page has to be declared before it.
page_event = Page(EVENT_TAB_SELECTED)
# A stage page of an event. Its 「选择」 button sits in the bottom right corner
# and the card list behind it does not have one.
page_event_stage = Page(EVENT_BTN_SELECT)
# The sortie page of an event stage, the one 「选择」 opens. Same layout as the
# boss raid sortie page but a different bottom button: 「出发」.
page_event_start = Page(EVENT_BTN_START)
# The battle tab (战斗), the page with the 普通 / 副本 / 挑战 / 公会 / 活动 cards.
# Its own heading is the check point, not a card: the game remembers the tab it
# was left on (measured: back from the arena on 「活动」), and the cards only
# exist under 「普通」.
page_battle = Page(BATTLE_TITLE)
# A stage page under the 副本 tab. Its 「选择」 button is on every one of them
# (the sweepable stages add 「扫荡」 next to it, the limited ones only have 选择),
# while the card list behind it does not have it at all.
page_copy_stage = Page([COPY_BTN_SELECT, COPY_BTN_SWEEP])
# 星辰轮回, opened from the last card of the battle page. Full screen with the
# three adventure areas on the left and the score table on the right.
page_star = Page(STAR_TITLE)
# The squad dungeon detail page (小队副本). Built like the boss raid page - same
# 「队伍编排」 button, same left column - so it is matched by its boss name instead,
# and it has to come before `page_boss` because that page's check point matches
# here as well.
page_dungeon = Page(DUNGEON_TITLE)
# Its "是否前往小队副本房间?" confirm dialog covers the middle only, so the page
# below keeps matching and the dialog has to be a page of its own, declared first.
page_dungeon_dialog = Page(DUNGEON_DIALOG_TITLE)
# The arena list (竞技场). The 「对战对手」 heading is drawn whatever the three
# cards hold, while the side panel carries numbers that change every battle.
page_arena = Page(ARENA_TITLE)
# The versus page of one arena battle. Its 「编排进攻队伍」 button is the only
# thing that stays: the cards and the opponent change with the list.
page_arena_preview = Page(ARENA_BTN_TEAM)
# The season mission panel of the arena. Identified by its footnote rather than
# by the 「全部领取」 button: that button and the one of the task panel match each
# other's screenshots (same label, 170 pixels apart), so either of them used as a
# check point made the two pages claim each other. The footnote exists only here.
page_arena_season = Page(ARENA_SEASON_FOOTER)
# The menu. Identified by the "任务" text of its icon grid: the icon itself
# carries a red dot that disappears once the tasks are claimed, which drops the
# match from 1.00 to 0.74, so only the text is used.
page_menu = Page(MENU_BTN_TASK)
# The battle pass panel, opened from the lobby's left column. Full screen; the
# season it shows is picked by the game, not by the graph.
page_pass = Page(PASS_TITLE)
# The character grid, opened from the bottom bar. Its 「角色」 heading is the
# check point; a detail page shows the character name there instead (0.79).
page_character = Page(CHAR_TITLE)
# One character's detail page. The affection entry at the bottom left is an icon
# whose label changes with the character (羁绊延续 / 心生好感 / ...), so the icon
# is what is matched.
page_character_detail = Page(CHAR_BTN_AFFECTION)
# The affection panel of that character. Both talk buttons match here - the one
# with tries left and the finished one - because whatever is under it is the
# panel either way.
page_affection = Page([AFFECTION_BTN_TALK, AFFECTION_BTN_DONE])
# A running conversation: the continue arrow at the bottom right.
page_talk = Page(AFFECTION_TAP)
# The round table panel, opened from the menu grid. Its 「升级」 button is drawn
# whether or not the resources are enough (the colour tells, read separately),
# and it covers the menu behind it.
page_round = Page(ROUND_BTN_UPGRADE)
# The lobby. The battle icon is opaque art and gets covered by every modal.
page_main = Page(MAIN_BTN_BATTLE)

page_main.link(button=MAIN_BTN_TREASURE, destination=page_treasure)
page_main.link(button=MAIN_BTN_MENU, destination=page_menu)
page_main.link(button=MAIN_BTN_BATTLE, destination=page_battle)
page_main.link(button=PASS_BTN, destination=page_pass)
page_main.link(button=CHAR_BTN, destination=page_character)
page_character.link(button=ARENA_BTN_CLOSE, destination=page_main)
page_character_detail.link(button=ARENA_BTN_CLOSE, destination=page_character)
page_affection.link(button=ARENA_BTN_CLOSE, destination=page_character_detail)
page_pass.link(button=ARENA_BTN_CLOSE, destination=page_main)
# The 领主突袭 card opens the detail page. It is also this page's check point,
# which is fine: it is the only card the tasks below ever click.
page_battle.link(button=EVENT_TAB, destination=page_event)
page_event.link(button=ARENA_BTN_CLOSE, destination=page_battle)
# The stage page and the sortie page are two levels of the same event: the X of
# the stage page goes up to the sortie page (measured), and the X of the sortie
# page leaves the event.
page_event_stage.link(button=ARENA_BTN_CLOSE, destination=page_event_start)
page_event_start.link(button=ARENA_BTN_CLOSE, destination=page_event)
page_battle.link(button=BOSS_CARD, destination=page_boss)
page_battle.link(button=DUNGEON_CARD, destination=page_dungeon)
page_battle.link(button=STAR_CARD, destination=page_star)
page_star.link(button=ARENA_BTN_CLOSE, destination=page_battle)
page_copy_stage.link(button=ARENA_BTN_CLOSE, destination=page_battle)
page_dungeon.link(button=ARENA_BTN_CLOSE, destination=page_battle)
page_dungeon_dialog.link(button=DUNGEON_DIALOG_CLOSE, destination=page_dungeon)
page_battle.link(button=ARENA_CARD, destination=page_arena)
# All three cards lead to the same versus page: which one is fought is decided
# by the task, not by the page graph.
page_arena.link(button=ARENA_BTN_CHALLENGE_1, destination=page_arena_preview)
page_arena.link(button=ARENA_BTN_CHALLENGE_2, destination=page_arena_preview)
page_arena.link(button=ARENA_BTN_CHALLENGE_3, destination=page_arena_preview)
page_arena.link(button=ARENA_BTN_CLOSE, destination=page_battle)
page_arena.link(button=ARENA_BTN_SEASON, destination=page_arena_season)
page_arena_preview.link(button=ARENA_BTN_CLOSE, destination=page_arena)
page_arena_season.link(button=ARENA_BTN_CLOSE, destination=page_arena)
# The round X in the top right corner closes one layer: the boss page goes back
# to the battle tab, the battle tab back to the lobby. Same asset, same spot.
page_battle.link(button=BOSS_BTN_CLOSE, destination=page_main)
page_boss.link(button=BOSS_BTN_CLOSE, destination=page_battle)
page_boss_dialog.link(button=BOSS_DIALOG_CLOSE, destination=page_boss)
page_boss_ticket.link(button=BOSS_TICKET_CLOSE, destination=page_boss)
page_menu.link(button=MENU_BTN_MAIL, destination=page_mail)
page_menu.link(button=MENU_BTN_TASK, destination=page_task)
page_menu.link(button=MAIN_BTN_SHOP, destination=page_shop)
page_menu.link(button=MENU_BTN_CLOSE, destination=page_main)
page_menu.link(button=ROUND_BTN, destination=page_round)
page_round.link(button=ARENA_BTN_CLOSE, destination=page_menu)
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

# The tab row of the battle page. The selected tab is drawn on a cream pill
# (mean 193~208), an idle one on the dark panel (mean 60~71).
BATTLE_TAB_NORMAL = Button(area=(130, 71, 272, 107), color=(0, 0, 0),
                           button=(130, 71, 272, 107), name='BATTLE_TAB_NORMAL')
BATTLE_TAB_SELECTED_MEAN = 130

# The boss raid puts its 「扫荡」 button under the spot above, so dismissing the
# reward popup there also starts another sweep. This point is the blank band at
# the top of the boss page (above the enemy panel) and under the popup it is
# black background, so one tap both closes the popup and hits nothing else. It is
# also where the victory page is tapped through.
BOSS_RESULT_TAP = Button(area=(600, 70, 680, 110), color=(0, 0, 0),
                         button=(600, 70, 680, 110), name='BOSS_RESULT_TAP')


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
             page_talk, page_affection, page_character_detail, page_character,
             page_battle, page_menu, page_pass, page_round, page_main)

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

        Returns:
            bool: If handled.
        """
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
        retry = Timer(1.5, count=3).start()
        while 1:
            self.device.screenshot()
            color = get_color(self.device.image, BATTLE_TAB_NORMAL.area)
            if sum(color) / 3 > BATTLE_TAB_SELECTED_MEAN:
                # The card list keeps the offset it was left at; put it back to
                # the first card so every card asset sits where it was cut.
                self.battle_scroll(forward=False)
                return True
            if retry.reached():
                retry.reset()
                self.device.click(BATTLE_TAB_NORMAL)
            if timeout.reached():
                logger.warning('Cannot switch the battle page back to 普通')
                return False

    def battle_scroll(self, forward, swipes=3, pause=0.9):
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
            swipes (int): How many drags to make. The list is short, three
                always reach the end from anywhere.
            pause (float): Seconds between drags.
        """
        if forward:
            p1, p2 = (1000, 400), (300, 400)
        else:
            p1, p2 = (300, 400), (1000, 400)
        for _ in range(swipes):
            self.device.swipe(p1=p1, p2=p2)
            self.device.sleep(pause)
        self.device.screenshot()

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

    def handle_reward_popup(self, timeout=8, button=None):
        """
        Dismiss the "已获得道具。" reward popup and wait until it is gone.

        Args:
            timeout (int, float): Seconds.
            button (Button): Where to tap. Defaults to the blank strip below the
                golden band; pages that have a clickable button there pass their
                own safe point.

        Returns:
            bool: If the popup left.
        """
        button = button or REWARD_POPUP_CLOSE
        retry = Timer(2, count=3).start()
        timeout = Timer(timeout).start()
        self.device.click(button)

        absent = 0
        while 1:
            self.device.screenshot()
            if self.appear(REWARD_POPUP_TITLE, offset=30):
                absent = 0
                # 限速：连点会撞上 12 次连点保护，也可能把上一击吃掉。
                if retry.reached():
                    retry.reset()
                    self.device.click(button)
            else:
                absent += 1
                if absent >= self.SETTLE_FRAMES:
                    return True
            if timeout.reached():
                logger.warning('Reward popup is still on screen')
                return False
