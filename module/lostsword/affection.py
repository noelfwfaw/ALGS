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

# The character grid: five columns. Each entry is (x1 of the name plate, x of
# the card centre). The fifth card sits closer to its neighbours than the other
# four and its name plate starts about 45 pixels left of that column's edge; a
# plate read from the grid edge cut the first two characters of every name in
# the last column (迪安·凯特 came back as 凯特).
GRID_COLUMNS = (
    (289, 378),
    (489, 578),
    (689, 778),
    (889, 978),
    (1044, 1133),
)
# The vertical band the cards live in, and the shape of a name plate: a strip of
# bright text across all five columns, ten to twenty pixels high.
GRID_SCAN_TOP = 60
GRID_SCAN_BOTTOM = 720
NAME_BAND_PIXELS = 25
NAME_BAND_MIN = 8
NAME_BAND_MAX = 22
# Name plate, star row and MAX badge are all found as strips; the stars are the
# bright one right under a name, so four strips cover a screen of two rows.
NAME_BAND_COUNT = 4
# Distance from the name label up to the middle of the card.
GRID_CARD_DY = 76
NAME_WIDTH = 145
# How many screens the scan may walk before it gives up. The roster is deep (the
# grid shows two rows at a time and a full account holds dozens of rows), so the
# number is large on purpose: the scan stops at the end of the list by itself,
# and this is only the guard against a list that never ends.
GRID_MAX_SCREENS = 40
# How many drags `affection_scroll_top()` may spend getting back to the first
# row.
GRID_TOP_SWIPES = 40
# Consecutive screens that read the same names before the list is called
# finished. Two, because one drag can be dropped.
GRID_END_TRIES = 2
# A drag that moves the list by about a row. A full-screen drag is fast enough
# to leave a fling behind and the list then travels three rows while the screen
# is read once, which is how a character gets skipped.
GRID_SCROLL_FROM = (640, 620)
GRID_SCROLL_TO = (640, 250)
# Reads taken after one drag until two of them agree. The list eases out, so the
# first read can still show the rows that are leaving.
GRID_SETTLE_READS = 4

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
# How long one press may take to draw the next line, and how much of the screen
# has to change for the new line to count as drawn.
TALK_LINE_WAIT = 3
TALK_LINE_DIFF = 1.0
TALK_MAX_TAPS = 60

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
            # The OCR drops everything that is not a Chinese character, and so
            # does this: 迪安·凯特 is read as 迪安凯特, and comparing the raw
            # config value against that costs a fifth of the similarity.
            value = re.sub(r'[^\u4e00-\u9fa5]', '', value)
            if value:
                names.append(value)
        return names

    def affection_all(self, names):
        """
        Talk to every configured character that still has a talk left.

        The grid is walked once, from its first row to its last, and every
        visible card is compared with the names that are still waiting. A name
        that is not on the current screen is simply not there: the scan goes on,
        because the roster is sorted by level and not by what the user wants to
        talk to - a character can be fifty rows down, and the earlier per-name
        search left the list scrolled after a miss, so one name that could not
        be read took every name after it with it (reported 2026-10-27).

        Pages:
            in: page_character
            out: page_character

        Args:
            names (list): Character names.

        Returns:
            int: How many conversations were had.
        """
        todo = list(names)
        talked = 0
        previous = None
        same = 0
        self.affection_scroll_top()

        for screen in range(GRID_MAX_SCREENS):
            if not todo:
                break
            cards = self.affection_read_screen()
            texts = tuple(text for _, _, text in cards)
            if previous is not None and texts == previous:
                # The drag moved the list to its end: the same rows are read
                # again. Two in a row, because one drag can be dropped.
                same += 1
                if same >= GRID_END_TRIES:
                    logger.info('The grid does not scroll any more, end of the list')
                    break
            else:
                same = 0
            previous = texts

            found = self.affection_match(todo, cards)
            if found is None:
                self.affection_scroll_step()
                continue

            name, (x, y) = found
            logger.hr(f'Character {name}', level=2)
            todo.remove(name)
            logger.info(f'{name}: card at ({x}, {y})')
            if not self.affection_open_card(x, y):
                logger.warning(f'{name}: the card did not open')
                same = 0
                continue
            if self.affection_open():
                if self.affection_talk_available():
                    self.affection_walk()
                    talked += 1
                    logger.info(f'{name}: talk finished')
                else:
                    logger.info(f'{name}: no talk left for today')
            else:
                logger.warning(f'{name}: the affection panel did not open')
            self.affection_back_to_list()
            # The grid keeps the offset it was left at, but the screen is read
            # again instead of trusted: a card press that opened nothing leaves
            # the same rows, and the next name may be on them.
            previous = None
            same = 0

        if todo:
            logger.warning(f'Not found on the character page: {", ".join(todo)}')
        return talked

    # -------------------------------------------------------------------- grid

    def affection_read_screen(self):
        """
        OCR the name of every visible card, once the list has settled.

        The name plates are found first instead of being read at a fixed y: the
        list stops wherever the drag left it, so a plate can be anywhere in its
        half of the screen. Reading fixed rows missed whole characters and read
        star rows as names when the offset was off by twenty pixels (measured
        2026-10-27, that is why 女仆丽塔 was never found).

        A read is repeated while it keeps changing: the list eases out after a
        drag, and a frame taken during that carries half a row of each name.

        Returns:
            list: (x, y, text) per card, x/y being the point to press for that
                card and text what its plate says ('' when unreadable).
        """
        previous = None
        cards = []
        for _ in range(GRID_SETTLE_READS):
            self.device.screenshot()
            cards = self.affection_read_image()
            texts = tuple(text for _, _, text in cards)
            if previous is not None and texts == previous:
                return cards
            previous = texts
        return cards

    def affection_read_image(self):
        """
        OCR the name plates of the current screenshot.

        Returns:
            list: (x, y, text) per card.
        """
        image = self.device.image
        cards = []
        for y1, y2 in self.affection_name_bands(image):
            for x1, x2 in GRID_COLUMNS:
                area = (x1, y1, x1 + NAME_WIDTH, y2)
                text = read_text(image, area)
                if text:
                    logger.attr(f'Card y{y1}', f'{x1} {text}')
                cards.append((x2, y1 - GRID_CARD_DY, text))
        return cards

    def affection_name_bands(self, image):
        """
        Find the rows of name plates on the grid.

        A plate is a strip of bright text about fifteen pixels high that runs
        across all five columns; the star row under it and the MAX badge over it
        are found as well and simply do not match any name.

        Args:
            image (np.ndarray): Screenshot.

        Returns:
            list: (y1, y2) of the strips, top to bottom.
        """
        band = image[GRID_SCAN_TOP:GRID_SCAN_BOTTOM, 250:1160].astype(np.int16)
        bright = ((band[:, :, 0] > 150) & (band[:, :, 1] > 150)
                  & (band[:, :, 2] > 150)).sum(axis=1)
        strips = []
        start = None
        for i, value in enumerate(bright):
            if value > NAME_BAND_PIXELS and start is None:
                start = i
            elif value <= NAME_BAND_PIXELS and start is not None:
                if NAME_BAND_MIN <= i - start <= NAME_BAND_MAX:
                    strips.append((GRID_SCAN_TOP + start, GRID_SCAN_TOP + i))
                start = None
        return strips[:NAME_BAND_COUNT]

    def affection_match(self, todo, cards):
        """
        Pick the card that best matches one of the wanted names.

        Args:
            todo (list): Names still waiting.
            cards (list): (x, y, text) of the visible cards.

        Returns:
            tuple: (name, (x, y)), None when no card is close to any name.
        """
        best = None
        best_ratio = NAME_SIMILARITY
        for x, y, text in cards:
            if not text:
                continue
            for name in todo:
                ratio = difflib.SequenceMatcher(None, name, text).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best = (name, (x, y))
        return best

    def affection_scroll_top(self):
        """
        Drag the grid back to its first row.

        The list remembers where it was left, so a scan that starts anywhere
        else is not a scan of the roster. The drags stop as soon as the names on
        screen stop changing, which is the first row - the common case costs one
        read and no drag at all.

        Names are compared instead of pixels: the grid is drawn over a live
        lobby, so a frame compare never sees two identical frames and the loop
        would drag until the click protection fires (measured 2026-10-27).
        """
        previous = None
        for _ in range(GRID_TOP_SWIPES):
            texts = self.affection_screen_texts()
            if previous is not None and texts == previous:
                logger.info('The grid is at its first row')
                return True
            previous = texts
            self.affection_drag(GRID_SCROLL_TO, GRID_SCROLL_FROM)
        logger.warning('The grid did not reach its first row')
        return False

    def affection_scroll_step(self):
        """
        Drag the grid down by about one row.
        """
        self.affection_drag(GRID_SCROLL_FROM, GRID_SCROLL_TO)

    def affection_drag(self, p1, p2):
        """
        Drag the grid and clear the click record afterwards.

        A `drag` rather than a `swipe`: a swipe is fast enough to leave a fling
        behind, and the list then travels three rows while the screen is read
        once. The record is cleared because one deliberate, verified drag per
        step is not the click loop that "too many click for a button" exists to
        catch - and a deep roster would fill it up and kill the task halfway
        down.

        Args:
            p1 (tuple): Start point.
            p2 (tuple): End point.
        """
        self.device.stuck_record_clear()
        self.device.drag(p1=p1, p2=p2)
        self.device.click_record_clear()

    def affection_screen_texts(self):
        """
        The names the current screen shows, as one tuple.

        Read twice when the list is still easing out: two reads that agree are
        the only proof that the screen has stopped moving, and reading a moving
        list cuts the names in half.

        Returns:
            tuple: What every detected plate says.
        """
        return tuple(text for _, _, text in self.affection_read_screen())

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
            self.tap(x, y)
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
            self.tap(*AFFECTION_ENTRY_POINT)
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
            self.tap(*AFFECTION_TALK_POINT)
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
            self.tap(*point)
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
                self.tap(1232, 56)
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

    def tap(self, x, y):
        """
        Press a point with an adb tap.

        Args:
            x (int): Pixel x.
            y (int): Pixel y.
        """
        self.device.adb_shell(['input', 'tap', str(int(x)), str(int(y))])
