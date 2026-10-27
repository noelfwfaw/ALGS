"""The auto run of the maze, from 「自动进行」 to the last room.

The map plays itself: no battle screen, no click, the floors go up while the
camera pans (measured: 1 层 to 16 层 in about fifteen seconds). What is left is
the waiting - and the three ways the game interrupts itself:

- a story scene, which a tap in the middle advances (its bottom right arrow is
  decoration and does nothing);
- 「女神的祝福」, a choice of three cards, answered by picking a 增益型 one;
- the last room, which the auto run does not enter: the map stops, the round
  button opens the party check, the boss node asks 「是否移动?」 and the sortie
  page starts the fight.

A run is over when the map stops moving. Two consecutive frames of a running maze
always differ, a finished one is the same image - so the end of a run is a
property of the screen, not a timer.
"""

import numpy as np

from module.base.timer import Timer
from module.logger import logger
from module.lostsword.assets import (AFFECTION_TAP, BOSS_VICTORY,
                                     MAZE_AUTO_TITLE, MAZE_BTN_AUTO,
                                     REWARD_POPUP_TITLE)
from module.lostsword.page import page_battle, page_main
from module.lostsword.utils import match, read_text

# The auto run is not fully automatic: every few rooms the game stops and asks a
# question. 「女神的祝福」 shows three cards and a 「选择」 bar at the bottom; the
# run only goes on once one is picked. The bar is the reliable sign - the map
# behind it is dark (mean 67) while the bar is cream (mean 189).
MAZE_CHOICE_BAR = (590, 625, 700, 660)
MAZE_CHOICE_MEAN = 120
# The three cards of that screen, and the label of each one's kind.
MAZE_CHOICE_CARDS = (340, 636, 940)
MAZE_CHOICE_CARD_Y = 384
MAZE_CHOICE_LABELS = ((270, 348, 412, 378), (566, 348, 708, 378),
                      (870, 348, 1012, 378))
MAZE_CHOICE_CONFIRM = (640, 653)
# Story scenes of the maze - the 流泪的女神像 and the like - show the same arrow
# at the bottom right as a conversation, but that arrow is only decoration: a tap
# on it does nothing (confirmed by the user). The whole screen advances the line,
# so the press goes to the middle.
MAZE_TALK_TAP = (640, 360)
MAZE_TALK_REGION = (1150, 600, 1280, 720)
# The last room - the Minotauros King - is not part of the auto run: the map
# stops there, the 「自动进行」 button is gone, and the run only continues after
# the round button at the bottom right opens the party check and its 「确认」.
MAZE_BOSS_NEXT = (904, 653)
MAZE_BOSS_CONFIRM = (640, 632)
# Tapping the boss room raises 「感受到怪物的气息。是否移动?」 with a checkbox that
# stops the question from coming back for the rest of the session.
MAZE_MOVE_CHECKBOX = (488, 432)
MAZE_MOVE_CONFIRM = (640, 520)
MAZE_BOSS_NODE = (1064, 384)
# The boss room opens the usual sortie page: team on the left, 「出发」 bottom right.
MAZE_BOSS_START = (996, 664)
# The 「自动进行迷宫」 panel: its own 「自动进行」 button sits in the middle.
MAZE_PANEL_POINT = (640, 600)
# A run is over when the map stops moving; two frames of a running maze always
# differ (the camera pans), a finished one is the same image.
MAZE_STILL_FRAMES = 3
MAZE_STILL_DIFF = 1.0
# How much of the screen has to differ before a press counts as done. Opening a
# panel dims the whole page, which is worth far more than this; a press that was
# eaten leaves the frame unchanged to the last pixel.
MAZE_CHANGE_DIFF = 2.0
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
    `self.device`, `ui_get_current_page()` and `ui_page_appear()`; these come
    from the composed class:

    - `maze_on_map()` - is the map of the maze on screen (in `maze.py`, next to
      the entry and exit steps it belongs to)
    - `maze_set_priorities()` - the panel settings, from `MazePriority`
    - `tap_point()` / `handle_reward_popup()` - from `LostswordUI`
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
        the known ones, so they are answered here - tapping the story arrow or
        picking a card - until the map is back.

        A normal page ends the wait immediately: most runs start on the lobby or
        on the battle tab, and none of the overlays below can be there. Without
        that check a bright page used to read as a choice screen and the loop
        pressed a 「选择」 that did not exist until it was killed (2026-10-27).

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

    def maze_fight_boss(self):
        """
        Try to start the last room of the maze.

        Called when the map has stopped moving. The round button at the bottom
        right opens a 「体力状态」 panel, its 「确认」 goes back to the map, the
        boss node asks 「是否移动?」 and the sortie page starts the fight. The
        fight itself cannot be skipped, so it is left to the wait loop.

        The sequence is only worth walking while every press is confirmed: the
        map freezes for a second or two between two steps, and a press that
        lands in such a gap is dropped, which would send the rest of the chain
        onto the wrong page. So every step waits for its own screen change and
        the chain aborts at the first step that does not move.

        Returns:
            bool: If the fight was started.
        """
        # The round button only exists while the run has something left; on a
        # finished map the press changes nothing, which ends the chain at once.
        if not self.maze_tap_change(MAZE_BOSS_NEXT, 'party check'):
            return False

        logger.hr('Start the last room', level=2)
        if not self.maze_tap_change(MAZE_BOSS_CONFIRM, 'stamina panel'):
            return False
        if not self.maze_tap_change(MAZE_BOSS_NODE, 'boss room'):
            return False
        # 「是否移动?」 - the box only silences the question for the rest of the
        # session, so it is pressed without a check; the confirm next to it is
        # what moves the party and is verified like the rest.
        self.tap_point(*MAZE_MOVE_CHECKBOX)
        if not self.maze_tap_change(MAZE_MOVE_CONFIRM, 'move confirm'):
            return False
        if not self.maze_tap_change(MAZE_BOSS_START, 'sortie'):
            return False
        logger.info('The last room is running')
        return True

    def maze_tap_change(self, point, name, timeout=8, tries=2):
        """
        Press a point and wait until the screen really changed.

        Args:
            point (tuple): (x, y) to press.
            name (str): What the press is for, for the log.
            timeout (int, float): Seconds to wait after one press.
            tries (int): How many presses may be spent.

        Returns:
            bool: If the screen changed.
        """
        for attempt in range(tries):
            before = np.array(self.device.image).astype(np.int16)
            self.tap_point(*point)
            timer = Timer(timeout).start()
            while 1:
                self.device.stuck_record_clear()
                self.device.screenshot()
                after = np.array(self.device.image).astype(np.int16)
                if float(np.abs(after - before).mean()) > MAZE_CHANGE_DIFF:
                    logger.info(f'Press {name}: the screen moved')
                    return True
                if timer.reached():
                    break
            logger.info(f'Press {name} did nothing, press again ({attempt + 1}/{tries})')
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
        if self.maze_talk_appear():
            self.tap_point(*MAZE_TALK_TAP)
            return True
        return False

    def maze_wait_finish(self, timeout=1800):
        """
        Wait until the auto run stops moving.

        The map pans while the run goes on and freezes the moment it ends, so a
        run of identical frames is the end. The panel is pressed again if it
        shows up in the middle (the game asks for a new run after some events).

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

