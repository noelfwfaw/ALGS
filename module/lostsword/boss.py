from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.lostsword.assets import (BOSS_BEST_SCORE, BOSS_BTN_ENTER,
                                     BOSS_BTN_SWEEP, BOSS_BTN_SWEEP_CONFIRM,
                                     BOSS_BTN_TEAM, BOSS_DIALOG_CLOSE,
                                     BOSS_DIALOG_TITLE, BOSS_TICKET_CLOSE,
                                     BOSS_TICKET_TITLE, BOSS_VICTORY,
                                     REWARD_POPUP_TITLE)
from module.lostsword.lostsword_ui import (BOSS_RESULT_TAP, LostswordUI,
                                          page_battle, page_boss)

"""
Boss raid (领主突袭).

Flow observed in game:

    page_main  -- bottom bar 「战斗」 -->  page_battle (普通 tab, the raid card is
                                             the first of the row)
    page_battle  -- raid card -->  page_boss (阿格尼丝 / solo raid)
    page_boss  -- 「进入」 -->  loading page -> battle (auto played) -> VICTORY
                                -> tap -> loading page -> page_boss
    page_boss  -- 「扫荡」 -->  「是否进行扫荡?」 --> 「确认」 --> 已获得道具。 popup
    page_boss  -- top right round X -->  page_battle  -- round X -->  page_main

The mode gives three tries a day, and 进入 and 扫荡 draw from the same pool:
the counter on both buttons drops by one per run. The intended daily routine is
one real battle (it is what feeds the damage ranking) and then sweep the rest, so
this task fights once and sweeps until the free tries are gone.

Whether today's battle is done is read from the "最高分数" row above the enemy
panel: it does not exist before the first run of the day (similarity 0.11) and
stays afterwards (1.00). The counter itself is a tiny "x/3" next to the button
label, too small to OCR reliably, and the two buttons share it anyway.

Once the free tries are used up the two buttons switch to a different layout (the
ticket count moves to the left of the label), which drops the match of
`BOSS_BTN_SWEEP` from 1.00 to 0.31. That is the natural end of the sweep loop, and
it also means the task never spends the paid tickets.
"""

# A battle takes 80~270 seconds on top of the client loading page (two runs of
# the same day measured 78s and over 240s), so the wait is generous.
BOSS_BATTLE_TIMEOUT = 600
# Three free tries a day, one of them is the battle itself.
BOSS_SWEEP_TRIES = 4


class LostswordBoss(LostswordUI):
    """
    Fight the boss raid once a day and sweep the rest of the free tries.

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
        logger.hr('Boss raid', level=1)
        self.ui_ensure(page_battle)
        self.battle_goto_normal()
        self.ui_ensure(page_boss)
        self.boss_dismiss_dialogs()

        if self.boss_fought_today():
            logger.info('Already fought today, skip the battle')
        else:
            self.boss_battle()

        if self.config.LostswordBoss_Sweep:
            swept = self.boss_sweep_all()
            logger.info(f'Swept {swept} time(s)')
        else:
            logger.info('Sweep is off, the rest of the tries are left alone')

        self.ui_ensure(page_boss)
        self.boss_dismiss_dialogs()
        self.ui_goto_main()
        # One pass a day, at the daily reset of this game (00:00, pinned in
        # argument/override.yaml).
        self.config.task_delay(server_update=True)

    def boss_fought_today(self):
        """
        Whether today's battle is already fought.

        Read from the "最高分数" row, which does not exist before the first run
        of the day and stays afterwards. The page is still sliding in when
        `ui_ensure` returns, and on that frame the row has not been drawn yet
        (measured: absent 10ms after the page arrived, present a second later),
        so the absence is only believed after a bounded wait instead of on the
        first frame.

        Returns:
            bool: If the battle was already fought.
        """
        return self.wait_until_appear(BOSS_BEST_SCORE, offset=30, timeout=2)

    def boss_battle(self, timeout=BOSS_BATTLE_TIMEOUT):
        """
        Fight today's boss raid once and come back to its page.

        The battle is auto played, so nothing is clicked between entering and the
        result page; the screen barely changes for minutes, which the stuck
        detector of the framework would read as a frozen game.

        Pages:
            in: page_boss
            out: page_boss

        Args:
            timeout (int, float): Seconds to wait for the battle to end.

        Raises:
            GameStuckError: If the battle does not end in time.
        """
        logger.hr('Boss battle', level=2)
        # Guard against a misread of the "最高分数" row: with no free try left the
        # button is repainted as the ticket layout (match 0.40) and pressing it
        # would spend a Boss Raid Ticket of the user.
        # A previous run may have left this button cooling down, and
        # `appear_then_click` is False both for "not there" and for "throttled".
        self.interval_clear(BOSS_BTN_ENTER)
        entered = self.appear_then_click(BOSS_BTN_ENTER, offset=30, interval=3)
        if not entered:
            logger.info('No free try left, skip the battle')
            return

        # The client loading page and the battle itself both cover the
        # 「队伍编排」 button, so the page going away is the start of the battle.
        if not self.wait_until_disappear(BOSS_BTN_TEAM, offset=30, timeout=60, settle=2):
            logger.warning('Boss battle did not start')
            raise GameStuckError('Boss battle did not start in time')
        logger.info('Battle started')

        timeout = Timer(timeout).start()
        report = Timer(30).start()
        for _ in self.loop():
            # A battle screen is a live 3D scene that barely changes for
            # minutes, which reads as a frozen game to the stuck detector.
            self.device.stuck_record_clear()

            # End - the raid page is back, either after the victory page or
            # after a run that ended without one (defeat).
            if self.appear(BOSS_BTN_TEAM, offset=30):
                logger.info('Battle finished, back at the boss raid page')
                return
            if timeout.reached():
                logger.warning('Boss battle did not reach the victory page')
                raise GameStuckError('Boss battle did not end in time')

            # Click - the victory page leaves on a tap and plays a client
            # loading page right after it, so it is tapped until the raid page
            # is back rather than once.
            if self.appear(BOSS_VICTORY, offset=30, interval=2):
                logger.info('Battle won, tap through the victory page')
                self.device.click(BOSS_RESULT_TAP)
                continue

            if report.reached():
                report.reset()
                logger.info(f'Still fighting, {int(timeout.current_time())}s elapsed')

    def boss_sweep_all(self):
        """
        Sweep until the free tries are used up.

        Pages:
            in: page_boss
            out: page_boss

        Returns:
            int: How many sweeps ran.
        """
        swept = 0
        for _ in range(BOSS_SWEEP_TRIES):
            self.ui_ensure(page_boss)
            self.boss_dismiss_dialogs()
            # The button keeps its look while there are free tries and switches
            # to the ticket layout once there are none, so a bounded wait that
            # comes back empty is the end of the loop.
            if not self.wait_until_appear(BOSS_BTN_SWEEP, offset=30, timeout=2):
                logger.info('No free sweep left')
                break
            if not self.boss_sweep_once():
                break
            swept += 1
        return swept

    def boss_dismiss_dialogs(self, timeout=5):
        """
        Close any dialog left open on the boss page.

        Both dialogs cover only the middle of the page: the 「队伍编排」 button
        below them still matches, so `ui_goto` believes it already arrived at
        `page_boss` and leaves the dialog open. Closing it is left to the
        callers of the graph instead.

        Pages:
            in: page_boss
            out: page_boss

        Args:
            timeout (int, float): Seconds to wait for a dialog to fade out.

        Returns:
            bool: If a dialog was closed.
        """
        closed = False
        self.device.screenshot()
        for title, close in ((BOSS_TICKET_TITLE, BOSS_TICKET_CLOSE),
                             (BOSS_DIALOG_TITLE, BOSS_DIALOG_CLOSE)):
            if self.appear(title, offset=30):
                logger.info(f'{title.name} is open, close it')
                self.device.click(close)
                self.wait_overlay_gone(title, timeout=timeout)
                closed = True
        return closed

    def boss_sweep_once(self):
        """
        Sweep once: open the dialog, confirm it, claim the popup.

        Pages:
            in: page_boss
            out: page_boss

        Returns:
            bool: If a reward popup was claimed.
        """
        # Only touch the button while it is the free-try one. With no try left it
        # is repainted as "ticket count + 扫荡", pressing it opens the 「一键扫荡」
        # dialog, and one more tap there spends the user's Boss Raid Tickets.
        self.interval_clear(BOSS_BTN_SWEEP)
        sweeping = self.appear_then_click(BOSS_BTN_SWEEP, offset=30, interval=3)
        if not sweeping:
            logger.info('No free sweep left')
            return False

        logger.info('Sweep the boss raid')
        # The dialog is matched from its first fading frame and a tap during the
        # fade in is lost, so the confirm button is only pressed once the panel
        # is fully drawn.
        if not self.wait_overlay_settle(BOSS_DIALOG_TITLE, timeout=6):
            logger.warning('Sweep dialog did not open')
            return False
        self.interval_clear(BOSS_BTN_SWEEP_CONFIRM)
        confirmed = self.appear_then_click(BOSS_BTN_SWEEP_CONFIRM, offset=30, interval=3)
        if not confirmed:
            logger.warning('Sweep confirm button not found')
            self.boss_close_dialog()
            return False

        if self.wait_until_appear(REWARD_POPUP_TITLE, offset=30, timeout=10):
            # The popup is dismissed on the blank part of its own panel: the
            # shared close point sits on the 扫荡 button of this page, and the
            # tap would be taken by it as well.
            self.handle_reward_popup(button=BOSS_RESULT_TAP)
            return True

        logger.warning('No reward popup after confirming the sweep')
        # Either the confirm tap was swallowed or the tries ran out (the game
        # just ignores the tap). A dialog left open would eat every later click.
        self.boss_close_dialog()
        return False

    def boss_close_dialog(self, timeout=5):
        """
        Close the "是否进行扫荡?" dialog without sweeping.

        Pages:
            in: page_boss_dialog
            out: page_boss

        Args:
            timeout (int, float): Seconds to wait for the dialog to fade out.

        Returns:
            bool: If the dialog left.
        """
        if self.appear_then_click(BOSS_DIALOG_CLOSE, offset=30, interval=3):
            return self.wait_overlay_gone(BOSS_DIALOG_TITLE, timeout=timeout)
        return False
