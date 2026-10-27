"""Reading the character grid (角色页面) of the affection task.

The grid shows five columns of cards, each card carrying its name at the bottom.
Finding a configured character means reading the whole roster, because the names
have no fixed row: the list is left where the last run dropped it, so a name can
be anywhere from the first screen to the last.

Four things about the read are worth knowing:

- The fifth column's name plate starts about 45 pixels left of that column's
  edge, so reading it from the grid edge cut the first two characters of every
  name in it (迪安·凯特 came back as 凯特).
- The band of a name is found by brightness before OCR runs: the grid sits on a
  live 3D lobby, so the pixels behind the text are always moving and a fixed box
  cannot be trusted.
- Progress is decided by the names that were read, never by pixels.
- The names are compared with `difflib` rather than exactly: the Chinese model
  drops a character now and then (女仆丽塔 comes back as 仆丽塔).

The OCR itself is `utils.read_text()`, which asks for the Chinese model - the
default one reads Chinese as noise.
"""

import difflib
import re

import numpy as np

from module.logger import logger
from module.lostsword.utils import read_text

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

# OCR similarity needed to accept a card as the wanted character. The names are
# read with the Chinese model, which drops a character now and then (「女仆丽塔」
# comes back as 「仆丽塔」), so an exact compare is not enough.
NAME_SIMILARITY = 0.5


class AffectionGrid:
    """
    Find the configured characters on the roster.

    Mixed into `LostswordAffection`. Reading the grid needs the rest of the
    affection flow, so this mixin calls these methods of the composed class:

    - `affection_open()` - walk from the lobby to the grid
    - `affection_open_card(name)` - open a card, return if it was the character
    - `affection_walk(name)` - finish a conversation with that character
    - `affection_talk_available()` - whether its 「对话」 button still has work
    - `affection_back_to_list()` - leave the detail page

    It also uses `self.device` and `self.config`; it never takes the task's
    scheduling or navigation decisions of its own.
    """

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

