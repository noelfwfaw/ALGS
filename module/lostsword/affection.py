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

import numpy as np

from module.base.timer import Timer
from module.logger import logger
from module.lostsword.assets import (AFFECTION_BTN_DONE, AFFECTION_BTN_TALK,
                                     AFFECTION_CHOICE, AFFECTION_TAP,
                                     CHAR_BTN_AFFECTION, CHAR_TITLE)
from module.lostsword.affection_grid import AffectionGrid
from module.lostsword.utils import match
from module.lostsword.lostsword_ui import (LostswordUI, page_character,
                                           page_main)
# Buttons of this flow, all pressed with an adb tap: the character cards and the
# dialog buttons ignore the shorter minitouch tap.
AFFECTION_ENTRY_POINT = (200, 585)
AFFECTION_TALK_POINT = (830, 590)
AFFECTION_CONTINUE_POINT = (1230, 665)
# The first of the two choices, the one the asset was cut from.
AFFECTION_CHOICE_POINT = (314, 277)

# A conversation is about ten lines plus two choices; the timeout is a net only.
TALK_TIMEOUT = 180
# How long one press may take to draw the next line, and how much of the screen
# has to change for the new line to count as drawn.
TALK_LINE_WAIT = 3
TALK_LINE_DIFF = 1.0
TALK_MAX_TAPS = 60


class LostswordAffection(AffectionGrid, LostswordUI):
    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
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

    def affection_open_card(self, x, y, timeout=8, tries=2):
        """
        Press a card and wait until its detail page really opened.

        The card press is a plain adb tap on a list that keeps animating after
        the drag, so a press is dropped now and then. Waiting for the detail
        page - instead of sleeping a fixed time and assuming the press landed -
        is what keeps a dropped press from being read as "this character has no
        detail page".

        Pages:
            in: page_character
            out: page_character_detail

        Args:
            x (int): Pixel x of the card.
            y (int): Pixel y of the card.
            timeout (int, float): Seconds to wait after one press.
            tries (int): How many presses may be spent.

        Returns:
            bool: If the detail page is up.
        """
        for attempt in range(tries):
            self.tap_point(x, y)
            timeout = Timer(timeout).start()
            while 1:
                self.device.stuck_record_clear()
                self.device.screenshot()
                if self.affection_detail_appear():
                    return True
                if timeout.reached():
                    break
            logger.info(f'The card press did nothing, press again ({attempt + 1}/{tries})')
        return False

    def affection_detail_appear(self):
        """
        Whether the detail page of a character is on screen.

        Returns:
            bool: If the affection entry is in its corner.
        """
        return match(self.device.image, CHAR_BTN_AFFECTION,
                     (140, 530, 260, 640)) > 0.85

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
        # The press is repeated until the panel is up: the entry sits under a
        # page that is still fading in after the card press, and a press that
        # lands then is dropped without any feedback.
        for attempt in range(3):
            timeout = Timer(timeout).start()
            while 1:
                self.device.stuck_record_clear()
                self.device.screenshot()
                if self.affection_detail_appear():
                    break
                if timeout.reached():
                    logger.warning('The affection entry is not on screen')
                    return False
            self.tap_point(*AFFECTION_ENTRY_POINT)
            if self.affection_wait_panel(timeout=4):
                return True
            logger.info(f'The affection entry press did nothing, press again '
                        f'({attempt + 1}/3)')
        return False

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
        # The 「对话」 button is pressed until the talk page shows: a press that
        # lands while the panel is still drawing is swallowed, and reading that
        # as "no talk left" would skip a character that still has one.
        for attempt in range(2):
            self.tap_point(*AFFECTION_TALK_POINT)
            timeout = Timer(4).start()
            while 1:
                self.device.stuck_record_clear()
                self.device.screenshot()
                if self.affection_talk_appear():
                    return True
                if timeout.reached():
                    break
            logger.info(f'No talk page, press 对话 again ({attempt + 1}/2)')
        return False

    def affection_walk(self):
        """
        Walk one conversation to its end.

        A tap on the continue arrow advances a line; every fourth or fifth line
        a box with two choices shows up, and one of them has to be picked before
        the story goes on. The conversation ends when neither the arrow nor the
        choice box is on screen any more - the game goes back to the panel by
        itself.

        Every press is followed by a wait for the next line to be drawn: the
        line fades in, and a press that lands during the fade is swallowed, so
        pressing on a fixed interval both wastes time on a fast line and misses
        a slow one.

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
                point = AFFECTION_CHOICE_POINT
                choices += 1
            elif self.affection_talk_appear():
                point = AFFECTION_CONTINUE_POINT
                taps += 1
            else:
                logger.info(f'Talk finished, {taps} lines, {choices} choices')
                return taps

            before = np.array(self.device.image).astype(np.int16)
            self.tap_point(*point)
            if not self.affection_wait_line(before):
                logger.info('The line did not move, press again')

            if taps > TALK_MAX_TAPS:
                logger.warning('Stopped at the tap limit')
                return taps
            if timer.reached():
                logger.warning('Stopped at the time limit')
                return taps

    def affection_wait_line(self, before, timeout=TALK_LINE_WAIT):
        """
        Wait until the line after a press is drawn and has settled.

        Args:
            before (np.ndarray): The frame the press was made on.
            timeout (int, float): Seconds.

        Returns:
            bool: If the screen moved to a new line.
        """
        timeout = Timer(timeout).start()
        previous = before
        moved = False
        still = 0
        while 1:
            self.device.screenshot()
            image = np.array(self.device.image).astype(np.int16)
            if float(np.abs(image - previous).mean()) < TALK_LINE_DIFF:
                # The fade is over: the line is fully drawn and the next press
                # will be taken. Without `moved` an eaten press would look the
                # same as a drawn line, and the caller would never press again.
                still += 1
                if moved and still >= 2:
                    return True
            else:
                moved = True
                still = 0
            previous = image
            if timeout.reached():
                return False

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

    def affection_back_to_list(self, timeout=12):
        """
        Walk back to the character grid.

        The X of the panel goes to the detail page, the X of the detail page
        back to the grid; the loop presses the corner until the grid is really
        there, because either press is dropped now and then.

        Pages:
            in: page_affection or page_character_detail
            out: page_character

        Returns:
            bool: If the grid is back.
        """
        timeout = Timer(timeout).start()
        retry = Timer(2, count=2).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.affection_on_list():
                return True
            if retry.reached():
                retry.reset()
                self.tap_point(1232, 56)
            if timeout.reached():
                logger.warning('Back on the grid did not work')
                return False

    def affection_on_list(self):
        """
        Whether the character grid is on screen.

        Returns:
            bool: If the 「角色」 heading of the grid is there.
        """
        return match(self.device.image, CHAR_TITLE, (60, 10, 240, 70)) > 0.95

    # ----------------------------------------------------------------- input

