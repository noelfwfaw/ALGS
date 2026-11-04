"""Reading the shelf of an exchange sub shop: where the cards are, and moving it.

The sub shops of 兑换商店 all show a two-row grid that scrolls sideways, about
four columns on screen. Drags do not land the cards on a fixed grid (a 264 px
drag moved the list about 280 px), so nothing here may assume a position: every
stop measures where each card actually is from its white price strip - a bright
band across the bottom of every card that the dark gaps between cards interrupt
- and the caller then OCRs the title right above where that strip says the card
is.

A price band can carry hairline dark seams that break one card into pieces
(measured on 后勤商店: three 1 px seams through a single card), so runs closer
together than a card gap are bridged before the width test.
"""

import numpy as np

from module.coupon.text import read_text
from module.logger import logger

# Every card is a button of the same shape; only its x moves. Row 0 is the top
# row of the grid, row 1 the bottom one.
#
# NAME: where the card title is printed, OCR'd per card.
# STRIP: the white price band across the card bottom - the gaps between cards
#   break it, so a brightness profile over this band yields the cards' real x.
# SOLD: the 已售罄 band over a sold-out card, OCR'd for 售罄.
# TAP: y of the card centre, where the tap that opens the dialog goes.
SHOP_ROWS = (
    {'name': (196, 232), 'strip': (390, 420), 'sold': (300, 340), 'tap': 306},
    {'name': (443, 479), 'strip': (642, 672), 'sold': (548, 588), 'tap': 553},
)
# Left of this the sidebar of the shop covers the cards: a card starting here
# is only partly on screen and its tap would land on the sidebar.
SHOP_SAFE_LEFT = 240
SHOP_SAFE_RIGHT = 1280
# A price strip run shorter than this is the sliver of a card sliding out.
SHOP_MIN_CARD_WIDTH = 200
# A card is 227 px wide; a run wider than this means two cards whose gap did
# not come out dark (the goods were caught mid-scroll). Capping keeps the title
# crop off the neighbour and the tap inside the card that was measured.
SHOP_MAX_CARD_WIDTH = 250
# Strips carry hairline dark seams: runs closer than this are the same card.
SHOP_STRIP_BRIDGE = 16
# The two crop margins a card title is read with: the tight crop keeps more of
# the characters but picks up the decorative brackets of the card frame, the
# wide one is safe from the brackets but can clip a long title.
SHOP_NAME_MARGINS = (12, 25)
# Duration of the hold in every drag - without it the swipe carries momentum
# and the landing position becomes a guess.
SHOP_DRAG_HOLD = 0.4
# Area the drags run through, clear of the sidebar and of the goods.
SHOP_DRAG_Y = 400
# Area the still-check watches while the goods settle: the goods panel only.
SHOP_GOODS_AREA = (240, 180, 1280, 690)
# Mean absolute difference per channel of the goods panel, below which a drag
# did not move the shelf at all. Measured on 后勤商店: a drag that moved the
# list one column scored 52.4, a swallowed one and a drag against the clamped
# end scored 0.01 to 0.44. The card art shimmers faintly, so the line sits
# well above the idle noise and far below a real move.
SHOP_MOVED_DIFF = 2.0
# Distance between two columns, and therefore the drag that advances the shelf
# by exactly one of them.
SHOP_COLUMN_PITCH = 272
# A drag that leaves the goods untouched is retried this many times before the
# shelf counts as clamped - a single one is swallowed now and then.
SHOP_DRAG_RETRY = 4
# How far the sweep walks before giving up on finding the list end. The shops
# show about a dozen columns this week; the cap is what keeps a shelf that
# never clamps from dragging forever.
SHOP_MAX_COLUMNS = 15


class ShopGrid:
    """
    Where the cards of one shop shelf are, and how to move that shelf.

    A mixin, not a `UI`: it only adds measuring and dragging, the tasks bring
    the device and the page graph. Methods assume `self.device`.
    """

    @staticmethod
    def shop_strip_runs(profile):
        """
        The cards of one row, from the brightness profile of its price band.

        Args:
            profile (np.ndarray): count of bright rows per x.

        Returns:
            list[tuple]: (x_left, x_right) of every card wide enough to read.
        """
        raw, start = [], None
        for x, value in enumerate(profile):
            if value > 10 and start is None:
                start = x
            elif value <= 10 and start is not None:
                raw.append((start, x))
                start = None
        if start is not None:
            raw.append((start, len(profile)))

        merged = []
        for x1, x2 in raw:
            if merged and x1 - merged[-1][1] <= SHOP_STRIP_BRIDGE:
                merged[-1] = (merged[-1][0], x2)
            else:
                merged.append((x1, x2))
        return [(x1, x2) for x1, x2 in merged
                if x2 - x1 >= SHOP_MIN_CARD_WIDTH]

    def shop_cards(self):
        """
        The cards on screen, measured from their price strips.

        Returns:
            list[tuple]: (row, x_left, x_right, name_a, name_b) of every card
            wide enough to be read, top row first, left to right. The two
            names are the same title read at two crop margins.
        """
        out = []
        image = self.device.image
        for row, spec in enumerate(SHOP_ROWS):
            y1, y2 = spec['strip']
            band = image[y1:y2, :, :].astype(np.int16)
            profile = (band.mean(axis=2) > 170).sum(axis=0)
            for x1, x2 in self.shop_strip_runs(profile):
                if x1 < SHOP_SAFE_LEFT:
                    continue
                x2 = min(x2, x1 + SHOP_MAX_CARD_WIDTH)
                ny1, ny2 = spec['name']
                names = tuple(
                    read_text(image, (x1 + m, ny1, x2 - m, ny2))
                    for m in SHOP_NAME_MARGINS)
                out.append((row, x1, x2) + names)
        return out

    def shop_columns(self, cards):
        """
        Group cards into columns: a top and a bottom card sharing an x.

        Returns:
            list[[int, tuple, tuple]]: [x_left, top_card, bottom_card], sorted
            left to right. A half of the pair may stay None.

        The tolerance is wide on purpose: a card whose price band sits a few
        pixels lower also catches the bright art above the band, so its
        measured x_left can start ~40 px early (seen on 后勤商店, Ⅲ型自选水晶).
        The pitch between two columns is 272 px, so 70 can never merge
        neighbours.
        """
        columns = []
        for card in cards:
            for column in columns:
                if abs(card[1] - column[0]) < 70:
                    column[1 + card[0]] = card
                    break
            else:
                entry = [card[1], None, None]
                entry[1 + card[0]] = card
                columns.append(entry)
        return sorted(columns, key=lambda c: c[0])

    def shop_drag(self, delta):
        """
        Drag the goods sideways. `delta` > 0 moves them left (forward), the
        direction the sweep travels in.
        """
        x1 = 1000 if delta > 0 else 500
        x2 = max(280, min(1100, x1 - delta))
        self.device.drag((x1, SHOP_DRAG_Y), (x2, SHOP_DRAG_Y),
                         hold_duration=SHOP_DRAG_HOLD, name='SHOP_DRAG')

    def shop_goods_image(self):
        """
        The goods panel of the current frame, as a plain array, for telling a
        drag that moved the shelf from one that was swallowed.
        """
        x1, y1, x2, y2 = SHOP_GOODS_AREA
        return self.device.image[y1:y2, x1:x2, :].astype(np.int16)

    def shop_goods_diff(self, before):
        """Mean absolute difference of the goods panel since `before`."""
        return float(np.abs(before - self.shop_goods_image()).mean())

    def shop_drag_moved(self, before, delta):
        """
        Drag by `delta` and say whether the shelf really moved.

        Args:
            before (np.ndarray): The goods panel before the drag.
            delta (int): Pixels to drag, as `shop_drag` reads it.

        Returns:
            bool: If the goods panel changed. A swallowed drag and a drag
            against the clamped end of the list both leave it untouched, which
            is why the caller retries a few times before calling it the end.
        """
        self.shop_drag(delta)
        self.wait_until_still(SHOP_GOODS_AREA, timeout=4)
        self.device.screenshot()
        if self.shop_goods_diff(before) <= SHOP_MOVED_DIFF:
            return False
        # The goods moved, so the drag did what it was for. A sweep drags a
        # dozen times and more, and the device raises GameTooManyClickError at
        # twelve presses of one name in fifteen, so a verified drag is cleared
        # out of the click record right here.
        self.device.click_record_clear()
        return True

    def shop_scroll_home(self):
        """
        Drag the list back to its start, so the sweep begins at card one.

        Returns:
            bool: If the start was reached. The list clamps there, so a drag
            that leaves the goods untouched means the start; three of them in
            a row, because a single drag is swallowed now and then.
        """
        self.wait_until_still(SHOP_GOODS_AREA, timeout=4)
        still = 0
        for _ in range(15):
            if self.shop_drag_moved(self.shop_goods_image(), -700):
                still = 0
                continue
            still += 1
            if still >= 3:
                logger.info('Shop list is at its start')
                return True
        logger.warning('Shop list did not reach its start')
        return False

    def shop_walk_to(self, column):
        """
        Put column `column` (0-based) at the left edge of the shelf.

        The walk always starts from the shelf's start, because a purchase
        resets the shelf there (see `shop_sweep`); a drag towards the start
        that still moves the goods says it is not, and the shelf is dragged
        back first.

        Args:
            column (int): Index of the column to bring to the left edge.

        Returns:
            int: How many columns the shelf really moved. Short of `column`
            means it clamped - no column sits that far right.
        """
        if self.shop_drag_moved(self.shop_goods_image(), -SHOP_COLUMN_PITCH * 3):
            logger.info('The shelf was not at its start, dragging it back')
            self.shop_scroll_home()
        moved = 0
        for _ in range(column):
            before = self.shop_goods_image()
            for _ in range(SHOP_DRAG_RETRY):
                if self.shop_drag_moved(before, SHOP_COLUMN_PITCH):
                    moved += 1
                    break
                logger.info('The shop list did not take the drag, retrying')
            else:
                logger.info('The shop list is at its end')
                break
        return moved
