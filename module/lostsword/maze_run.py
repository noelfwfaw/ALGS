"""The auto run of the maze, from 「自动进行」 to the last room.

The map plays itself: no battle screen, no click, the floors go up while the
camera pans (measured: 1 层 to 16 层 in about fifteen seconds). What is left is
the waiting - and the three ways the game interrupts itself:

- a story scene, which a tap in the middle advances;
- 「女神的祝福」, a choice of three cards, answered by picking a 增益型 one;
- the last room, which the auto run does not enter - see `maze_fight_boss`.

A run is over when the map stops moving: two frames of a running maze always
differ, a finished one is the same image.
"""

import numpy as np

from module.base.timer import Timer
from module.logger import logger
from module.lostsword.assets import (AFFECTION_TAP, BOSS_VICTORY,
                                     MAZE_AUTO_TITLE, MAZE_BTN_AUTO,
                                     REWARD_POPUP_TITLE)
from module.lostsword.page import page_battle, page_main
from module.lostsword.utils import match, read_text

# Every few rooms the game stops at 「女神的祝福」: three cards and a 「选择」
# bar, dark map behind it (mean 67) against the cream bar (mean 189). The
# brightness check alone once matched any bright page (2026-10-27).
MAZE_CHOICE_BAR = (590, 625, 700, 660)
MAZE_CHOICE_MEAN = 120
# The three cards of that screen, and the label of each one's kind.
MAZE_CHOICE_CARDS = (340, 636, 940)
MAZE_CHOICE_CARD_Y = 384
MAZE_CHOICE_LABELS = ((270, 348, 412, 378), (566, 348, 708, 378),
                      (870, 348, 1012, 378))
MAZE_CHOICE_CONFIRM = (640, 653)
# Story scenes of the maze show the conversation arrow at the bottom right, but
# there it is decoration: the whole screen advances, the press goes to the middle.
MAZE_TALK_TAP = (640, 360)
MAZE_TALK_REGION = (1150, 600, 1280, 720)
# The last room - the Minotauros King - is not part of the auto run: the map
# stops in front of it (measured: the run went to floor 50 of 50) and pressing
# the King node asks 「是否移动?」, then the sortie page starts the fight.
MAZE_BOSS_NODE = (1064, 384)
# Tapping the boss room raises 「感受到怪物的气息。是否移动?」 with a checkbox that
# stops the question from coming back for the rest of the session; a tap on the
# node then moves straight on and the sortie page comes up without the dialog.
MAZE_MOVE_CHECKBOX = (488, 432)
MAZE_MOVE_CONFIRM = (640, 520)
MAZE_MOVE_ASK_AREA = (520, 300, 780, 375)
# The boss room opens the usual sortie page: 「出发」 bottom right (measured
# 2026-11-04, the button spans (886, 643) - (1197, 687)).
MAZE_BOSS_START = (996, 664)
MAZE_SORTIE_AREA = (900, 640, 1180, 690)
# The 「自动进行迷宫」 panel: its own 「自动进行」 button sits in the middle of
# the bottom bar. Measured 2026-11-04 on V1.610.1: the panel sits higher than
# before, the old (640, 600) landed under the button and only dismissed it.
MAZE_PANEL_POINT = (640, 538)
# A run is over when the map stops moving; two frames of a running maze always
# differ (the camera pans), a finished one is the same image.
MAZE_STILL_FRAMES = 3
MAZE_STILL_DIFF = 1.0
# Its result page: 「VICTORY」 over the loot, 「点击屏幕」 at the bottom.
MAZE_VICTORY_REGION = (0, 0, 1280, 300)
# When the boss room is down the map shows 「完成」 over the head of the maze: the
# run is over and there is nothing left to wait for.
MAZE_DONE_AREA = (580, 25, 700, 65)
MAZE_VICTORY_TAP = (640, 400)


class MazeAutoRun:
    """
    Start the auto run and carry it to the end of the week.

    Mixed into `LostswordMaze`. The framework supplies `self.loop()`,
    `self.device`, `ui_get_current_page()` and `ui_page_appear()`; the composed
    class adds `maze_on_map()` (in `maze.py`), `maze_set_priorities()`
    (`MazePriority`) and `tap_point()` / `handle_reward_popup()` (`LostswordUI`).
    """

    def maze_auto_start(self, timeout=12):
        """
        Press 「自动进行」 and confirm the panel it raises.

        The button looks the same when the weekly run is spent, so the panel is
        what tells: it comes up when a run can be started, and nothing happens
        when it cannot. The press is repeated until the panel shows - pressing
        it twice is harmless, it only raises the same panel.

        Pages:
            in: page_maze
            out: page_maze

        Args:
            timeout (int, float): Seconds to wait for the panel.

        Returns:
            bool: If a run was started.
        """
        x1, y1, x2, y2 = MAZE_BTN_AUTO.button
        button = ((x1 + x2) // 2, (y1 + y2) // 2)

        retry = Timer(2, count=2).start()
        for _ in self.loop(timeout=timeout):
            # The tap is repeated on an interval instead of trusted to the first
            # frame: the map is still panning when the task arrives and eats a
            # press that lands before it settles.
            self.device.stuck_record_clear()
            if self.maze_panel_appear():
                break
            if retry.reached():
                retry.reset()
                self.tap_point(*button)
        else:
            logger.info('The auto run panel did not show, nothing to start')
            return False

        self.maze_set_priorities()

        logger.info('Confirm the auto run')
        timeout = Timer(10).start()
        retry = Timer(2, count=2).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if not self.maze_panel_appear():
                return True
            if retry.reached():
                retry.reset()
                self.tap_point(*MAZE_PANEL_POINT)
            if timeout.reached():
                logger.warning('The panel did not go away')
                return False

    def maze_settle(self, timeout=240):
        """
        Get out of whatever the auto run left on screen.

        The task may start while a previous run is still going: the map then
        shows 「正在自动进行...」 instead of its 「自动进行」 button, and the
        game may sit on a story line or a choice. None of those pages is one of
        the known ones, so they are answered here until the map is back. A
        normal page ends the wait immediately - without that check a bright page
        used to read as a choice screen and the loop answered a choice that did
        not exist until it was killed (2026-10-27).

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If a known page is reachable afterwards.
        """
        timeout = Timer(timeout).start()
        choice_gave_up = False
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.maze_on_map() or self.maze_panel_appear() or self.maze_finished():
                return True
            # A plain page of this game is nothing to settle: the maze has not
            # been entered yet, so the task can go on with its own flow.
            if self.ui_page_appear(page_main) or self.ui_page_appear(page_battle):
                return True
            if self.maze_victory_appear():
                self.tap_point(*MAZE_VICTORY_TAP)
                continue
            if self.maze_talk_appear():
                self.tap_point(*MAZE_TALK_TAP)
                continue
            if not choice_gave_up and self.maze_choice_appear():
                if not self.maze_choose():
                    # Answering it failed three times; hammering it further
                    # only keeps the task on a screen it cannot read.
                    logger.warning('The choice screen does not answer, give up')
                    choice_gave_up = True
                continue
            if self.reward_appear():
                self.handle_reward_popup()
                continue
            try:
                self.ui_get_current_page()
                return True
            except Exception:
                pass
            if timeout.reached():
                return False

    def reward_appear(self):
        """
        Whether the 「已获得道具。」 popup is on screen.

        Returns:
            bool: If it is there.
        """
        return match(self.device.image, REWARD_POPUP_TITLE,
                     (0, 0, 1280, 720)) > 0.85

    def maze_finished(self):
        """
        Whether the map says 「完成」, meaning the maze has been cleared.

        Returns:
            bool: If the maze is done.
        """
        return '完成' in read_text(self.device.image, MAZE_DONE_AREA)

    def maze_victory_appear(self):
        """
        Whether the result page of the last room is on screen.

        Returns:
            bool: If 「VICTORY」 is there.
        """
        return match(self.device.image, BOSS_VICTORY,
                     MAZE_VICTORY_REGION) > 0.85

    def maze_talk_appear(self):
        """
        Whether a maze story scene is on screen.

        Returns:
            bool: If the continue arrow is at the bottom right.
        """
        return match(self.device.image, AFFECTION_TAP, MAZE_TALK_REGION) > 0.85

    def maze_fight_boss(self, timeout=240):
        """
        Fight the last room of the maze.

        Called when the map has stopped moving in front of the Minotauros King
        (the run reached floor 50 of 50 that way, 2026-11-04). The King node
        asks 「是否移动?」, its 确认 moves the party in, the sortie page starts
        the fight; the old party-check presses ahead of the node are gone, the
        node works alone. Every step waits for its own screen instead of
        trusting a press - the map's idle animation alone exceeds the "screen
        moved" threshold, which let a stale chain "succeed" against nothing.
        The fight cannot be skipped, so the victory page is waited for here:
        the generic wait loop would read the static loading screen as "the run
        is over".

        Returns:
            bool: If the fight was fought and its result page answered.
        """
        logger.hr('Start the last room', level=2)
        # Press the King node until the move dialog asks or the sortie page is
        # already up (the checkbox silences the question for the session).
        asked = False
        timer = Timer(12).start()
        retry = Timer(2, count=2).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if '是否移动' in read_text(self.device.image, MAZE_MOVE_ASK_AREA):
                asked = True
                break
            if '出发' in read_text(self.device.image, MAZE_SORTIE_AREA):
                break
            if retry.reached():
                retry.reset()
                self.tap_point(*MAZE_BOSS_NODE)
            if timer.reached():
                logger.warning('The boss node does not answer')
                return False

        if asked:
            # The box only silences the question for the rest of the session,
            # so it is pressed without a check.
            self.tap_point(*MAZE_MOVE_CHECKBOX)
            self.tap_point(*MAZE_MOVE_CONFIRM)

        # The party walks into the room and the sortie page comes up.
        timer = Timer(15).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if '出发' in read_text(self.device.image, MAZE_SORTIE_AREA):
                break
            if asked and '是否移动' in read_text(self.device.image, MAZE_MOVE_ASK_AREA):
                # The confirm was eaten, the dialog is still there.
                self.tap_point(*MAZE_MOVE_CONFIRM)
            if timer.reached():
                logger.warning('The sortie page did not come up')
                return False
        self.tap_point(*MAZE_BOSS_START)
        logger.info('The last room is running')

        timer = Timer(timeout).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.maze_victory_appear():
                logger.info('The last room is won')
                self.tap_point(*MAZE_VICTORY_TAP)
                return True
            if self.maze_finished() or self.maze_on_map():
                return True
            if timer.reached():
                logger.warning('The boss fight did not finish in time')
                return False

    def maze_choice_appear(self):
        """
        Whether the game stopped the run to ask something.

        The screen shows three cards and each one carries its kind above the art
        (增益型 / 消耗型 / 恢复型), so the labels are read. The brightness of the
        「选择」 bar was the check before and it matched any bright page: on a
        shop dialog it read as a choice, the settle loop answered a choice that
        did not exist and ran until it was killed (measured 2026-10-27).

        Returns:
            bool: If a choice screen is up.
        """
        from module.base.utils import get_color

        # Cheap gate first: the map is dark in the bar area, only a choice
        # screen draws the cream bar there.
        color = get_color(self.device.image, MAZE_CHOICE_BAR)
        if sum(color) / 3 <= MAZE_CHOICE_MEAN:
            return False
        for area in MAZE_CHOICE_LABELS:
            if '型' in read_text(self.device.image, area):
                return True
        return False

    def maze_choose(self):
        """
        Answer one choice screen.

        「女神的祝福」 offers three cards: one 消耗型 (some material) and two
        增益型 buffs. The buffs are what the run wants, so the first card
        labelled 增益型 is picked; if the labels cannot be read, the middle card
        is taken, which is a buff on every screen seen so far. A reward popup may
        follow and is dismissed.

        Pages:
            in: choice screen
            out: page_maze

        Returns:
            bool: If the screen went away.
        """
        logger.hr('Answer the choice', level=2)
        pick = 1
        for index, area in enumerate(MAZE_CHOICE_LABELS):
            text = read_text(self.device.image, area)
            logger.attr(f'Card {index + 1}', text or '-')
            if '增益' in text:
                pick = index
                break

        # Picking a card and confirming it are two presses; the screen stays up
        # if either is missed, so the pair is repeated until it goes away.
        for attempt in range(3):
            self.tap_point(MAZE_CHOICE_CARDS[pick], MAZE_CHOICE_CARD_Y)
            timeout = Timer(3).start()
            while 1:
                self.device.stuck_record_clear()
                self.device.screenshot()
                if self.reward_appear() or not self.maze_choice_appear():
                    break
                if timeout.reached():
                    break
            if self.reward_appear():
                self.handle_reward_popup()
                logger.info('Reward popup dismissed')
                return True
            if not self.maze_choice_appear():
                return True
            # The card is selected but not confirmed: the 「选择」 bar is the
            # second half of the press and only works once a card is picked.
            self.tap_point(*MAZE_CHOICE_CONFIRM)
            timeout = Timer(3).start()
            while 1:
                self.device.stuck_record_clear()
                self.device.screenshot()
                if self.reward_appear():
                    self.handle_reward_popup()
                    return True
                if not self.maze_choice_appear():
                    return True
                if timeout.reached():
                    break
            logger.info('The choice screen is still up, press again')
        logger.warning('The choice screen did not go away')
        return False

    def maze_panel_appear(self):
        """
        Whether the 「自动进行迷宫」 panel is on screen.

        Returns:
            bool: If its title is there.
        """
        return match(self.device.image, MAZE_AUTO_TITLE,
                     (400, 40, 820, 140)) > 0.85

    def maze_answer_overlay(self):
        """
        Answer whatever the auto run stopped on, if anything.

        The game interrupts itself in three ways and each one freezes the map
        exactly like the end of a run does, so they have to be answered before a
        still frame is read as "the run is over".

        Returns:
            bool: True if something was pressed, so the caller reads a new frame.
        """
        if self.maze_panel_appear():
            logger.info('The panel is back, confirm it again')
            self.tap_point(*MAZE_PANEL_POINT)
            return True
        if self.maze_victory_appear():
            logger.info('The last room is won')
            self.tap_point(*MAZE_VICTORY_TAP)
            return True
        if self.reward_appear():
            logger.info('Reward popup in the maze')
            self.handle_reward_popup()
            return True
        if self.maze_talk_appear():
            self.tap_point(*MAZE_TALK_TAP)
            return True
        return False

    def maze_wait_finish(self, timeout=1800):
        """
        Wait until the auto run stops moving, then answer whatever stopped it.

        The map pans while the run goes on and freezes the moment it ends, so a
        run of identical frames is the end; the boss chain owns the fight once
        the map stops in front of the King (see `maze_fight_boss`).

        Args:
            timeout (int, float): Seconds, a safety net only.

        Returns:
            bool: If the run finished by itself.
        """
        logger.hr('Auto run', level=2)
        timeout = Timer(timeout).start()
        still = 0
        previous = None
        boss_tried = False
        choice_gave_up = False

        for _ in self.loop():
            # A map panning in front of a live scene reads as a frozen game to
            # the stuck detector.
            self.device.stuck_record_clear()
            image = np.array(self.device.image).astype(np.int16)

            # End - 「完成」 over the head of the maze: the last room is down and
            # the week is spent, there is nothing left to wait for.
            if self.maze_finished():
                logger.info('The maze is complete')
                return True

            # Click - a story, a result page or the panel again.
            if self.maze_answer_overlay():
                previous = None
                still = 0
                continue

            # A screen that does not answer is dropped after three tries instead
            # of being pressed forever.
            if not choice_gave_up and self.maze_choice_appear():
                if not self.maze_choose():
                    logger.warning('The choice screen does not answer, give up')
                    choice_gave_up = True
                previous = None
                still = 0
                continue

            if previous is not None:
                diff = float(np.abs(image - previous).mean())
                if diff < MAZE_STILL_DIFF:
                    still += 1
                else:
                    still = 0
            previous = image

            # End - the map also freezes when it stops in front of the last
            # room, which the auto run does not enter by itself. One attempt is
            # enough: a press chain that does not move on the first try means the
            # run really is over.
            if still >= MAZE_STILL_FRAMES:
                if not boss_tried:
                    boss_tried = True
                    if self.maze_fight_boss():
                        previous = None
                        still = 0
                        continue
                logger.info('The map has stopped, the run is over')
                return True

            if timeout.reached():
                logger.warning('The auto run did not stop in time')
                return False

