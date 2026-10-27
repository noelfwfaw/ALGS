"""Daily affection talks (好感对话).

Layout:

    主界面 --底栏「角色」--> 角色页面（5 列网格，卡片底部写名字）
    角色页面 --角色卡--> 角色详情页
    角色详情页 --左下「羁绊延续」--> 好感页面
        右上角是今天全服共用的对话次数（6/6）
        右下「对话」下面是这个角色今天的次数（0/1 可谈，1/1 已完成）
    好感页面 --「对话」--> 对话页面（立绘 + 台词，右下有一个继续箭头）
        点四五次后弹出两条选项，随便选一条
        再点几下就结束，回到好感页面，「对话」变成「对话完成」
    好感页面 --右上 X--> 角色详情页 --右上 X--> 角色页面

Six talks a day, shared by every character. The names come from the task config
(`Name1` .. `Name6`); each one is found on the character grid by OCR.
"""

import difflib
import re

import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.logger import logger
from module.lostsword.assets import (AFFECTION_BTN_DONE, AFFECTION_BTN_TALK,
                                     AFFECTION_CHOICE, AFFECTION_TAP,
                                     CHAR_BTN_AFFECTION, CHAR_TITLE)
from module.lostsword.event import match
from module.lostsword.lostsword_ui import (LostswordUI, page_character,
                                           page_main)

# The character grid: five columns, the name of each card sits at the bottom
# left of the card.
GRID_COLUMNS = (289, 489, 689, 889, 1089)
# y of the name label of the first two rows; a third row is only half drawn and
# its names are off screen, so the list is scrolled to reach it.
GRID_NAME_Y = (266, 511)
GRID_ROW_STEP = 245
# Distance from the name label up to the middle of the card.
GRID_CARD_DY = 76
NAME_WIDTH = 145
NAME_HEIGHT = 17

# Buttons of this flow, all pressed with an adb tap: the character cards and the
# dialog buttons ignore the shorter minitouch tap.
CHAR_TAB_POINT = (1078, 674)
AFFECTION_ENTRY_POINT = (200, 585)
AFFECTION_TALK_POINT = (830, 590)
AFFECTION_CONTINUE_POINT = (1230, 665)
# The first of the two choices, the one the asset was cut from.
AFFECTION_CHOICE_POINT = (314, 277)

# A conversation is about ten lines plus two choices; the timeout is a net only.
TALK_TIMEOUT = 180
# Each line fades in, a tap during the fade is swallowed.
TALK_INTERVAL = 1.1
TALK_MAX_TAPS = 40

# OCR similarity needed to accept a card as the wanted character. The names are
# read with the Chinese model, which drops a character now and then (「女仆丽塔」
# comes back as 「仆丽塔」), so an exact compare is not enough.
NAME_SIMILARITY = 0.5


def read_text(image, area):
    """
    OCR a piece of the screenshot with the Chinese model.

    Args:
        image (np.ndarray): Screenshot.
        area (tuple): (x1, y1, x2, y2).

    Returns:
        str: What was read, without punctuation.
    """
    from module.ocr.ocr import Ocr

    button = Button(area=area, color=(0, 0, 0), button=area, name='NAME')
    ocr = Ocr(button, lang='cnocr', letter=(255, 255, 255), threshold=170,
              name='CHAR_NAME')
    text = ocr.ocr(image)
    return re.sub(r'[^\u4e00-\u9fa5]', '', str(text))


class LostswordAffection(LostswordUI):
    def run(self):
        logger.hr('Affection', level=1)
        names = self.affection_names()
        if not names:
            logger.warning('No character name configured, nothing to do')
            self.config.task_delay(server_update=True)
            return
        logger.attr('Affection targets', ', '.join(names))

        self.ui_ensure(page_main)
        self.ui_ensure(page_character)

        talked = self.affection_all(names)
        logger.info(f'Talked to {talked} character(s)')

        self.ui_goto_main()
        # Six talks a day, one pass is enough to spend them.
        self.config.task_delay(server_update=True)

    def affection_names(self):
        """
        Read the six names from the task config.

        Returns:
            list: Configured names, empty entries dropped.
        """
        names = []
        for i in range(1, 7):
            value = getattr(self.config, f'LostswordAffection_Name{i}', '')
            value = str(value).strip() if value else ''
            if value:
                names.append(value)
        return names

    def affection_all(self, names):
        """
        Talk to every configured character that still has a talk left.

        Pages:
            in: page_character
            out: page_character

        Args:
            names (list): Character names.

        Returns:
            int: How many conversations were had.
        """
        talked = 0
        for name in names:
            if not self.affection_find(name):
                logger.warning(f'{name}: not found on the character page')
                continue
            if not self.affection_open():
                logger.warning(f'{name}: the affection panel did not open')
                self.affection_back_to_list()
                continue
            if not self.affection_talk_available():
                logger.info(f'{name}: no talk left for today')
                self.affection_back_to_list()
                continue
            self.affection_walk()
            talked += 1
            logger.info(f'{name}: talk finished')
            self.affection_back_to_list()
        return talked

    # -------------------------------------------------------------------- grid

    def affection_find(self, name):
        """
        Find a character on the grid and open it.

        The grid scrolls; the visible part is scanned first, then the list is
        scrolled down one screen and scanned again.

        Pages:
            in: page_character
            out: page_character_detail (or still page_character)

        Args:
            name (str): Character name.

        Returns:
            bool: If the character was opened.
        """
        logger.hr(f'Character {name}', level=2)
        for screen in range(2):
            self.device.stuck_record_clear()
            self.device.screenshot()
            found = self.affection_match_on_screen(name)
            if found:
                x, y = found
                logger.info(f'{name}: card at ({x}, {y})')
                self.tap(x, y)
                self.device.sleep(2.5)
                return True
            if screen == 0:
                logger.info('Not on screen, scroll the list down')
                self.device.swipe(p1=(640, 620), p2=(640, 220))
                self.device.sleep(1.5)
        return False

    def affection_match_on_screen(self, name):
        """
        OCR the names of the visible rows and pick the best match.

        Args:
            name (str): Character name.

        Returns:
            tuple: (x, y) of the card to press, None when nothing is close.
        """
        image = self.device.image
        best = None
        best_ratio = NAME_SIMILARITY
        for row, name_y in enumerate(GRID_NAME_Y):
            for x1 in GRID_COLUMNS:
                area = (x1, name_y, x1 + NAME_WIDTH, name_y + NAME_HEIGHT)
                text = read_text(image, area)
                if not text:
                    continue
                ratio = difflib.SequenceMatcher(None, name, text).ratio()
                logger.attr(f'Card r{row + 1}', f'{text} ({ratio:.2f})')
                if ratio > best_ratio:
                    best_ratio = ratio
                    best = (x1 + 89, name_y - GRID_CARD_DY)
        return best

    # --------------------------------------------------------------- panel

    def affection_open(self, timeout=10):
        """
        Press the affection entry of the detail page.

        The entry is named 「羁绊延续」 / 「心生好感」 / ... depending on the
        character, so the icon is what gets matched, and the press goes to the
        fixed corner of the page.

        Pages:
            in: page_character_detail
            out: page_affection

        Args:
            timeout (int, float): Seconds to wait for the panel.

        Returns:
            bool: If the panel opened.
        """
        timeout = Timer(timeout).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if match(self.device.image, CHAR_BTN_AFFECTION,
                     (140, 530, 260, 640)) > 0.85:
                break
            if timeout.reached():
                logger.warning('The affection entry is not on screen')
                return False
            self.device.sleep(0.5)

        self.tap(*AFFECTION_ENTRY_POINT)
        return self.affection_wait_panel(timeout=10)

    def affection_wait_panel(self, timeout=10):
        """
        Wait until the affection panel is on screen.

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If the panel is there.
        """
        timeout = Timer(timeout).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.affection_panel_appear():
                return True
            if timeout.reached():
                return False
            self.device.sleep(0.5)

    def affection_panel_appear(self):
        """
        Whether the affection panel is on screen.

        Both the enabled and the finished talk button match here: the two assets
        differ only in the label, and either of them means "this is the panel".

        Returns:
            bool: If the panel is up.
        """
        image = self.device.image
        region = (700, 500, 960, 680)
        return (match(image, AFFECTION_BTN_TALK, region) > 0.85
                or match(image, AFFECTION_BTN_DONE, region) > 0.85)

    # ------------------------------------------------------------------ talk

    def affection_talk_available(self):
        """
        Press 「对话」 and tell from the result whether a talk was left.

        The button looks the same with and without tries (the two assets match
        each other at 0.96), so the page that comes up decides: a talk page has
        the continue arrow at the bottom right, a finished one stays on the
        panel.

        Pages:
            in: page_affection
            out: page_talk (on success) / page_affection

        Returns:
            bool: If a conversation started.
        """
        self.tap(*AFFECTION_TALK_POINT)
        timeout = Timer(5).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.affection_talk_appear():
                return True
            if timeout.reached():
                return False
            self.device.sleep(0.6)

    def affection_walk(self):
        """
        Walk one conversation to its end.

        A tap on the continue arrow advances a line; every fourth or fifth line
        a box with two choices shows up, and one of them has to be picked before
        the story goes on. The conversation ends when neither the arrow nor the
        choice box is on screen any more - the game goes back to the panel by
        itself.

        Pages:
            in: page_talk
            out: page_affection

        Returns:
            int: How many lines were advanced.
        """
        logger.hr('Talk', level=2)
        timer = Timer(TALK_TIMEOUT).start()
        taps = 0
        choices = 0
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.affection_choice_appear():
                logger.info('Choice box, pick the first one')
                self.tap(*AFFECTION_CHOICE_POINT)
                choices += 1
            elif self.affection_talk_appear():
                self.tap(*AFFECTION_CONTINUE_POINT)
                taps += 1
            else:
                logger.info(f'Talk finished, {taps} lines, {choices} choices')
                return taps
            if taps > TALK_MAX_TAPS:
                logger.warning('Stopped at the tap limit')
                return taps
            if timer.reached():
                logger.warning('Stopped at the time limit')
                return taps
            self.device.sleep(TALK_INTERVAL)

    def affection_talk_appear(self):
        """
        Whether the conversation page is on screen.

        Returns:
            bool: If the continue arrow is at the bottom right.
        """
        return match(self.device.image, AFFECTION_TAP,
                     (1150, 600, 1280, 720)) > 0.85

    def affection_choice_appear(self):
        """
        Whether the two choice lines are on screen.

        Returns:
            bool: If the choice box is there.
        """
        return match(self.device.image, AFFECTION_CHOICE,
                     (100, 220, 520, 330)) > 0.85

    # ------------------------------------------------------------------ back

    def affection_back_to_list(self):
        """
        Walk back to the character grid.

        Pages:
            in: page_affection or page_character_detail
            out: page_character

        Returns:
            bool: If the grid is back.
        """
        for _ in range(4):
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.affection_on_list():
                return True
            self.tap(1232, 56)
            self.device.sleep(2)
        self.device.screenshot()
        return self.affection_on_list()

    def affection_on_list(self):
        """
        Whether the character grid is on screen.

        Returns:
            bool: If the 「角色」 heading of the grid is there.
        """
        return match(self.device.image, CHAR_TITLE, (60, 10, 240, 70)) > 0.95

    # ----------------------------------------------------------------- input

    def tap(self, x, y):
        """
        Press a point with an adb tap.

        Args:
            x (int): Pixel x.
            y (int): Pixel y.
        """
        self.device.adb_shell(['input', 'tap', str(int(x)), str(int(y))])
