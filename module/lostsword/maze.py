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
                                           page_maze)

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
MAZE_STILL_INTERVAL = 3

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
# Its result page: 「VICTORY」 over the loot, 「点击屏幕」 at the bottom.
MAZE_VICTORY_REGION = (0, 0, 1280, 300)
# When the boss room is down the map shows 「完成」 over the head of the maze: the
# run is over and there is nothing left to wait for.
MAZE_DONE_AREA = (580, 25, 700, 65)
MAZE_VICTORY_TAP = (640, 400)


class LostswordMaze(LostswordUI):
    def run(self):
        logger.hr('Maze', level=1)
        if not self.maze_settle():
            logger.warning('The game is on a screen the maze task cannot leave')
            self.maze_delay()
            return
        self.ui_ensure(page_battle)
        self.battle_goto_normal()
        # Let the tab finish sliding before the list is dragged: a swipe that
        # lands during the transition is dropped, and the last card is then out
        # of reach.
        self.device.sleep(1.5)
        if not self.maze_enter():
            logger.warning('Could not open the maze')
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

    def maze_enter(self, timeout=25):
        """
        Open the maze from the battle tab.

        The maze card is the last one of the list, so the list is scrolled to its
        end first.

        Pages:
            in: page_battle
            out: page_maze

        Args:
            timeout (int, float): Seconds to wait for the map.

        Returns:
            bool: If the map opened.
        """
        # The maze card is the last one of the list, so the list is dragged to
        # its end and the rightmost card is pressed. Its caption is not used as
        # a check point: the game writes 可进入 / 探险完成 / ... under it, and
        # every state renders it differently (0.74 against the 可进入 asset).
        self.battle_scroll(forward=True)
        self.device.sleep(1.5)
        self.tap_point(*MAZE_LAST_CARD)

        timeout = Timer(timeout).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            # A cleared maze has no 「自动进行」 button any more, only 「完成」 over
            # the map, so both count as "the maze opened".
            if self.maze_on_map() or self.maze_finished():
                logger.info('Maze map opened')
                return True
            if timeout.reached():
                logger.warning('The maze did not open, the card was wrong?')
                return False
            self.device.sleep(0.8)

    def maze_on_map(self):
        """
        Whether the maze map is on screen.

        Returns:
            bool: If the 「自动进行」 button is in its corner.
        """
        return match(self.device.image, MAZE_BTN_AUTO,
                     (100, 600, 320, 700)) > 0.85

    def maze_auto_start(self, timeout=8):
        """
        Press 「自动进行」 and confirm the panel it raises.

        The button looks the same when the daily run is spent, so the panel is
        what tells: it comes up when a run can be started, and nothing happens
        when it cannot.

        Pages:
            in: page_maze
            out: page_maze

        Args:
            timeout (int, float): Seconds to wait for the panel.

        Returns:
            bool: If a run was started.
        """
        x1, y1, x2, y2 = MAZE_BTN_AUTO.button
        self.device.adb_shell(['input', 'tap',
                               str((x1 + x2) // 2), str((y1 + y2) // 2)])

        timeout = Timer(timeout).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.maze_finished():
                logger.info('The maze is complete')
                return True

            if self.maze_victory_appear():
                logger.info('The last room is won')
                self.tap_point(*MAZE_VICTORY_TAP)
                previous = None
                still = 0
                self.device.sleep(1.5)
                continue

            if self.maze_talk_appear():
                self.tap_point(*MAZE_TALK_TAP)
                previous = None
                still = 0
                self.device.sleep(1.2)
                continue

            if self.maze_choice_appear():
                self.maze_choose()
                previous = None
                still = 0
                continue

            if self.maze_panel_appear():
                break
            if timeout.reached():
                return False
            self.device.sleep(0.6)

        self.maze_set_priorities()

        logger.info('Confirm the auto run')
        for _ in range(2):
            self.tap_point(*MAZE_PANEL_POINT)
            self.device.sleep(1.5)
            self.device.screenshot()
            if not self.maze_panel_appear():
                return True
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
        same cell needs two or three presses), so it is retried until the
        option list is readable.

        Args:
            x (int): Centre x of the dropdown.
            y (int): Centre y of the dropdown.
            level (int): 1 to 6.

        Returns:
            bool: If the cell was set.
        """
        for attempt in range(4):
            self.tap_point(x, y)
            self.device.sleep(1.2)
            self.device.screenshot()
            lines = self.maze_priority_lines(x, y)
            if len(lines) >= 6:
                target = lines[:6][level - 1]
                self.tap_point(x, target)
                self.device.sleep(0.9)
                self.device.screenshot()
                logger.info(f'Cell ({x}, {y}) -> 优先级{level} at y={target}')
                return True
            self.device.sleep(0.4)
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

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If a known page is reachable afterwards.
        """
        timeout = Timer(timeout).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.maze_on_map() or self.maze_panel_appear() or self.maze_finished():
                return True
            if self.maze_victory_appear():
                self.tap_point(*MAZE_VICTORY_TAP)
                self.device.sleep(1.5)
                continue
            if self.maze_talk_appear():
                self.tap_point(*MAZE_TALK_TAP)
                self.device.sleep(1.2)
                continue
            if self.maze_choice_appear():
                self.maze_choose()
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
            self.device.sleep(1.2)

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
        right opens a 「体力状态」 panel, and its 「确认」 starts the fight; both
        presses are harmless when the run has simply ended (they land on the
        map). The fight itself cannot be skipped, so it is left to run.

        Returns:
            bool: If something happened - a fight started or a result page came up.
        """
        before = np.array(self.device.image).astype(np.int16)
        self.tap_point(*MAZE_BOSS_NEXT)
        self.device.sleep(2)
        self.device.screenshot()
        if float(np.abs(np.array(self.device.image).astype(np.int16) - before).mean()) < 2:
            return False

        logger.hr('Start the last room', level=2)
        self.tap_point(*MAZE_BOSS_CONFIRM)
        self.device.sleep(1.5)
        self.tap_point(*MAZE_BOSS_NODE)
        self.device.sleep(2)
        # 「是否移动?」 - tick the box so the question stays away, then confirm.
        self.tap_point(*MAZE_MOVE_CHECKBOX)
        self.device.sleep(0.5)
        self.tap_point(*MAZE_MOVE_CONFIRM)
        self.device.sleep(3)
        self.device.screenshot()
        # The sortie page of the boss room; its 「出发」 starts a fight that
        # cannot be skipped, so the wait loop takes over again from here.
        self.tap_point(*MAZE_BOSS_START)
        self.device.sleep(3)
        self.device.screenshot()
        logger.info('The last room is running')
        return True

    def maze_choice_appear(self):
        """
        Whether the game stopped the run to ask something.

        The 「选择」 bar of the choice screen is cream over a bright card area,
        while the map is dark in that spot.

        Returns:
            bool: If a choice screen is up.
        """
        from module.base.utils import get_color

        color = get_color(self.device.image, MAZE_CHOICE_BAR)
        return sum(color) / 3 > MAZE_CHOICE_MEAN

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
            self.device.sleep(1.2)
            self.tap_point(*MAZE_CHOICE_CONFIRM)
            self.device.sleep(2.0)
            self.device.screenshot()
            if self.reward_appear():
                self.handle_reward_popup()
                logger.info('Reward popup dismissed')
                return
            if not self.maze_choice_appear():
                return
            logger.info('The choice screen is still up, press again')
        logger.warning('The choice screen did not go away')

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
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            image = np.array(self.device.image).astype(np.int16)

            if self.maze_panel_appear():
                logger.info('The panel is back, confirm it again')
                self.tap_point(*MAZE_PANEL_POINT)
                self.device.sleep(1.5)
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
                # which the auto run does not enter by itself. The round button
                # at the bottom right opens the party check; if nothing happens
                # the run really is over.
                if self.maze_fight_boss():
                    previous = None
                    still = 0
                    continue
                logger.info('The map has stopped, the run is over')
                return True
            if timeout.reached():
                logger.warning('The auto run did not stop in time')
                return False

            self.device.sleep(MAZE_STILL_INTERVAL)

    def maze_exit(self):
        """
        Close the map and go back to the battle tab.

        Pages:
            in: page_maze
            out: page_battle
        """
        for _ in range(3):
            self.device.stuck_record_clear()
            self.device.screenshot()
            if not (self.maze_on_map() or self.maze_finished()):
                break
            self.tap_point(1237, 38)
            self.device.sleep(2)
        self.device.sleep(1)
        self.device.screenshot()

    def tap_point(self, x, y):
        """
        Press a point of this page with an adb tap.

        Args:
            x (int): Pixel x.
            y (int): Pixel y.
        """
        self.device.adb_shell(['input', 'tap', str(int(x)), str(int(y))])
