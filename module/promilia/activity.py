"""Promilia daily-activity reward claiming."""

import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import crop
from module.exception import TaskFailed
from module.logger import logger
from module.promilia.activity_scroll import PromiliaActivityScroll
from module.promilia.assets import (ACTIVITY_BOX_100, ACTIVITY_BOX_20,
                                    ACTIVITY_BOX_40, ACTIVITY_BOX_60,
                                    ACTIVITY_BOX_80, ACTIVITY_DAILY_ACTIVE,
                                    ACTIVITY_DAILY_TAB, ACTIVITY_TASK_CLAIM,
                                    ACTIVITY_TASK_ONGOING, ACTIVITY_TASK_UPDATED,
                                    ACTIVITY_WEEKLY_ACTIVE)
from module.promilia.page import page_activity, page_main
from module.promilia.promilia_ui import PromiliaUI


ACTIVITY_OFFSET = (20, 20)
ACTIVITY_TIMEOUT = 15
ACTIVITY_POINT_WAIT = 1
ACTIVITY_SETTLE_FRAMES = 2
ACTIVITY_READY_FRAMES = 3
ACTIVITY_TASK_COLUMN = (1095, 140, 1200, 570)
ACTIVITY_TASK_CONTENT = (500, 140, 1095, 570)
ACTIVITY_TASK_CARD = (500, 133, 1095, 573)
ACTIVITY_TASK_CARD_BRIGHT = 195
ACTIVITY_TASK_CARD_RATIO = 0.55
ACTIVITY_TASK_CARD_MIN_HEIGHT = 95
ACTIVITY_TASK_CARD_MIN_BANDS = 3
ACTIVITY_TASK_SIMILARITY = 0.85
ACTIVITY_TASK_ONGOING_SIMILARITY = 0.92
ACTIVITY_TASK_STATE_MARGIN = 0.15
ACTIVITY_TASK_CONTENT_DIFF = 1.5
ACTIVITY_EMPTY_SECONDS = 0.5
ACTIVITY_SCROLL_SECONDS = 3
ACTIVITY_SCROLL_WINDOWS = 12
ACTIVITY_BOX_RED_MIN = 8
ACTIVITY_BOXES = (
    (ACTIVITY_BOX_20, (442, 608, 466, 638)),
    (ACTIVITY_BOX_40, (617, 608, 641, 638)),
    (ACTIVITY_BOX_60, (792, 608, 816, 638)),
    (ACTIVITY_BOX_80, (967, 608, 991, 638)),
    (ACTIVITY_BOX_100, (1142, 608, 1166, 638)),
)


class PromiliaActivity(PromiliaUI):
    """
    Claim daily activity points, then one lit milestone box.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        self.ui_ensure(page_main)
        self.activity_claim()
        self.config.task_delay(server_update=True)

    def activity_claim(self):
        """
        Open the activity page, claim the daily tab and return to the lobby.

        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Daily activity', level=2)
        self.ui_ensure(page_activity)
        self.activity_ensure_daily()
        self.activity_claim_all_points()
        if self._activity_points_complete:
            self.activity_claim_box(scroll=self._activity_scroll)
        self.ui_goto_main()

    def activity_ensure_daily(self, timeout=ACTIVITY_TIMEOUT):
        """
        Switch to the daily tab and confirm its selected state.

        Pages:
            in: page_activity
            out: page_activity (daily)
        """
        for _ in self.loop(timeout=timeout):
            if self.appear(ACTIVITY_DAILY_ACTIVE, offset=ACTIVITY_OFFSET):
                return True
            if self.appear(ACTIVITY_WEEKLY_ACTIVE, offset=ACTIVITY_OFFSET):
                if self.appear_then_click(ACTIVITY_DAILY_TAB, offset=ACTIVITY_OFFSET, interval=3):
                    continue
            if self.handle_activity_reward():
                continue
        self.activity_fail('Promilia daily activity tab was not selected')

    def activity_task_states(self):
        """Classify the visible daily rows as 领取, 前往 or 进行中."""
        ACTIVITY_TASK_CLAIM.ensure_template()
        ACTIVITY_TASK_UPDATED.ensure_template()
        ACTIVITY_TASK_ONGOING.ensure_template()
        column = crop(self.device.image, ACTIVITY_TASK_COLUMN, copy=False)
        claim = cv2.matchTemplate(ACTIVITY_TASK_CLAIM.image, column, cv2.TM_CCOEFF_NORMED)
        updated = cv2.matchTemplate(ACTIVITY_TASK_UPDATED.image, column, cv2.TM_CCOEFF_NORMED)
        ongoing = cv2.matchTemplate(ACTIVITY_TASK_ONGOING.image, column, cv2.TM_CCOEFF_NORMED)
        scores = (claim, updated, ongoing)
        score_maps = []
        for index, score in enumerate(scores):
            if index == 0:
                valid = (score > ACTIVITY_TASK_SIMILARITY) & ((score - updated) > ACTIVITY_TASK_STATE_MARGIN)
            elif index == 1:
                valid = ((score > ACTIVITY_TASK_SIMILARITY)
                         & ((score - claim) > ACTIVITY_TASK_STATE_MARGIN)
                         & ((score - ongoing) > ACTIVITY_TASK_STATE_MARGIN))
            else:
                valid = ((score > ACTIVITY_TASK_ONGOING_SIMILARITY)
                         & ((score - claim) > ACTIVITY_TASK_STATE_MARGIN)
                         & ((score - updated) > ACTIVITY_TASK_STATE_MARGIN))
            score_maps.append(np.where(valid, score, -1))

        matches = []
        height, width = ACTIVITY_TASK_CLAIM.image.shape[:2]
        for _ in range(6):
            best_value = -1
            best_state = None
            best_point = None
            for state, score in zip(('claim', 'goto', 'ongoing'), score_maps):
                _, value, _, point = cv2.minMaxLoc(score)
                if value > best_value:
                    best_value = value
                    best_state = state
                    best_point = point
            if best_state is None:
                break
            x = ACTIVITY_TASK_COLUMN[0] + best_point[0]
            y = ACTIVITY_TASK_COLUMN[1] + best_point[1]
            matches.append(((x, y, x + width, y + height), best_state))
            for score in score_maps:
                score[max(0, best_point[1] - 25):best_point[1] + 26,
                      max(0, best_point[0] - 20):best_point[0] + 21] = -1
        matches.sort(key=lambda match: match[0][1])
        return matches

    def activity_find_claims(self):
        """Find claim buttons in the visible list without treating 前往 as 领取."""
        matches = self.activity_task_states()
        self.device.stuck_record_add(ACTIVITY_TASK_CLAIM)
        return [area for area, state in matches if state == 'claim']

    def activity_row_states(self, target, states):
        """Return the classified states on the row containing target."""
        center = (target[1] + target[3]) // 2
        height = target[3] - target[1]
        return [state for area, state in states
                if abs((area[1] + area[3]) // 2 - center) <= height]

    def activity_row_content(self, area):
        """Capture the task text and progress region used to detect row replacement."""
        return crop(self.device.image,
                    (ACTIVITY_TASK_CONTENT[0], area[1], ACTIVITY_TASK_CONTENT[2], area[3]),
                    copy=True)

    @staticmethod
    def activity_content_same(first, second):
        """Compare two card crops tolerating live frosted-glass background jitter."""
        if first is None or second is None or first.shape != second.shape:
            return False
        diff = np.abs(first.astype(np.int16) - second.astype(np.int16))
        return float(np.mean(diff)) <= ACTIVITY_TASK_CONTENT_DIFF

    def _activity_window_same(self, prev_sig, prev_content, signature, content):
        """Whether two verified windows match structurally and visually within jitter."""
        return (prev_sig == signature
                and self.activity_content_same(prev_content, content))

    def activity_claim_received(self, waiting, states):
        """Accept only a positive successor state or changed same-position task content."""
        row_states = self.activity_row_states(waiting['area'], states)
        if any(state != 'claim' for state in row_states):
            return True
        if 'claim' in row_states:
            content = self.activity_row_content(waiting['area'])
            if not self.activity_content_same(content, waiting['content']):
                return True
        return False

    def activity_card_bands(self):
        """Return full visible task-card bands, ignoring clipped edge rows."""
        image = crop(self.device.image, ACTIVITY_TASK_CARD, copy=False)
        bright = (image.mean(axis=2) > ACTIVITY_TASK_CARD_BRIGHT).mean(axis=1)
        mask = bright > ACTIVITY_TASK_CARD_RATIO
        edges = np.flatnonzero(np.diff(np.r_[False, mask, False]))
        bands = [(int(y1), int(y2)) for y1, y2 in edges.reshape(-1, 2)
                 if y2 - y1 >= ACTIVITY_TASK_CARD_MIN_HEIGHT]
        return [(ACTIVITY_TASK_CARD[1] + y1, ACTIVITY_TASK_CARD[1] + y2)
                for y1, y2 in bands]

    def activity_window_state(self, scroll=None):
        """Return a positively verified list window, or None while it is unreadable."""
        if not self.appear(ACTIVITY_DAILY_ACTIVE, offset=ACTIVITY_OFFSET):  # alas-lint: allow R5 -- unknown frames reset readiness without clicking.
            return None
        position = scroll.position() if scroll is not None else None
        if scroll is not None and position is None:
            return None
        states = self.activity_task_states()
        bands = self.activity_card_bands()
        if len(states) < ACTIVITY_TASK_CARD_MIN_BANDS or len(bands) < ACTIVITY_TASK_CARD_MIN_BANDS:
            return None
        centers = [(area[1] + area[3]) // 2 for area, _ in states]
        if any(not any(y1 <= center < y2 for center in centers) for y1, y2 in bands):
            return None
        content = crop(self.device.image, ACTIVITY_TASK_CARD, copy=True)
        signature = (round(position, 3) if position is not None else None,
                     tuple(bands), tuple(states))
        return position, states, signature, content

    def activity_wait_ready(self, timeout, box=False, scroll=None):
        """Wait for a stable, fully classified window before acting or accepting empty."""
        previous = None
        prev_content = None
        stable = 0
        settle = Timer(ACTIVITY_EMPTY_SECONDS).start()
        for _ in self.loop(timeout=timeout):
            if self.handle_activity_reward():
                previous = None
                prev_content = None
                stable = 0
                settle.reset()
                continue
            window = self.activity_window_state(scroll)
            if window is None:
                previous = None
                prev_content = None
                stable = 0
                settle.reset()
                continue
            states = window[1]
            badges = tuple(self.activity_box_has_badge(badge) for _, badge in ACTIVITY_BOXES)
            actionable = any(badges) if box else any(state == 'claim' for _, state in states)
            signature = (window[2], badges)
            if self._activity_window_same(previous, prev_content, signature, window[3]):
                stable += 1
            else:
                previous = signature
                prev_content = window[3]
                stable = 0
                settle.reset()
            if actionable:
                return True
            if stable >= ACTIVITY_READY_FRAMES and settle.reached():
                return True
        self.activity_fail('Promilia daily activity list was not ready')

    def activity_click_claim(self, area):
        """Click one freshly matched row, throttling swallowed clicks per task."""
        content = self.activity_row_content(area)
        last = getattr(self, '_activity_last_claim', None)
        if last is not None and abs(last[0] - area[1]) <= 4 and self.activity_content_same(content, last[1]):
            token = last[2]
        else:
            token = getattr(self, '_activity_claim_seq', 0) + 1
            self._activity_claim_seq = token
        key = (ACTIVITY_TASK_CLAIM.name, token)
        timer = self.get_interval_timer(key, interval=2, renew=True)
        if not timer.reached():
            return False
        button = Button(area=area, color=ACTIVITY_TASK_CLAIM.color,
                        button=area, name=ACTIVITY_TASK_CLAIM.name)
        self.device.click(button)  # alas-lint: allow R13 -- caller matched this rectangle; outer loop verifies or retries.
        self._activity_last_claim = (area[1], content, token)
        timer.reset()
        return True

    def activity_claim_points(self, timeout=ACTIVITY_TIMEOUT, claim_wait=ACTIVITY_POINT_WAIT, scroll=None):
        """
        Claim every completed task in one verified list window.

        Pages:
            in: page_activity (daily)
            out: same page

        Returns:
            bool: Whether a completed task was claimed.
        """
        deadline = Timer(timeout).start()
        remaining = max(0, timeout - deadline.current_time())
        if remaining <= 0:
            self.activity_fail('Promilia daily activity list was not ready')
        if not self.wait_until_appear(ACTIVITY_DAILY_ACTIVE, offset=ACTIVITY_OFFSET,
                                      skip_first_screenshot=True, timeout=min(claim_wait, remaining)):
            if self.appear(ACTIVITY_WEEKLY_ACTIVE, offset=ACTIVITY_OFFSET):
                return False
            self.activity_fail('Promilia daily activity list was not ready')
        remaining = max(0, timeout - deadline.current_time())
        if claim_wait and not self.activity_wait_ready(remaining, scroll=scroll):
            return False

        self._activity_last_claim = None
        claimed = False
        waiting = None
        settled = 0
        previous = None
        prev_content = None
        settle = Timer(ACTIVITY_EMPTY_SECONDS).start()
        remaining = max(0, timeout - deadline.current_time())
        for _ in self.loop(timeout=remaining):
            if self.handle_activity_reward():
                settled = 0
                previous = None
                prev_content = None
                settle.reset()
                continue
            window = self.activity_window_state(scroll)
            if window is None:
                settled = 0
                previous = None
                prev_content = None
                settle.reset()
                continue

            states = window[1]
            claims = [area for area, state in states if state == 'claim']
            if waiting is not None:
                if self.activity_claim_received(waiting, states):
                    claimed = True
                    waiting = None
                    self._activity_last_claim = None
                    settled = 0
                    previous = None
                    prev_content = None
                    settle.reset()
                elif 'claim' not in self.activity_row_states(waiting['area'], states):
                    settled = 0
                    previous = None
                    prev_content = None
                    settle.reset()
                    continue
                else:
                    settled = 0
                    previous = None
                    prev_content = None
                    settle.reset()
            elif claims:
                settled = 0
                previous = None
                prev_content = None
                settle.reset()
            else:
                if self._activity_window_same(previous, prev_content, window[2], window[3]):
                    settled += 1
                else:
                    previous = window[2]
                    prev_content = window[3]
                    settled = 0
                    settle.reset()
                if settled >= ACTIVITY_SETTLE_FRAMES and settle.reached():
                    return claimed

            if claims and self.activity_click_claim(claims[0]):
                area = claims[0]
                waiting = {'area': area, 'content': self.activity_row_content(area)}
                settled = 0
                previous = None
                prev_content = None
                settle.reset()
        self.activity_fail('Promilia daily activity list did not settle after claiming')

    def activity_claim_all_points(self, timeout=ACTIVITY_TIMEOUT):
        """Scan overlapping windows from the top to a positively verified bottom."""
        scroll = PromiliaActivityScroll(self)
        self._activity_scroll = scroll
        self._activity_points_complete = False
        deadline = Timer(timeout).start()
        remaining = max(0, timeout - deadline.current_time())
        if remaining <= 0:
            self.activity_fail('Promilia daily activity scan timed out')
        if not scroll.set_top(timeout=min(ACTIVITY_SCROLL_SECONDS, remaining)):
            self.activity_fail('Promilia daily activity list could not return to the top')
        claimed = False
        for _ in range(ACTIVITY_SCROLL_WINDOWS):
            remaining = max(0, timeout - deadline.current_time())
            if remaining <= 0:
                self.activity_fail('Promilia daily activity scan timed out')
            if self.activity_claim_points(timeout=remaining, scroll=scroll):
                claimed = True
            if scroll.at_bottom():
                self._activity_points_complete = True
                return claimed
            remaining = max(0, timeout - deadline.current_time())
            if not scroll.next_page(timeout=min(ACTIVITY_SCROLL_SECONDS, remaining)):
                self.activity_fail('Promilia daily activity list did not advance')
            self.device.click_record_clear()
        self.activity_fail('Promilia daily activity scan exhausted its window limit')

    def activity_box_has_badge(self, badge):
        """Return whether the fixed milestone badge region contains red pixels."""
        patch = crop(self.device.image, badge)
        red, green, blue = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
        marker = (red > 150) & (red > green * 1.35) & (red > blue * 1.20)
        return np.count_nonzero(marker) >= ACTIVITY_BOX_RED_MIN

    def activity_claim_box(self, timeout=ACTIVITY_TIMEOUT, scroll=None):
        """
        Click the first lit milestone box once and close its reward panel.

        Pages:
            in: page_activity (daily)
            out: same page

        Returns:
            bool: Whether a lit box was claimed.
        """
        if scroll is not None:
            if not getattr(self, '_activity_points_complete', False) or not scroll.at_bottom():
                self.activity_fail('Promilia daily activity boxes were opened before the list bottom')
        if not self.wait_until_appear(ACTIVITY_DAILY_ACTIVE, offset=ACTIVITY_OFFSET,
                                      skip_first_screenshot=True, timeout=ACTIVITY_POINT_WAIT):
            if self.appear(ACTIVITY_WEEKLY_ACTIVE, offset=ACTIVITY_OFFSET):
                return False
            self.activity_fail('Promilia daily activity list was not ready')
        self.activity_wait_ready(timeout, box=True, scroll=scroll)
        for button, badge in ACTIVITY_BOXES:
            # The badge is the claim state; lit artwork must not have to match the gray template.
            if self.activity_box_has_badge(badge):
                if scroll is not None and not scroll.at_bottom():
                    self.activity_fail('Promilia daily activity boxes were opened before the list bottom')
                self.device.click(button)  # alas-lint: allow R13 -- positive badge evidence was checked in the current frame.
                return self.activity_wait_reward(timeout=timeout)
        return False

    def activity_wait_reward(self, timeout=ACTIVITY_TIMEOUT):
        """
        Wait for a delayed reward panel, close it once and confirm the daily page.

        Pages:
            in: page_activity (daily)
            out: same page
        """
        seen_reward = False
        for _ in self.loop(timeout=timeout):
            if self.handle_activity_reward():
                seen_reward = True
                continue
            if (seen_reward and not getattr(self, '_activity_reward_closing', False)
                    and self.appear(ACTIVITY_DAILY_ACTIVE, offset=ACTIVITY_OFFSET)):
                return True
        self.activity_fail('Promilia activity reward popup was not observed and closed')

    def activity_fail(self, message):
        """Delay the failed attempt and report it without marking success."""
        logger.warning(message)
        self.config.task_delay(success=False)
        raise TaskFailed(message)
