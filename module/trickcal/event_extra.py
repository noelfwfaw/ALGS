"""Story skipping, achievement/task claiming, and shop buying for Trickcal events."""

import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import crop
from module.logger import logger
from module.trickcal.assets import (
    E_4_1,
    EVENT_PASS_CLAIM_ALL,
    EVENT_SHOP_BUY_TITLE,
    EVENT_SHOP_CANCEL,
    EVENT_SHOP_CONFIRM,
    EVENT_SHOP_MAX,
    EVENT_SHOP_REWARD,
    EVENT_STORY_NEW,
    EVENT_TASK_CLAIM_ALL,
    REWARD_POPUP,
    REWARD_POPUP_GAIN,
    REWARD_POPUP_GAIN_TALL,
)
from module.trickcal.page import (
    page_event,
    page_event_pass,
    page_event_shop,
    page_event_story,
    page_event_task,
)

EXTRA_OFFSET = (20, 20)

# Cyan NEW badge on the bottom story-ticket strip (438, 522, 495, 543):
# offset [-400, 740] keeps search strictly within [38, 1235] x [492, 573].
STORY_NEW_OFFSET = (-400, -30, 740, 30)
STORY_MAX_EPISODES = 12
STORY_EPISODE_TIMEOUT = 60
STORY_TOTAL_TIMEOUT = 300

# Three tabs on the right half of 活动任务.
EVENT_TASK_TABS = (
    ('每日任务', (508, 92, 728, 134)),
    ('成就', (756, 92, 976, 134)),
    ('像素异世界', (1004, 92, 1224, 134)),
)
TASK_CLAIM_COLOR_THRESHOLD = 30
TASK_TAB_YELLOW_PIXELS = 3000

# Event-exclusive pass plaque on the bottom-right of `page_event` (title rotates per event).
EVENT_PASS_ENTRY_AREA = (945, 622, 1135, 670)
EVENT_PASS_CLAIM_COLOR_THRESHOLD = 30

# Suitcase item grid on 活动商店. Unsold cream/white cards sit on a dark grey-brown
# suitcase; sold cards turn dark grey with a green 已购买 stamp.
EVENT_SHOP_GRID = (545, 130, 1215, 625)
EVENT_SHOP_MAX_BUYS = 40
SHOP_MAX_COLOR_THRESHOLD = 25
SHOP_CONFIRM_COLOR_THRESHOLD = 35

SHOP_REWARD_POPUPS = (
    EVENT_SHOP_REWARD,
    REWARD_POPUP,
    E_4_1,
    REWARD_POPUP_GAIN,
    REWARD_POPUP_GAIN_TALL,
)


def _tap_box(area, name):
    """Build a tap-only Button for a dynamic or fixed rectangle."""
    return Button(area=area, color=(0, 0, 0), button=area, name=name)


def _task_tab_selected(image, tab_area):
    """Return True when the given 活动任务 pill is highlighted bright yellow."""
    patch = crop(image, tab_area)
    yellow = (patch[:, :, 0] > 220) & (patch[:, :, 1] > 175) & (patch[:, :, 2] < 140)
    return int(yellow.sum()) >= TASK_TAB_YELLOW_PIXELS


def _shop_card_buy_area(card):
    """Target the bottom price strip of an event shop card to avoid item info tooltips."""
    x1, y1, x2, y2 = card
    return (x1 + 24, y1 + int((y2 - y1) * 0.80), x2 - 24, y2 - 8)


def _clamped_story_ticket_box(button_area):
    """Clamp a shifted story-ticket tap box strictly within `[20, 1260]` horizontally."""
    bx1, by1, bx2, by2 = button_area
    tx1 = max(20, min(bx1, 1240))
    tx2 = max(tx1 + 20, min(bx2, 1260))
    return (tx1, by1, tx2, by2)


def find_event_shop_unsold_cards(image):
    """
    Find every full, unsold item card in the event shop grid, ordered strictly
    top-to-bottom then left-to-right.

    Sold cards darken with an 「已购买」 stamp, and empty bottom slots reveal dark
    suitcase wood, so bright cream/white component segmentation cleanly keeps
    only complete, purchasable cards and excludes peeking partial rows or wide
    item-info tooltips.

    Returns:
        list[tuple[int, int, int, int]]: Full-screen `(x1, y1, x2, y2)` boxes.
    """
    gx1, gy1, gx2, gy2 = EVENT_SHOP_GRID
    roi = image[gy1:gy2, gx1:gx2]
    white = (
        (roi[:, :, 0] > 235) & (roi[:, :, 1] > 230) & (roi[:, :, 2] > 215)
    ).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    closed = cv2.morphologyEx(white, cv2.MORPH_CLOSE, kernel)
    num, _, stats, _ = cv2.connectedComponentsWithStats(closed)
    cards = []
    for idx in range(1, num):
        x, y, w, h, _ = stats[idx]
        if 160 <= w <= 240 and 165 <= h <= 240:
            cards.append((gx1 + int(x), gy1 + int(y), gx1 + int(x + w), gy1 + int(y + h)))
    cards.sort(key=lambda c: (c[1] // 80, c[0]))
    return cards


class TrickcalEventExtra:
    """Mixin implementing story skipping, task claiming, and shop purchases."""

    def _handle_event_reward(self):
        """Dismiss any standard or taller event reward popup via its bottom hint."""
        if self.handle_reward_popup():
            return True
        if self.appear(EVENT_SHOP_REWARD, offset=EXTRA_OFFSET, interval=2):
            logger.info('Event reward popup, tap bottom continue')
            self.device.click(EVENT_SHOP_REWARD)
            return True
        return False

    def _wait_story_episode_end(self):
        """Skip the opened episode (including 继续观看 chains) until back on `page_event_story`."""
        idle = Timer(STORY_EPISODE_TIMEOUT).start()
        for _ in self.loop(timeout=STORY_TOTAL_TIMEOUT):
            self.device.stuck_record_clear()
            if self.ui_page_appear(page_event_story):
                return True
            if self._handle_event_reward():
                idle.reset()
                continue
            if self.handle_event_story_or_guide():
                idle.reset()
                continue
            if idle.reached():
                break
        logger.warning('Timed out waiting to return to 活动剧情')
        return False

    def _scroll_story_left(self):
        """Scroll the bottom episode strip left to expose later unwatched tickets."""
        logger.info('Scroll 活动剧情 strip to check later episodes')
        self.device.drag(
            (950, 610),
            (350, 610),
            point_random=(-10, -10, 10, 10),
            name='EVENT_STORY_SCROLL',
        )
        settle = Timer(0.8).start()
        for _ in self.loop(timeout=2):
            if settle.reached() and self.ui_page_appear(page_event_story):
                return

    def event_story_clear(self):
        """
        Enter 活动剧情 and skip every unlocked episode marked with `NEW`.
        """
        logger.hr('Event story', level=2)
        self.ui_ensure(page_event_story)

        for _ in range(STORY_MAX_EPISODES):
            found = False
            for _ in self.loop(timeout=2):
                if self.appear(EVENT_STORY_NEW, offset=STORY_NEW_OFFSET):
                    found = True
                    break

            if not found:
                for _ in range(2):
                    self._scroll_story_left()
                    if self.appear(EVENT_STORY_NEW, offset=STORY_NEW_OFFSET):
                        found = True
                        break

            if not found:
                logger.info('No unwatched NEW event story found, done')
                return True

            if EVENT_STORY_NEW.button[2] > 1265:
                self._scroll_story_left()
                found = self.appear(EVENT_STORY_NEW, offset=STORY_NEW_OFFSET)
                if not found:
                    continue

            # Click the ticket beneath NEW until we actually leave page_event_story.
            entered = False
            tap_retry = Timer(2.0)
            left_frames = 0
            for _ in self.loop(timeout=10):
                if self.appear(EVENT_STORY_NEW, offset=STORY_NEW_OFFSET):
                    left_frames = 0
                    if tap_retry.reached():
                        tap_retry.reset()
                        tap_area = _clamped_story_ticket_box(EVENT_STORY_NEW.button)
                        logger.info(f'Open NEW event story episode at {tap_area}')
                        self.device.click(_tap_box(tap_area, 'EVENT_STORY_NEW'))  # alas-lint: allow - guarded by appear(EVENT_STORY_NEW) with STORY_NEW_OFFSET
                    continue
                if self.ui_page_appear(page_event_story):
                    left_frames = 0
                else:
                    left_frames += 1
                    if left_frames >= 2:
                        entered = True
                        break

            if not entered:
                logger.warning('NEW story ticket did not start playback')
                return False

            if not self._wait_story_episode_end():
                return False

        return True

    def event_claim_tasks(self):
        """
        Enter 活动任务 (成就) and claim all lit rewards across all 3 tabs.
        """
        logger.hr('Event tasks & achievements', level=2)
        self.ui_ensure(page_event_task)

        for label, tab_area in EVENT_TASK_TABS:
            self.device.click_record_clear()
            tab_retry = Timer(1.5)
            switched = False
            for _ in self.loop(timeout=6):
                if self._handle_event_reward():
                    continue
                if _task_tab_selected(self.device.image, tab_area):
                    switched = True
                    break
                if self.ui_page_appear(page_event_task) and tab_retry.reached():
                    tab_retry.reset()
                    logger.info(f'Select event task tab: {label}')
                    self.device.click(_tap_box(tab_area, 'EVENT_TASK_TAB'))  # alas-lint: allow - guarded by ui_page_appear(page_event_task)
            if not switched:
                logger.warning(f'Event task tab {label} did not highlight yellow, proceed anyway')

            settle = Timer(0.5).start()
            for _ in self.loop(timeout=2):
                if settle.reached() and self.ui_page_appear(page_event_task):
                    break

            claim_retry = Timer(2.0)
            clean = 0
            for _ in self.loop(timeout=15):
                if self._handle_event_reward():
                    clean = 0
                    continue
                if self.appear(EVENT_TASK_CLAIM_ALL, offset=EXTRA_OFFSET):
                    if EVENT_TASK_CLAIM_ALL.appear_on(
                        self.device.image, threshold=TASK_CLAIM_COLOR_THRESHOLD
                    ):
                        clean = 0
                        if claim_retry.reached():
                            claim_retry.reset()
                            logger.info(f'Claim all on tab {label}')
                            self.device.click(EVENT_TASK_CLAIM_ALL)  # alas-lint: allow - guarded by appear + appear_on lit check
                        continue
                    clean += 1
                    if clean >= 3:
                        logger.info(f'Tab {label}: no rewards to claim')
                        break
                    continue
                if self.ui_page_appear(page_event_task):
                    clean += 1
                    if clean >= 3:
                        break

        return True

    def event_claim_pass(self):
        """
        Open the event-exclusive pass from bottom-right of `page_event` and
        claim all lit rewards via `一键领取`.
        """
        logger.hr('Event pass', level=2)
        self.ui_ensure(page_event)

        entry_retry = Timer(2.0)
        opened = False
        for _ in self.loop(timeout=8):
            if self.ui_page_appear(page_event_pass):
                opened = True
                break
            if self.ui_page_appear(page_event) and entry_retry.reached():
                entry_retry.reset()
                logger.info('Open event-exclusive pass from page_event bottom-right')
                self.device.click(_tap_box(EVENT_PASS_ENTRY_AREA, 'EVENT_PASS_ENTRY'))  # alas-lint: allow - guarded by ui_page_appear(page_event)
        if not opened:
            logger.warning('Event-exclusive pass did not open, skip')
            return False

        claim_retry = Timer(2.0)
        clean = 0
        for _ in self.loop(timeout=15):
            if self._handle_event_reward():
                clean = 0
                continue
            if self.appear(EVENT_PASS_CLAIM_ALL, offset=EXTRA_OFFSET) or EVENT_PASS_CLAIM_ALL.match_luma(
                self.device.image, offset=EXTRA_OFFSET
            ):
                if EVENT_PASS_CLAIM_ALL.appear_on(
                    self.device.image, threshold=EVENT_PASS_CLAIM_COLOR_THRESHOLD
                ):
                    clean = 0
                    if claim_retry.reached():
                        claim_retry.reset()
                        logger.info('Claim all on event pass')
                        self.device.click(EVENT_PASS_CLAIM_ALL)  # alas-lint: allow - guarded by appear/match_luma + appear_on lit check
                    continue
                clean += 1
                if clean >= 3:
                    logger.info('Event pass: no rewards to claim')
                    return True
                continue
            if self.ui_page_appear(page_event_pass):
                clean += 1
                if clean >= 3:
                    return True

        return True

    def _close_shop_cancel(self):
        """Close the 购买商品 dialog via 取消 back to `page_event_shop`."""
        retry = Timer(2.0)
        clean = 0
        for _ in self.loop(timeout=8):
            if self.appear(EVENT_SHOP_CANCEL, offset=EXTRA_OFFSET):
                clean = 0
                if retry.reached():
                    retry.reset()
                    logger.info('Close event shop buy dialog, press 取消')
                    self.device.click(EVENT_SHOP_CANCEL)  # alas-lint: allow - guarded by appear(EVENT_SHOP_CANCEL)
                continue
            if self.ui_page_appear(page_event_shop):
                clean += 1
                if clean >= 2:
                    return True
        return False

    def _shop_reward_active(self):
        """Return True if any reward overlay is still on screen."""
        return any(self.appear(btn, offset=EXTRA_OFFSET) for btn in SHOP_REWARD_POPUPS)

    def _shop_buy_dialog_once(self):
        """
        Inside 购买商品: press 最大 if lit, confirm 购买, and settle rewards.

        Returns:
            bool: True if a purchase succeeded and returned cleanly to shop,
                False if currency was insufficient or the dialog stayed stuck.
        """
        max_clicked = False
        max_settle = Timer(0.4)
        confirm_retry = Timer(2.0)
        confirmed = False
        post_confirm = Timer(4.5)
        reward_seen = False
        clean_shop = 0

        for _ in self.loop(timeout=15):
            if self._handle_event_reward():
                reward_seen = True
                clean_shop = 0
                post_confirm.reset()
                continue

            if self.appear(EVENT_SHOP_BUY_TITLE, offset=EXTRA_OFFSET):
                clean_shop = 0
                if confirmed:
                    if post_confirm.reached():
                        logger.info('Insufficient event currency, cancel purchase')
                        self._close_shop_cancel()
                        return False
                    continue

                if (
                    not max_clicked
                    and self.appear(EVENT_SHOP_MAX, offset=EXTRA_OFFSET)
                    and EVENT_SHOP_MAX.appear_on(
                        self.device.image, threshold=SHOP_MAX_COLOR_THRESHOLD
                    )
                ):
                    logger.info('Press 最大 on event shop dialog')
                    self.device.click(EVENT_SHOP_MAX)  # alas-lint: allow - guarded by appear + appear_on lit check
                    max_clicked = True
                    max_settle = Timer(0.4).start()
                    continue

                if max_clicked and not max_settle.reached():
                    continue

                if self.appear(EVENT_SHOP_CONFIRM, offset=EXTRA_OFFSET) or (
                    self.appear(EVENT_SHOP_CANCEL, offset=EXTRA_OFFSET)
                    and EVENT_SHOP_CONFIRM.match_luma(self.device.image, offset=EXTRA_OFFSET)
                ):
                    if not EVENT_SHOP_CONFIRM.appear_on(
                        self.device.image, threshold=SHOP_CONFIRM_COLOR_THRESHOLD
                    ):
                        logger.info('购买 button is grey/disabled, stop shop buying')
                        self._close_shop_cancel()
                        return False
                    if confirm_retry.reached():
                        confirm_retry.reset()
                        confirmed = True
                        post_confirm = Timer(4.5).start()
                        logger.info('Press 购买 on event shop dialog')
                        self.device.click(EVENT_SHOP_CONFIRM)  # alas-lint: allow - guarded by appear + appear_on lit check
                continue

            if confirmed:
                if self._shop_reward_active():
                    clean_shop = 0
                    continue
                if self.ui_page_appear(page_event_shop):
                    clean_shop += 1
                    if clean_shop >= 2 or reward_seen:
                        return True

        self._close_shop_cancel()
        return False

    def event_shop_buy(self):
        """
        Enter 活动商店 and buy items strictly top-to-bottom, left-to-right.

        Never skips an unbought item to buy the next one, and only reaches the
        bottom infinite gold slot after every item above it is 「已购买」.
        """
        logger.hr('Event shop', level=2)
        self.ui_ensure(page_event_shop)
        unchanged = 0

        for _ in range(EVENT_SHOP_MAX_BUYS):
            if self._handle_event_reward():
                continue

            cards = find_event_shop_unsold_cards(self.device.image)
            if not cards:
                before = crop(self.device.image, EVENT_SHOP_GRID)
                logger.info('No unsold card on current shop view, scroll down')
                self.device.drag(
                    (880, 540),
                    (880, 200),
                    point_random=(-10, -10, 10, 10),
                    name='EVENT_SHOP_SCROLL',
                )
                settle = Timer(0.8).start()
                for _ in self.loop(timeout=2):
                    if settle.reached() and self.ui_page_appear(page_event_shop):
                        break
                after = crop(self.device.image, EVENT_SHOP_GRID)
                diff = float(np.abs(after.astype(np.int16) - before.astype(np.int16)).mean())
                if diff < 2.0:
                    unchanged += 1
                    if unchanged >= 2:
                        logger.info('Reached bottom of event shop with no unsold items')
                        return True
                else:
                    unchanged = 0
                continue

            unchanged = 0
            card = cards[0]
            tap_area = _shop_card_buy_area(card)
            opened = False
            open_retry = Timer(2.0)
            for _ in self.loop(timeout=8):
                if self.appear(EVENT_SHOP_BUY_TITLE, offset=EXTRA_OFFSET):
                    opened = True
                    break
                if self.ui_page_appear(page_event_shop) and open_retry.reached():
                    open_retry.reset()
                    logger.info(f'Open top-most unsold shop item at {card} via price strip {tap_area}')
                    self.device.click(_tap_box(tap_area, 'EVENT_SHOP_CARD'))  # alas-lint: allow - card detected by find_event_shop_unsold_cards() on this frame
            if not opened:
                logger.warning('Shop buy dialog did not open, stop')
                return False

            if not self._shop_buy_dialog_once():
                logger.info('Stopped event shop purchase strictly at current item')
                return True

        return True
