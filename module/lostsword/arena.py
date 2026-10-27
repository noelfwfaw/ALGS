from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import crop, get_color
from module.exception import GameStuckError
from module.logger import logger
from module.lostsword.assets import (ARENA_BTN_CHALLENGE_1,
                                     ARENA_BTN_CHALLENGE_2,
                                     ARENA_BTN_CHALLENGE_3,
                                     ARENA_BTN_CLOSE, ARENA_BTN_ENTER,
                                     ARENA_BTN_SEASON, ARENA_BTN_SKIP,
                                     ARENA_BTN_TEAM, ARENA_PROMO_TAG,
                                     ARENA_SEASON_CLAIM_ALL, ARENA_TITLE,
                                     ARENA_VICTORY, REWARD_POPUP_TITLE)
from module.lostsword.lostsword_ui import (BOSS_RESULT_TAP,
                                           LostswordUI,
                                           page_arena,
                                           page_battle)

"""
竞技场 (arena).

Flow observed in game:

    page_main  --底栏「战斗」-->  page_battle  --「竞技场」卡-->  page_arena
    page_arena  --「挑战」-->  page_arena_preview（我方 vs 对手）
    page_arena_preview  --「进入」-->  战斗  --右上「Skip」-->  VICTORY  --点屏幕-->  加载页  ->  page_arena
    page_arena  --右上圆 X-->  page_battle  --右上圆 X-->  page_main

Every battle ends with a fresh list of three opponents (measured twice: the
names, the ranks and even the promotion tag changed after a single fight), so the
loop does not track "which card is already done" - it re-reads the list and picks
again. That is also why the ticket counter, not the buttons, is what ends the
run.

Tickets: the counter in the top right corner is the number of fights left (10 is
the cap, shown as "10 Max"; otherwise a countdown to the next ticket sits under
it). One ticket per battle, one ticket back every 2 hours, so the task itself is
scheduled every ~2 hours and never for a whole day.

A promotion match (晋级赛) draws a red tag at the left edge of one of the three
cards, and it can be on any of them. When one is there, that card is fought
first: winning it promotes the tier and refreshes the whole list.
"""

ARENA_BTN_CHALLENGES = (ARENA_BTN_CHALLENGE_1, ARENA_BTN_CHALLENGE_2,
                        ARENA_BTN_CHALLENGE_3)

# The red 「晋级赛」 tag is 83x23 at x 357~440, its row depends on which card it
# sits on. The three cards are not exactly 180 pixels apart (185 and 179
# measured), so each band is a window to search in instead of a fixed box; they
# do not overlap, which is what keeps one tag from being seen twice.
ARENA_PROMO_BANDS = ((130, 205), (310, 385), (490, 565))
ARENA_PROMO_SIMILARITY = 0.85

# The ticket counter, top right. One digit while under 10, two when full.
ARENA_TICKET_AREA = (1005, 15, 1035, 38)
ARENA_TICKET_COLOR = (255, 255, 255)

# The season mission panel, opened from the left column of the arena list. Its
# three tabs each hold their own set of missions and their own 「全部领取」; the
# tab can be told apart by brightness (selected 181~202, idle 57~92) and the
# claim button by the same trick (enabled 208, greyed out 125).
ARENA_SEASON_TABS = (  # alas-lint: allow - a click point on a blank part of a panel
    ('参与', Button(area=(36, 71, 190, 113), color=(0, 0, 0),
                  button=(36, 71, 190, 113), name='ARENA_SEASON_TAB_1')),
    ('资源', Button(area=(329, 71, 391, 107), color=(0, 0, 0),
                  button=(329, 71, 391, 107), name='ARENA_SEASON_TAB_2')),
    ('段位', Button(area=(563, 71, 616, 107), color=(0, 0, 0),
                  button=(563, 71, 616, 107), name='ARENA_SEASON_TAB_3')),
)
ARENA_SEASON_TAB_MEAN = 140
ARENA_SEASON_CLAIM_MEAN = 165

# A battle is about 10 seconds after the skip, on top of the loading page.
ARENA_BATTLE_TIMEOUT = 180
# Safety net: 10 tickets plus the two that may come back while fighting.
ARENA_MAX_BATTLES = 12

ARENA_TICKET = Button(area=ARENA_TICKET_AREA, color=ARENA_TICKET_COLOR,  # alas-lint: allow - a click point on a blank part of a panel
                      button=ARENA_TICKET_AREA, name='ARENA_TICKET')


class LostswordArena(LostswordUI):
    """
    Spend the arena tickets: one battle per ticket, promotion matches first.

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
        logger.hr('Arena', level=1)
        self.ui_ensure(page_battle)
        self.battle_goto_normal()
        self.ui_ensure(page_arena)

        tickets = self.arena_ticket_count()
        logger.attr('Arena tickets', tickets)

        fought = 0
        while fought < ARENA_MAX_BATTLES:
            if tickets is not None and tickets <= 0:
                logger.info('No arena ticket left')
                break
            index = self.arena_pick()
            if index == 0:
                logger.warning('No challenge button on the arena list')
                break
            if not self.arena_fight(index):
                break
            fought += 1
            tickets = self.arena_ticket_count()
            logger.attr('Arena tickets', tickets)

        logger.info(f'Arena battles: {fought}')
        claimed = self.arena_season_claim()
        logger.info(f'Season missions claimed: {claimed}')
        self.ui_goto_main()
        # A ticket takes four hours to come back, so following the refill
        # countdown would mean six runs a day for six fights - each one costs
        # more in loading screens than the fight itself. Once a day is enough:
        # the tickets pile up in between and are all spent in one go here.
        self.config.task_delay(server_update=True)

    def arena_season_claim(self):
        """
        Claim the season missions of the arena, all three tabs.

        The 「全部领取」 button belongs to the open tab only - claiming one tab
        leaves the other two untouched (verified: after claiming 参与 the panel
        moved to 段位 with its own 「领取」 buttons still there). The button is
        always drawn, greyed out when the tab has nothing to claim, so the
        colour decides whether pressing it is worth a popup wait.

        Pages:
            in: page_arena
            out: page_arena

        Returns:
            int: How many tabs paid out.
        """
        logger.hr('Season missions', level=2)
        self.ui_ensure(page_arena)
        if self.wait_until_appear(ARENA_BTN_SEASON, offset=30, timeout=2):
            self.device.click(ARENA_BTN_SEASON)
        else:
            logger.warning('Season mission entry not found')
            return 0

        if not self.wait_overlay(ARENA_SEASON_CLAIM_ALL, timeout=10):
            logger.warning('Season mission panel did not open')
            return 0

        claimed = 0
        for name, tab in ARENA_SEASON_TABS:
            if not self.arena_season_tab(tab):
                continue
            if not self.arena_season_claimable():
                logger.info(f'{name}: nothing to claim')
                continue
            logger.info(f'{name}: claim all')
            # The tab has just been switched, and a tap that lands while the
            # list is still sliding in is swallowed (measured: the first press
            # after opening 段位 produced nothing, the same press by hand did).
            for attempt in range(2):
                if self.appear(ARENA_SEASON_CLAIM_ALL, offset=30):
                    self.device.click(ARENA_SEASON_CLAIM_ALL)
                if self.wait_overlay(REWARD_POPUP_TITLE, timeout=6):
                    self.handle_reward_popup()
                    claimed += 1
                    break
                if attempt == 0:
                    logger.info(f'{name}: no popup, press 全部领取 again')
            else:
                logger.warning(f'{name}: no reward popup after 全部领取')

        # The panel is left through its own X: the graph routes it back to the
        # list, so a stray panel cannot swallow the next run.
        if self.appear(ARENA_SEASON_CLAIM_ALL, offset=30):
            self.device.click(ARENA_BTN_CLOSE)
            self.wait_overlay_gone(ARENA_SEASON_CLAIM_ALL, timeout=8)
        return claimed

    def arena_season_tab(self, tab, timeout=6):
        """
        Open one tab of the season panel.

        Args:
            tab (Button): Tab to open.
            timeout (int, float): Seconds.

        Returns:
            bool: If the tab is the open one.
        """
        timeout = Timer(timeout).start()
        retry = Timer(1.5).start()

        for _ in self.loop():
            # End - this tab is the lit one.
            color = get_color(self.device.image, tab.area)
            if sum(color) / 3 > ARENA_SEASON_TAB_MEAN:
                # Switching repaints the list below, and the claim button is read
                # for its brightness, so let the panel stop changing first.
                self.wait_until_still(ARENA_SEASON_CLAIM_ALL.area, timeout=3)
                return True

            # Click - the tab is a plain area of the panel with no template of
            # its own, which `appear()` would need, so the panel is what guards
            # the press; the brightness above is what decides whether it landed.
            if retry.reached():
                retry.reset()
                if self.appear(ARENA_SEASON_CLAIM_ALL, offset=30):
                    self.device.click(tab)

            if timeout.reached():
                logger.warning(f'{tab.name} did not open')
                return False

    def arena_season_claimable(self):
        """
        Whether 「全部领取」 is the enabled one.

        Returns:
            bool: If the button is drawn on the cream background.
        """
        color = get_color(self.device.image, ARENA_SEASON_CLAIM_ALL.area)
        return sum(color) / 3 > ARENA_SEASON_CLAIM_MEAN

    def arena_ticket_count(self):
        """
        Read the ticket counter at the top right.

        `Digit` answers 0 both for "no ticket" and for "nothing drawn here", and
        the counter is one of the last things painted after the list slides in:
        measured right after a battle it read 0 while the list showed 5. A zero
        is therefore confirmed on a later frame before it ends the run.

        Returns:
            int or None: Tickets left, None when it cannot be read.
        """
        value = self._arena_ticket_ocr()
        if value:
            return value

        # A zero is confirmed on later frames before it ends the run.
        timeout = Timer(3).start()
        for _ in self.loop():
            value = self._arena_ticket_ocr()
            if value:
                return value
            if timeout.reached():
                return value
        return value

    def _arena_ticket_ocr(self):
        """
        One read of the ticket counter.

        Returns:
            int or None: Tickets left, None when it cannot be read.
        """
        from module.ocr.ocr import Digit

        ocr = Digit(ARENA_TICKET, letter=ARENA_TICKET_COLOR, threshold=128,
                    name='ARENA_TICKET')
        value = ocr.ocr(self.device.image)
        if isinstance(value, tuple):
            value = value[0] if value else None
        return value

    def arena_promo_index(self):
        """
        Which card carries the 「晋级赛」 tag.

        The tag is small and its row moves with the card, so the tag is searched
        for in three separate horizontal bands rather than matched at a fixed
        point. `Button.match()` is not used here: it swaps its arguments around
        the template, which turns a "search this band" into a meaningless score.

        Returns:
            int: 1 to 3, or 0 when no card is a promotion match.
        """
        ARENA_PROMO_TAG.ensure_template()
        for index, (y1, y2) in enumerate(ARENA_PROMO_BANDS, 1):
            region = crop(self.device.image, (354, y1, 443, y2))
            if region.shape[0] < ARENA_PROMO_TAG.image.shape[0]:
                continue
            import cv2
            res = cv2.matchTemplate(region, ARENA_PROMO_TAG.image, cv2.TM_CCOEFF_NORMED)
            _, similarity, _, _ = cv2.minMaxLoc(res)
            if similarity > ARENA_PROMO_SIMILARITY:
                logger.info(f'Promotion match on card {index} ({similarity:.2f})')
                return index
        return 0

    def arena_pick(self):
        """
        The card to fight: the promotion match when there is one, else the first
        card whose 「挑战」 button is still there.

        Returns:
            int: 1 to 3, or 0 when nothing can be fought.
        """
        self.device.screenshot()
        index = self.arena_promo_index()
        if index and self.appear(ARENA_BTN_CHALLENGES[index - 1], offset=30):
            return index
        for index, button in enumerate(ARENA_BTN_CHALLENGES, 1):
            if self.appear(button, offset=30):
                return index
        return 0

    def arena_fight(self, index):
        """
        Fight one arena battle and come back to the list.

        Pages:
            in: page_arena
            out: page_arena

        Args:
            index (int): Which card to fight, 1 to 3.

        Returns:
            bool: If a battle was fought to the end.
        """
        logger.hr(f'Fight card {index}', level=2)
        # The list was read on the frame before, but it can repaint under the
        # press; a button that is gone again means the list moved and nothing can
        # be fought from here.
        if self.wait_until_appear(ARENA_BTN_CHALLENGES[index - 1], offset=30, timeout=3):
            self.device.click(ARENA_BTN_CHALLENGES[index - 1])
        else:
            logger.warning('The challenge button left the list')
            return False

        if not self.wait_overlay(ARENA_BTN_TEAM, timeout=8):
            # No ticket to pay with, or the list moved under the click: either
            # way nothing can be fought from here.
            logger.warning('Arena battle did not open')
            return False

        return self.arena_battle()

    def arena_battle(self, timeout=ARENA_BATTLE_TIMEOUT):
        """
        Enter the battle, skip it, and tap through the victory page.

        Pages:
            in: page_arena_preview
            out: page_arena

        Args:
            timeout (int, float): Seconds to wait for the battle to end.

        Raises:
            GameStuckError: If the battle does not end in time.
        """
        timeout = Timer(timeout).start()
        report = Timer(30).start()
        # `reached()` is True until the timer is started, so the first frame on
        # the versus page presses 「进入」 at once and the next tries are 5s apart.
        enter_retry = Timer(5).start()
        enter_tries = 0
        skipped = False
        skip_retry = Timer(3).start()

        for _ in self.loop():
            # A battle is a live scene that barely changes for minutes, which
            # reads as a frozen game to the stuck detector.
            self.device.stuck_record_clear()

            if self.appear(ARENA_VICTORY, offset=30):
                logger.info('Battle won')
                self.device.click(BOSS_RESULT_TAP)
                # The result page is followed by the client loading screen.
                if not self.wait_overlay(ARENA_TITLE, timeout=40):
                    # Measured: some battles drop back to the lobby instead of
                    # the list (the third of five did), and the battle page may
                    # come back on another tab. Walk in from the lobby: that
                    # resets the tab and anything the battle left behind.
                    logger.info('Not at the arena list, walk back into it')
                    self.ui_goto_main()
                    self.ui_ensure(page_battle)
                    self.battle_goto_normal()
                    self.ui_ensure(page_arena)
                return True

            if self.appear(ARENA_BTN_SKIP, offset=30):
                # The skip button is only drawn once the battle is running; the
                # result is decided the moment it is pressed.
                if skip_retry.reached():
                    skip_retry.reset()
                    if not skipped:
                        logger.info('Skip the battle')
                        skipped = True
                    self.device.click(ARENA_BTN_SKIP)
                continue

            if self.appear(ARENA_TITLE, offset=30):
                # A battle that ends without the victory page (or one that was
                # already skipped from a previous run) lands back on the list.
                logger.info('Back at the arena list')
                return True

            if self.appear(ARENA_BTN_TEAM, offset=30):
                # Still on the versus page: the first tap can be eaten by the
                # page sliding in. Retry slowly - the loading screen follows the
                # press, and a burst of taps would spend several tickets once
                # the battle is up.
                if enter_retry.reached() and enter_tries < 3:
                    enter_retry.reset()
                    enter_tries += 1
                    if enter_tries > 1:
                        logger.info('Versus page still up, press 进入 again')
                    self.device.click(ARENA_BTN_ENTER)

            if report.reached():
                report.reset()
                logger.info(f'Still in battle, {int(timeout.current_time())}s elapsed')
            if timeout.reached():
                logger.warning('Arena battle did not end in time')
                raise GameStuckError('Arena battle did not end in time')
