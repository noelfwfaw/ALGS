"""Comprehensive preparation (全域整备 / 构析勘探 & 本周奖励) for 雷索纳斯."""

import re

import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import load_image
from module.exception import GameStuckError
from module.logger import logger
from module.ocr.ocr import Ocr
from module.resonance import assets
from module.resonance.clarity import handle_clarity_recovery, normalize_clarity_item_mode
from module.resonance.page import page_resonance_prep, page_resonance_survey
from module.resonance.resonance_ui import ResonanceUI


OFFSET = (5, 5)
SURVEY_CLARITY_PLUS_BOX = (1198, 22, 1236, 50)
# Setting drawer rows inside 构析勘探, ordered top to bottom as shown on screen.
TREE_ROWS = (
    ('red', (23, 349, 448, 403)),      # 乱序根须（红树）
    ('white', (23, 409, 448, 463)),    # 异构厄枝（白树）
    ('rainbow', (23, 469, 448, 523)),  # 混响浮标（彩树）
    ('purple', (23, 529, 448, 583)),   # 桦树浮标（紫树）
)
BIRCH_ROI = (84, 535, 219, 577)
WEEKLY_BADGE_ROI = (588, 620, 618, 650)
MILESTONE_TRACK_ROI = (420, 215, 1255, 505)
DEFAULT_MILESTONE_BOXES = (
    (539, 226, 648, 334),
    (735, 386, 844, 494),
    (931, 226, 1040, 334),
    (1127, 386, 1236, 494),
)

CLARITY_OCR = Ocr(
    (1120, 18, 1225, 55),
    lang='cnocr', threshold=128, alphabet='0123456789/', name='Survey clarity',
)
COST_OCR = Ocr(
    (945, 670, 1020, 705),
    lang='cnocr', threshold=128, alphabet='0123456789-', name='Survey battle cost',
)

_BIRCH_GRAY_CACHE = None


def read_clarity_insufficient(image):
    """Return True when battle detail panel shows remaining clarity below battle cost."""
    clarity_text = CLARITY_OCR.ocr(image)
    m_cur = re.search(r'(\d+)\s*/\s*\d+', str(clarity_text))
    if not m_cur:
        return False
    cur = int(m_cur.group(1))
    cost_text = COST_OCR.ocr(image)
    m_cost = re.search(r'(\d+)', str(cost_text))
    if not m_cost:
        return False
    cost = int(m_cost.group(1))
    return cost > 0 and cur < cost


def _load_birch_gray():
    """Return cached grayscale template for setting-drawer detection."""
    global _BIRCH_GRAY_CACHE
    if _BIRCH_GRAY_CACHE is None:
        _BIRCH_GRAY_CACHE = cv2.cvtColor(load_image(assets.TEMPLATE_SURVEY_BIRCH.file), cv2.COLOR_RGB2GRAY)
    return _BIRCH_GRAY_CACHE


def _box_button(box, name):
    """Build an ad-hoc clickable Button for dynamic UI slots."""
    return Button(area=box, color=(), button=box, name=name)


def is_setting_panel_open(image):
    """Return True if the 构析勘探 target-setting drawer is currently expanded."""
    x1, y1, x2, y2 = BIRCH_ROI
    roi_g = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_RGB2GRAY)
    match = cv2.matchTemplate(roi_g, _load_birch_gray(), cv2.TM_CCOEFF_NORMED)
    score = max(abs(float(match.min())), abs(float(match.max())))
    return score >= 0.70


def is_tree_row_selected(image, box):
    """Return True if a target-tree toggle row is enabled (bright mint highlight)."""
    _, y1, _, y2 = box
    strip = image[y1 + 8:y2 - 8, 250:330]
    mean_rgb = strip.mean(axis=(0, 1))
    return bool(mean_rgb[1] > 150 and mean_rgb[2] > 120)


def has_weekly_reward_badge(image):
    """Return True if the red '!' badge is visible on 查看本周奖励."""
    x1, y1, x2, y2 = WEEKLY_BADGE_ROI
    roi = image[y1:y2, x1:x2]
    r = roi[:, :, 0].astype(np.int16)
    g = roi[:, :, 1].astype(np.int16)
    b = roi[:, :, 2].astype(np.int16)
    return int(np.count_nonzero((r > 180) & (g < 60) & (b < 60))) >= 20


def find_weekly_milestone_buttons(image):
    """Detect visible milestone reward item boxes inside the 凭证置换 timeline."""
    x1, y1, x2, y2 = MILESTONE_TRACK_ROI
    roi = image[y1:y2, x1:x2]
    r = roi[:, :, 0].astype(np.int16)
    b = roi[:, :, 2].astype(np.int16)
    blue_mask = ((b > 170) & (b - r > 70)).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(blue_mask)
    boxes = []
    for idx in range(1, count):
        bx, by, bw, bh, _ = stats[idx]
        if bw > 80 and bh > 80:
            boxes.append((int(x1 + bx), int(y1 + by), int(x1 + bx + bw), int(y1 + by + bh)))
    boxes.sort()
    if not boxes:
        boxes = list(DEFAULT_MILESTONE_BOXES)
    return [_box_button(box, f'PREP_MILESTONE_{i}') for i, box in enumerate(boxes)]


class ResonancePreparation(ResonanceUI):
    """Run 全域整备 -> 构析勘探 auto-crusade and claim weekly progress rewards."""

    def desired_targets(self):
        """Return target tree selection mapping from user config."""
        return {
            'purple': bool(self.config.ResonancePreparation_FightPurple),
            'rainbow': bool(self.config.ResonancePreparation_FightRainbow),
            'white': bool(self.config.ResonancePreparation_FightWhite),
            'red': bool(self.config.ResonancePreparation_FightRed),
        }

    def _set_setting_panel(self, want_open):
        """Expand or collapse the target-tree drawer on 构析勘探."""
        self.interval_clear(assets.SURVEY_SETTING)
        for _ in self.loop(timeout=12):
            if self.ui_page_appear(page_resonance_survey, offset=OFFSET):
                if is_setting_panel_open(self.device.image) == want_open:
                    return
                self.appear_then_click(assets.SURVEY_SETTING, offset=OFFSET, interval=1.5)
        raise GameStuckError(f'Resonance survey setting panel did not reach open={want_open}')

    def _set_single_tree(self, name, box, want_on):
        """Toggle one tree row inside the expanded setting drawer until it matches want_on."""
        btn = _box_button(box, f'SURVEY_TREE_{name.upper()}')
        retry = Timer(1.2)
        for _ in self.loop(timeout=8):
            if self.ui_page_appear(page_resonance_survey, offset=OFFSET):
                if is_tree_row_selected(self.device.image, box) == want_on:
                    return
                if self.appear(assets.SURVEY_SETTING, offset=OFFSET) and retry.reached():
                    self.device.click(btn)
                    retry.reset()
        raise GameStuckError(f'Resonance survey target {name} did not reach state {want_on}')

    def _stop_auto_crusade(self):
        """Click 关闭自动讨伐 until 开启自动讨伐 is restored."""
        self.interval_clear(assets.SURVEY_AUTO_STOP)
        for _ in self.loop(timeout=10):
            if self.appear(assets.SURVEY_AUTO_START, offset=OFFSET):
                return
            if self.appear(assets.SURVEY_AUTO_STOP, offset=OFFSET):
                self.appear_then_click(assets.SURVEY_AUTO_STOP, offset=OFFSET, interval=2)

    def configure_targets(self, desired):
        """Stop active auto-crusade if running, open 设置, match 4 tree toggles, then close 设置."""
        if self.appear(assets.SURVEY_AUTO_STOP, offset=OFFSET):
            self._stop_auto_crusade()
        self._set_setting_panel(True)
        for key, box in TREE_ROWS:
            self._set_single_tree(key, box, bool(desired[key]))
        self._set_setting_panel(False)

    def _handle_auto_combat_toggle(self, auto_off_timer, auto_retry_timer):
        """Enable auto combat inside battle if OP_AUTO_OFF is active."""
        if (self.appear(assets.OP_AUTO_OFF, offset=OFFSET, similarity=0.74)
                and self.image_color_count(assets.OP_AUTO_OFF, (130, 130, 130), threshold=18, count=250)):
            if auto_off_timer.reached() and auto_retry_timer.reached():
                self.device.click(assets.OP_AUTO_OFF)
                auto_off_timer.reset()
                auto_retry_timer.reset()

    def _handle_refill_modal(self):
        """Handle stamina/clarity refill dialogs according to `UseClarityItem`."""
        if self.appear(assets.CLARITY_PROMPT, offset=OFFSET) or self.appear(assets.CLARITY_RECOVERY_CHECK, offset=OFFSET):
            mode = getattr(self.config, 'ResonancePreparation_UseClarityItem', 'none')
            return 'recovered' if handle_clarity_recovery(self, mode) else 'cancelled'
        if self.appear(assets.FATIGUE_CONFIRM_MODAL, offset=OFFSET) and self.appear(assets.FATIGUE_CONFIRM_CANCEL, offset=OFFSET):
            if self.appear_then_click(assets.FATIGUE_CONFIRM_CANCEL, offset=OFFSET, interval=2):
                return 'cancelled'
        if self.appear_then_click(assets.SHOP_CANCEL, offset=OFFSET, interval=2):
            return 'cancelled'
        return None

    def _try_survey_clarity_refill(self):
        """Open clarity recovery via top-right `+` on survey page and use configured item."""
        mode = normalize_clarity_item_mode(getattr(self.config, 'ResonancePreparation_UseClarityItem', 'none'))
        if mode == 'none':
            return False
        retry = Timer(1.5)
        for _ in self.loop(timeout=8):
            if self.appear(assets.CLARITY_RECOVERY_CHECK, offset=OFFSET) or self.appear(assets.CLARITY_PROMPT, offset=OFFSET):
                return handle_clarity_recovery(self, mode)
            if (self.appear(assets.SURVEY_AUTO_STOP, offset=OFFSET) or self.ui_page_appear(page_resonance_survey, offset=OFFSET)) and retry.reached():
                self.device.click(_box_button(SURVEY_CLARITY_PLUS_BOX, 'SURVEY_CLARITY_PLUS'))
                retry.reset()
        return False

    def _handle_stop_panel_clarity(self, refills, battle_panel_idle):
        """Return 'refilled', 'stop', or None on the active auto-crusade detail panel."""
        if self.appear(assets.SURVEY_BATTLE_START, offset=OFFSET):
            if not (read_clarity_insufficient(self.device.image) or battle_panel_idle.reached()):
                return None
            if refills < 6 and self._try_survey_clarity_refill():
                return 'refilled'
            logger.info('琐呐全域整备澄明度不足，停止自动讨伐')
            self._stop_auto_crusade()
            return 'stop'
        battle_panel_idle.reset()
        return None

    def run_auto_crusade(self):
        """Start 开启自动讨伐 and return 'done', 'no_clarity', or 'no_target'."""
        self.interval_clear((assets.SURVEY_AUTO_START, assets.LOGIN_REWARD, assets.OP_NEXT))
        started, cancelled, clicks, refills = False, False, 0, 0
        no_start, finish_settle = Timer(6, count=3), Timer(6, count=3)
        cancel_settle, battle_panel_idle = Timer(2, count=2), Timer(6, count=3)
        auto_off, auto_retry = Timer(0.5, count=2).start(), Timer(4)

        def mark_active():
            finish_settle.reset()
            battle_panel_idle.reset()
            self.device.stuck_record_clear()
            return True

        for _ in self.loop(timeout=1200):
            if self.handle_reward_popup() or self.handle_operation_victory():
                started = mark_active()
                continue
            refill = self._handle_refill_modal()
            if refill == 'recovered':
                mark_active()
                started, clicks = False, 0
                continue
            if refill == 'cancelled':
                cancelled = mark_active()
                started = True
                cancel_settle.reset()
                continue
            if self.appear(assets.OP_PAUSE, offset=OFFSET):
                started = mark_active()
                self._handle_auto_combat_toggle(auto_off, auto_retry)
                continue
            auto_off.reset()

            if self.ui_page_appear(page_resonance_survey, offset=OFFSET):
                if self.appear(assets.SURVEY_AUTO_STOP, offset=OFFSET):
                    started = True
                    finish_settle.reset()
                    self.device.stuck_record_clear()
                    act = self._handle_stop_panel_clarity(refills, battle_panel_idle)
                    if act == 'refilled':
                        refills += 1
                        started, clicks = False, 0
                        mark_active()
                    elif act == 'stop':
                        return 'no_clarity'
                elif self.appear(assets.SURVEY_AUTO_START, offset=OFFSET):
                    battle_panel_idle.reset()
                    if cancelled and cancel_settle.reached():
                        logger.info('琐呐全域整备体力不足，已取消补充并结束讨伐')
                        return 'no_clarity'
                    if started:
                        if finish_settle.reached():
                            logger.info('琐呐全域整备自动讨伐完成')
                            return 'done'
                    elif clicks == 0 and self.appear_then_click(assets.SURVEY_AUTO_START, offset=OFFSET, interval=2):
                        clicks += 1
                        no_start.reset()
                        finish_settle.reset()
                    elif clicks > 0 and no_start.reached():
                        logger.info('琐呐全域整备无可讨伐目标或体力不足，结束讨伐')
                        return 'no_target'
                else:
                    started = mark_active()
            elif clicks > 0:
                started = mark_active()
        raise GameStuckError('Resonance preparation auto crusade timed out')

    def _open_weekly_reward_modal(self):
        """Open 凭证置换 modal when 查看本周奖励 shows a claimable red badge."""
        if not has_weekly_reward_badge(self.device.image):
            logger.info('琐呐全域整备本周奖励无红点，跳过领取')
            return False
        self.interval_clear(assets.PREP_WEEKLY_REWARD)
        for _ in self.loop(timeout=12):
            if self.appear(assets.PREP_REWARD_MODAL, offset=OFFSET):
                return True
            if self.ui_page_appear(page_resonance_prep, offset=OFFSET):
                self.appear_then_click(assets.PREP_WEEKLY_REWARD, offset=OFFSET, interval=2)
        raise GameStuckError('Resonance weekly reward modal did not open')

    def _click_milestone_and_wait(self, btn):
        """Click one milestone node on 凭证置换 and return True if LOGIN_REWARD pops up."""
        clicked = False
        got_reward = False
        wait = Timer(1.8)
        settle = Timer(1.5)
        for _ in self.loop(timeout=8):
            if self.handle_reward_popup():
                got_reward = True
                settle.reset()
                continue
            if got_reward:
                if settle.reached():
                    return True
                continue
            if self.appear(assets.PREP_REWARD_MODAL, offset=OFFSET):
                if not clicked:
                    self.device.click(btn)
                    clicked = True
                    wait.reset()
                elif wait.reached():
                    return False
        return got_reward

    def _close_weekly_reward_modal(self):
        """Dismiss 凭证置换 modal back to 全域整备."""
        self.interval_clear(assets.PREP_REWARD_MODAL)
        for _ in self.loop(timeout=12):
            if self.handle_reward_popup():
                continue
            if self.ui_page_appear(page_resonance_prep, offset=OFFSET):
                return
            self.appear_then_click(assets.PREP_REWARD_MODAL, offset=OFFSET, interval=2)
        raise GameStuckError('Resonance weekly reward modal did not close')

    def _scan_visible_milestones(self):
        """Try visible milestone nodes on the current 凭证置换 view; return True if rewards claimed."""
        for btn in find_weekly_milestone_buttons(self.device.image):
            if self._click_milestone_and_wait(btn):
                return True
        return False

    def claim_weekly_rewards(self):
        """Open 查看本周奖励, tap one unclaimed node to claim all rewards, then close modal."""
        if not self._open_weekly_reward_modal():
            return False
        claimed = False
        previous = None
        for _ in range(6):
            if self._scan_visible_milestones():
                claimed = True
                break
            track = self.image_crop(MILESTONE_TRACK_ROI)
            if previous is not None and cv2.absdiff(previous, track).mean() < 1:
                break
            previous = track
            if self.appear(assets.PREP_REWARD_MODAL, offset=OFFSET):
                self.device.swipe((1150, 360), (480, 360), duration=0.55, name='PREP_REWARD_SWIPE')
                self.wait_until_still(MILESTONE_TRACK_ROI, timeout=6, skip_first_screenshot=False)
        self._close_weekly_reward_modal()
        return claimed

    def run(self):
        """Execute 全域整备 -> 构析勘探 auto-crusade, claim weekly rewards, return to main, and delay."""
        desired = self.desired_targets()
        if any(desired.values()):
            self.ui_ensure(page_resonance_survey, skip_first_screenshot=False)
            self.configure_targets(desired)
            status = self.run_auto_crusade()
            if (status == 'no_clarity' and desired['white']
                    and any(desired[k] for k in ('red', 'rainbow', 'purple'))):
                logger.info('澄明度不足，切换为仅打白树（异构厄枝，不消耗体力）继续讨伐')
                self.configure_targets({'red': False, 'white': True, 'rainbow': False, 'purple': False})
                self.run_auto_crusade()
                self.configure_targets(desired)
            self.ui_ensure(page_resonance_prep, skip_first_screenshot=False)
        else:
            logger.info('琐呐全域整备未勾选任何讨伐目标，跳过自动讨伐并检查本周奖励')
            self.ui_ensure(page_resonance_prep, skip_first_screenshot=False)

        claimed = self.claim_weekly_rewards()
        logger.info('琐呐全域整备完成 (weekly_claimed=%s)', claimed)
        self.ui_goto_main()
        self.config.task_delay(server_update=True)
