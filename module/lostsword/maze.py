"""The maze (迷宫) of the battle tab.

Layout:

    战斗 --滑到卡片列表末尾--> 「迷宫」卡
    迷宫卡 --点击--> 迷宫地图（标题「迷宫N层」，左下「自动进行」）
    「自动进行」--> 「自动进行迷宫」面板（六个节点类型的优先级 + 扫荡难度）
    面板底部「自动进行」--> 自动走到今天走不动为止，停在地图上，「自动进行」变灰

The maze plays itself once the panel is confirmed: no battle screen, no click -
the map just scrolls and the floors go up (measured: 1 层 to 16 层 in about
fifteen seconds). What is left to do is to wait until the map stops moving.
"""

import numpy as np

import datetime

from module.base.timer import Timer
from module.logger import logger
from module.lostsword.affection import read_text
from module.lostsword.assets import (AFFECTION_TAP, ARENA_BTN_CLOSE,
                                     BOSS_VICTORY, MAZE_AUTO_TITLE,
                                     MAZE_BTN_AUTO, MAZE_CARD,
                                     REWARD_POPUP_TITLE)
from module.lostsword.event import match
from module.lostsword.lostsword_ui import (LostswordUI, page_battle,
                                           page_main, page_maze)

# The 「自动进行迷宫」 panel: its own 「自动进行」 button sits in the middle.
MAZE_PANEL_POINT = (640, 600)

# The six priority cells of that panel, top left to bottom right, with the value
# each one is set to. The value comes from the event guide: 女神的祝福 is the one
# that always helps (revive + heal), BOSS rooms carry the 玉玺 drop, chests drop
# gear and gifts, the winged cell revives a fallen unit, 死神的试炼 trades HP for
# power, and 特殊事件 "basically never has anything good".
#
#     行1: 宝箱          BOSS
#     行2: 死神的试炼    特殊事件
#     行3: 女神的祝福    复活
MAZE_PRIORITY_CELLS = (
    ((541, 254), 3),   # 宝箱
    ((925, 254), 2),   # BOSS
    ((541, 315), 5),   # 死神的试炼
    ((925, 315), 6),   # 特殊事件
    ((541, 378), 1),   # 女神的祝福
    ((925, 378), 4),   # 复活
)
# The option list of a dropdown, measured: six lines about 43 px apart, the
# first one a little under the cell that opened it.
MAZE_PRIO_STEP = 43
MAZE_PRIO_SCAN = (200, 380)
# A run is over when the map stops moving; two frames of a running maze always
# differ (the camera pans), a finished one is the same image.
MAZE_STILL_FRAMES = 3
MAZE_STILL_DIFF = 1.0

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
# The maze card once the list is dragged to its end.
MAZE_LAST_CARD = (1096, 416)
# The card art of that slot, used as a position check only (see
# `maze_at_list_end()`): 0.74 when the card is there, 0.04 when it is not.
MAZE_CARD_SIMILARITY = 0.5
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


class LostswordMaze(LostswordUI):
    def run(self):
        logger.hr('Maze', level=1)
        # Starting on the map of a cleared maze: the week is spent, there is
        # nothing to open and nothing to press.
        self.device.screenshot()
        if self.maze_finished():
            logger.info('The maze is already complete')
            self.maze_exit()
            self.ui_goto_main()
            self.maze_delay()
            return

        if not self.maze_settle():
            logger.warning('The game is on a screen the maze task cannot leave')
            self.maze_delay()
            return
        self.ui_ensure(page_battle)
        self.battle_goto_normal()
        if not self.maze_enter():
            logger.warning('Could not open the maze')
            self.ui_goto_main()
            self.maze_delay()
            return

        if self.maze_finished():
            # The card says 探险完成, so the map opens without a run left: it
            # shows 「完成」 over the head of the maze and no 「自动进行」 button.
            # Everything below would be guessing at buttons that are not there.
            logger.info('The maze is already complete, nothing to do this week')
            self.maze_exit()
            self.ui_goto_main()
            self.maze_delay()
            return

        if self.maze_auto_start():
            self.maze_wait_finish()
        else:
            logger.info('The auto run is not available today')

        self.maze_exit()
        self.ui_goto_main()
        self.maze_delay()

    def maze_delay(self):
        """
        Postpone the task to next Monday 00:00.

        The maze is a weekly mode, not a daily one: the reset is Sunday 11:00 in
        Korea, which is Monday 00:00 here, and the run spends everything the week
        allows - after it the map shows 「完成」 and the 「自动进行」 button does
        nothing until the reset.
        """
        now = datetime.datetime.now()
        days = (7 - now.weekday()) % 7 or 7
        target = (now + datetime.timedelta(days=days)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        logger.attr('Maze next reset', str(target))
        self.config.task_delay(target=target)

    def maze_enter(self, timeout=15):
        """
        Open the maze from the battle tab.

        Two phases on purpose. The list is dragged to its end and checked
        first, and once the maze card is in the last slot the list is not
        touched again: the press opens the map through a six second loading
        screen, and dragging during that screen does nothing but fill the click
        record until "too many click for a button" kills the task (measured
        2026-10-27, the map was already open and the task kept swiping).

        Pages:
            in: page_battle
            out: page_maze

        Args:
            timeout (int, float): Seconds to wait for the map after one press.

        Returns:
            bool: If the map opened.
        """
        if not self.maze_goto_last_card():
            logger.warning('The maze card never reached the last slot')
            return False

        for attempt in range(2):
            self.tap_point(*MAZE_LAST_CARD)
            timer = Timer(timeout).start()
            while 1:
                self.device.stuck_record_clear()
                self.device.screenshot()
                # A cleared maze has no 「自动进行」 button any more, only 「完成」
                # over the map, so both count as "the maze opened".
                if self.maze_on_map() or self.maze_finished():
                    logger.info('Maze map opened')
                    return True
                if timer.reached():
                    break
            logger.info(f'The press did not open the maze, press again '
                        f'({attempt + 1}/2)')
        return False

    def maze_goto_last_card(self, tries=3):
        """
        Drag the card list to its end and check that the maze is in the last
        slot.

        Args:
            tries (int): How many rounds of drags may be spent.

        Returns:
            bool: If the maze card is in the last slot.
        """
        for _ in range(tries):
            self.battle_scroll(forward=True)
            if self.maze_at_list_end():
                return True
            logger.info('The maze card is not in the last slot yet')
        return False

    def maze_at_list_end(self):
        """
        Whether the card list sits at its end, i.e. the maze card is in the last
        slot.

        The card art is a position check only, never a state check: the game
        writes 可进入 / 探险完成 under it and neither is part of the template.
        Measured 0.74 with the list at its end and 0.04 anywhere else, so the
        threshold sits between them with room on both sides.

        Returns:
            bool: If the last slot holds the maze.
        """
        return match(self.device.image, MAZE_CARD,
                     (1040, 545, 1145, 640)) > MAZE_CARD_SIMILARITY

    def maze_on_map(self):
        """
        Whether the maze map is on screen.

        Returns:
            bool: If the 「自动进行」 button is in its corner.
        """
        return match(self.device.image, MAZE_BTN_AUTO,
                     (100, 600, 320, 700)) > 0.85

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

        timeout = Timer(timeout).start()
        retry = Timer(2, count=2).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.maze_panel_appear():
                break
            if retry.reached():
                retry.reset()
                self.device.adb_shell(['input', 'tap',
                                       str(button[0]), str(button[1])])
            if timeout.reached():
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

    def maze_set_priorities(self):
        """
        Set the six priority dropdowns of the panel.

        Every dropdown is opened, the option lines are found by their white
        text, and the wanted one is pressed. A dropdown whose list does not
        come up with six lines is left alone - the game default (everything on
        「优先级1」) is harmless, while guessing a position could put 特殊事件
        above the rooms that matter.

        Pages:
            in: page_maze (panel open)
            out: page_maze (panel open)

        Returns:
            int: How many cells were set.
        """
        logger.hr('Set priorities', level=2)
        done = 0
        for (x, y), level in MAZE_PRIORITY_CELLS:
            if self.maze_set_one(x, y, level):
                done += 1
        logger.info(f'Priorities set: {done}/{len(MAZE_PRIORITY_CELLS)}')
        return done

    def maze_set_one(self, x, y, level):
        """
        Open one dropdown and pick a level.

        The press that opens a dropdown is eaten now and then (measured: the
        same cell needs two or three presses), so it is repeated until the
        option list is readable, and the pick is confirmed by the list closing.

        Args:
            x (int): Centre x of the dropdown.
            y (int): Centre y of the dropdown.
            level (int): 1 to 6.

        Returns:
            bool: If the cell was set.
        """
        for attempt in range(4):
            self.tap_point(x, y)
            # Wait for the list to be readable instead of sleeping a fixed time:
            # it renders in well under a second and the scan is cheap.
            timeout = Timer(3).start()
            while 1:
                self.device.screenshot()
                lines = self.maze_priority_lines(x, y)
                if len(lines) >= 6:
                    break
                if timeout.reached():
                    break
            if len(lines) < 6:
                continue

            target = lines[:6][level - 1]
            self.tap_point(x, target)
            timeout = Timer(3).start()
            while 1:
                self.device.screenshot()
                if len(self.maze_priority_lines(x, y)) < 6:
                    logger.info(f'Cell ({x}, {y}) -> 优先级{level} at y={target}')
                    return True
                if timeout.reached():
                    logger.warning(f'Cell ({x}, {y}): the list did not close')
                    break
        logger.warning(f'Cell ({x}, {y}): the option list did not open')
        return False

    def maze_priority_lines(self, x, y):
        """
        Find the six option lines of an opened dropdown by their white text.

        Args:
            x (int): Centre x of the dropdown.
            y (int): Centre y of the dropdown.

        Returns:
            list: y centres of the lines, top to bottom.
        """
        x1, x2 = x - 100, x + 100
        y1, y2 = y + 20, min(715, y + MAZE_PRIO_SCAN[1])
        region = self.device.image[y1:y2, x1:x2].astype(np.int16)
        mask = ((region[:, :, 0] > 195) & (region[:, :, 1] > 185)
                & (region[:, :, 2] > 170))
        counts = mask.sum(axis=1)
        lines = []
        start = None
        for i, value in enumerate(counts):
            if value > 3 and start is None:
                start = i
            elif value <= 3 and start is not None:
                if 8 <= i - start <= 24:
                    lines.append(y1 + (start + i) // 2)
                start = None
        return lines

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
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            image = np.array(self.device.image).astype(np.int16)

            if self.maze_finished():
                # 「完成」 over the head of the maze: the last room is down and
                # the week is spent, there is nothing left to wait for.
                logger.info('The maze is complete')
                return True

            if self.maze_panel_appear():
                logger.info('The panel is back, confirm it again')
                self.tap_point(*MAZE_PANEL_POINT)
                previous = None
                still = 0
                continue

            if self.maze_victory_appear():
                logger.info('The last room is won')
                self.tap_point(*MAZE_VICTORY_TAP)
                previous = None
                still = 0
                continue

            if self.maze_talk_appear():
                self.tap_point(*MAZE_TALK_TAP)
                previous = None
                still = 0
                continue

            if not choice_gave_up and self.maze_choice_appear():
                # The run stopped on a question, which freezes the map exactly
                # like the end of a run does: answer it before anything is
                # read as "the map has stopped". A screen that does not answer
                # is dropped after three tries instead of being pressed forever.
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

            if still >= MAZE_STILL_FRAMES:
                # The map also freezes when it stops in front of the last room,
                # which the auto run does not enter by itself. One attempt is
                # enough: a press chain that does not move on the first try
                # means the run really is over.
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

    def maze_exit(self, timeout=15):
        """
        Close the map and go back to whatever is behind it.

        The X of the map leads to the lobby through a loading screen (measured),
        which is why the wait below only asks for the map to be gone: the page
        behind it is found by `ui_goto_main()` anyway.

        Pages:
            in: page_maze
            out: page_main

        Returns:
            bool: If the map left.
        """
        timeout = Timer(timeout).start()
        retry = Timer(2, count=2).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if not (self.maze_on_map() or self.maze_finished()):
                return True
            if retry.reached():
                retry.reset()
                self.device.click(ARENA_BTN_CLOSE)
            if timeout.reached():
                logger.warning('The maze map did not close')
                return False

    def tap_point(self, x, y):
        """
        Press a point of this page with an adb tap.

        Args:
            x (int): Pixel x.
            y (int): Pixel y.
        """
        self.device.adb_shell(['input', 'tap', str(int(x)), str(int(y))])
