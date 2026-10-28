from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.lostsword.assets import (DUNGEON_BTN_BACK, DUNGEON_BTN_CONFIRM,
                                     DUNGEON_BTN_MATCH, DUNGEON_CLEAR,
                                     DUNGEON_DIALOG_TITLE, DUNGEON_TITLE)
from module.lostsword.lostsword_ui import (LostswordUI, page_battle,
                                          page_dungeon)

"""
Squad dungeon (小队副本).

Flow observed in game:

    page_main -- bottom bar 「战斗」 --> page_battle (普通 tab, the dungeon card is
                                          the third of the row)
    page_battle -- dungeon card --> page_dungeon (黑龙·尼德霍格 / KING)
    page_dungeon -- 「开始匹配 1/1」 --> 「是否前往小队副本房间?」 --> 「确认」
    -> client loading page (正在火热招募队友中… 20)
    -> battle (auto played, no preparation) -> 「CLEAR」 result page
    -> 「返回」 --> page_dungeon

The recruiting step never fails: empty slots are filled by NPCs, so the room
always opens and the countdown only makes it shorter. There is no "no teammate
found" state to wait for, nothing to retry and nothing to cancel - a press on
「确认」 is followed by a battle in every case, and the only question left is
when the battle is over.
    page_dungeon -- top right round X --> page_battle -- round X --> page_main

One try a day. The detail page is built exactly like the boss raid one (same
「队伍编排」 button, same left column), so it is matched by its boss name instead;
and the card of the battle page only exists under 「普通」.

The result page of this mode is 「CLEAR」, not the 「VICTORY」 of the solo modes,
which is why it needs its own asset rather than reusing BOSS_VICTORY.

Whether today's try is left is read from the match button: it is drawn as
「开始匹配 1/1」 while a try is left (match 1.00) and as "ticket count + 开始匹配"
once it is used up (match below 0.5).
"""

# The detail page leaving after 「确认」 is the sign that the run started. The
# recruiting countdown is 20 seconds and NPCs shorten it, so this only has to
# cover a slow emulator plus the client loading page.
DUNGEON_START_TIMEOUT = 30

# Then the battle runs on its own. The boss raid one has measured up to 240
# seconds on the same engine and the same kind of boss, so the ceiling is the
# same as that task's; a frame drop of the emulator is the only thing that ever
# gets close to it.
DUNGEON_TIMEOUT = 600


class LostswordDungeon(LostswordUI):
    """
    Spend the daily squad dungeon try and wait for the battle to clear.

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
        logger.hr('Squad dungeon', level=1)
        self.ui_ensure(page_battle)
        self.battle_goto_normal()
        self.ui_ensure(page_dungeon)

        if self.dungeon_available():
            self.dungeon_fight()
        else:
            logger.info('No squad dungeon try left for today')

        self.ui_goto_main()
        # One try a day, at the daily reset of this game (00:00).
        self.config.task_delay(server_update=True)

    def dungeon_available(self):
        """
        Whether the daily try is still there.

        Returns:
            bool: If 「开始匹配」 is the version with a try count.
        """
        return self.wait_until_appear(DUNGEON_BTN_MATCH, offset=30, timeout=2)

    def dungeon_fight(self, timeout=DUNGEON_TIMEOUT):
        """
        Confirm the match and wait for the CLEAR screen, then leave it.

        Pages:
            in: page_dungeon
            out: page_dungeon

        Args:
            timeout (int, float): Seconds to wait for the battle.

        Returns:
            bool: If a battle was fought to the end.

        Raises:
            GameStuckError: If the battle does not end in time.
        """
        logger.hr('Squad dungeon battle', level=2)
        # A previous run may have left this button cooling down, and
        # `appear_then_click` is False both for "not there" and for "throttled".
        self.interval_clear(DUNGEON_BTN_MATCH)
        if self.wait_until_appear(DUNGEON_BTN_MATCH, offset=30, timeout=2):
            self.device.click(DUNGEON_BTN_MATCH)
        else:
            logger.warning('Match button not found')
            return False
        if not self.wait_overlay(DUNGEON_DIALOG_TITLE, timeout=8):
            logger.warning('Match confirm dialog did not open')
            return False

        # The dialog is matched from its first fading frame and a tap during the
        # fade in is lost, so the confirm is only pressed once it is drawn.
        if not self.wait_overlay_settle(DUNGEON_DIALOG_TITLE, timeout=6):
            logger.warning('Match confirm dialog did not settle')
            return False
        if self.appear(DUNGEON_BTN_CONFIRM, offset=30):
            self.device.click(DUNGEON_BTN_CONFIRM)
        else:
            logger.warning('Match confirm button not found')
            return False

        # The dialog closing is the only proof the press was taken: the detail
        # page behind it does not move, so the page being on screen cannot tell
        # "accepted" from "still waiting for the press". Leaving while the
        # dialog is up would click into the dialog and, two seconds later, into
        # whatever the game decided to do with it.
        if not self.wait_overlay_gone(DUNGEON_DIALOG_TITLE, timeout=8):
            logger.warning('The confirm press was not taken, leaving the match alone')
            return False

        # The run has started once the detail page leaves. Right after the
        # confirm it is still fully drawn (the dialog covered its middle only),
        # which is why a plain `appear(DUNGEON_TITLE)` in the loop below read
        # "back at the dungeon page, battle is over" 62 ms after the press and
        # walked home through a battle that had just begun.
        started = self.wait_until_disappear(
            DUNGEON_TITLE, offset=30, timeout=DUNGEON_START_TIMEOUT, settle=2)
        if started:
            logger.info('Squad dungeon started')
        else:
            # Not an error: the recruiting panel may be drawn over a page that
            # still matches underneath. Keep watching instead of walking away -
            # a task that leaves here clicks into a live battle and then reports
            # an unknown page for a minute.
            logger.warning('The detail page is still up, watching it for the result')

        # Recruiting, the client loading page and the battle are all on their
        # own from here: nothing is clicked until the result page.
        timeout = Timer(timeout).start()
        report = Timer(30).start()
        for _ in self.loop():
            # A recruiting room and an auto battle are live scenes that barely
            # change, which reads as a frozen game to the stuck detector.
            self.device.stuck_record_clear()

            # End - the result page.
            if self.appear(DUNGEON_CLEAR, offset=30):
                logger.info('Squad dungeon cleared')
                break

            if self.appear(DUNGEON_TITLE, offset=30):
                # End - the detail page is back without a result page, so the
                # run ended in a way that leaves nothing to collect. Only
                # believed once the page has been watched leaving above.
                if started:
                    logger.info('Back at the detail page, the run is over')
                    return True
            elif not started:
                logger.info('Squad dungeon started')
                started = True

            if timeout.reached():
                logger.warning('Squad dungeon did not finish in time')
                raise GameStuckError('Squad dungeon did not end in time')

            if report.reached():
                report.reset()
                logger.info(f'Still in the dungeon, {int(timeout.current_time())}s elapsed')

        self.dungeon_leave_result()
        return True

    def dungeon_leave_result(self, timeout=40):
        """
        Press 「返回」 on the result page until the detail page is back.

        The result page fades in and swallows the press aimed at it, so one
        press is a coin flip; and the client loading page that follows keeps the
        button away for seconds at a time, so its absence is not an error
        either. The press is therefore repeated from the state loop.

        Pages:
            in: page_dungeon_result
            out: page_dungeon

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If the detail page is back.
        """
        timeout = Timer(timeout).start()
        retry = Timer(3).start()
        for _ in self.loop():
            self.device.stuck_record_clear()

            # End - the detail page is back, either because the loading page
            # before it is over or because the press already worked.
            if self.appear(DUNGEON_TITLE, offset=30):
                return True

            # Click - 「返回」 is the only way out of the result page.
            if retry.reached():
                retry.reset()
                if self.appear(DUNGEON_BTN_BACK, offset=30):
                    logger.info('Leave the result page')
                    self.device.click(DUNGEON_BTN_BACK)

            if timeout.reached():
                logger.warning('Did not return to the squad dungeon page')
                return False
