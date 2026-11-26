"""Beach volleyball minigame helper for 雷索纳斯 海岛物语."""

import re
import time

import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.ocr.ocr import Ocr
from module.resonance import assets


OFFSET = (5, 5)
VB_ATTEMPTS_OCR = Ocr(
    (1005, 580, 1068, 608),
    threshold=160,
    alphabet='0123456789/',
    name='Volleyball attempts',
)
CHAR_CARDS = ((40, 540, 136, 630), (178, 540, 274, 630))
CHAR_CARD_RECTS = ((26, 530, 150, 625), (164, 530, 288, 625))
CHAR_LOCK_SEARCH_ROI = (15, 620, 450, 685)
TIMING_HIT_BOX = (155, 515, 255, 605)
GRID_COURT_ROI = (0, 220, 1280, 710)


def _box_button(box, name):
    return Button(area=box, color=(), button=box, name=name)


def read_volleyball_attempts(image):
    """Return `(remaining, total)` attempts from match mode card, or None if unreadable."""
    text = VB_ATTEMPTS_OCR.ocr(image)
    match = re.search(r'(\d+)\s*/\s*(\d+)', str(text))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def is_char_card_locked(image, idx):
    """Return True when volleyball character card `idx` already has LOCK overlay."""
    x1, y1, x2, y2 = CHAR_CARD_RECTS[idx]
    patch = image[y1:y2, x1:x2]
    r_mean = float(patch[:, :, 0].mean())
    b_mean = float(patch[:, :, 2].mean())
    return (b_mean - r_mean) > 68.0 and float(patch.std()) < 48.0


def find_char_lock_button(image):
    """Find the active 点击锁定 button under character cards; return (Button, cx) or (None, None)."""
    rx1, ry1, rx2, ry2 = CHAR_LOCK_SEARCH_ROI
    score, button = assets.TEMPLATE_VB_LOCK_CLICK.match_result(image[ry1:ry2, rx1:rx2])
    if score <= 0.85:
        return None, None
    btn = button.move((rx1, ry1))
    cx = (btn.area[0] + btn.area[2]) // 2
    return btn, cx


def detect_grid_blue_marker(image):
    """Return `(cx, cy)` center of the glowing blue target tile anywhere on court, or None."""
    rx1, ry1, rx2, ry2 = GRID_COURT_ROI
    roi = image[ry1:ry2, rx1:rx2]
    r = roi[:, :, 0].astype(np.int16)
    g = roi[:, :, 1].astype(np.int16)
    b = roi[:, :, 2].astype(np.int16)
    mask = ((b > 185) & (g > 155) & ((b - r) > 70)).astype(np.uint8)
    mask[640 - ry1:, 880:] = 0
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(closed)
    best = None
    best_px = 0
    for idx in range(1, count):
        x, y, w, h, area = stats[idx]
        if w < 85 or h < 42 or area < 1800 or not (0.85 <= (w / float(h)) <= 3.8):
            continue
        cx, cy = rx1 + x + w // 2, ry1 + y + h // 2
        if cy < 280 and cx > 850:
            continue
        raw_px = int(mask[y:y + h, x:x + w].sum())
        if raw_px >= 900 and raw_px > best_px:
            best_px = raw_px
            best = (cx, cy)
    return best


def detect_timing_bar_x(image):
    """Return current right edge x of cyan timing bar in `[280, 603]`, or None."""
    strip = image[553:568, 280:604]
    r_mean = strip[:, :, 0].mean(axis=0)
    g_mean = strip[:, :, 1].mean(axis=0)
    b_mean = strip[:, :, 2].mean(axis=0)
    filled = (g_mean > 180) & (b_mean > 215) & ((b_mean - r_mean) > 60)
    xs = np.where(filled)[0]
    if not len(xs):
        return None
    return 280 + int(xs[-1])


def is_timing_bar_resolved(image):
    """Return True when center GOOD/PERFECT banner is visible over the timing bar."""
    roi = image[230:490, 520:760]
    mask = (roi[:, :, 0] > 220) & (roi[:, :, 1] > 170) & (roi[:, :, 2] < 120)
    return int(mask.sum()) >= 1500


def should_trigger_timing_hit(cur_x, prev_x, dt, target_x=545, lead_sec=0.14, hard_x=505, miss_x=595):
    """Decide whether to click volleyball QTE hit right before pointer reaches MISS."""
    if cur_x is None or cur_x < 330 or cur_x >= miss_x:
        return False
    if cur_x >= hard_x:
        return True
    if prev_x is not None and dt > 0.005 and cur_x > prev_x:
        speed = min(max((cur_x - prev_x) / dt, 150.0), 450.0)
        return (cur_x + speed * lead_sec) >= target_x
    return False


def _click_char_select(ui, select_timer):
    """Pick first 2 unlocked characters and click 锁定. Pages: char_select -> char_select."""
    if ui.appear(assets.VB_CHAR_SELECT, offset=OFFSET) and select_timer.reached():
        lock_btn, _ = find_char_lock_button(ui.device.image)
        if lock_btn is not None:
            ui.device.click(lock_btn)
        elif not is_char_card_locked(ui.device.image, 0):
            ui.device.click(_box_button(CHAR_CARDS[0], 'VB_CHAR_CARD_0'))
        elif not is_char_card_locked(ui.device.image, 1):
            ui.device.click(_box_button(CHAR_CARDS[1], 'VB_CHAR_CARD_1'))
        else:
            return
        ui.device.click_record_clear()
        select_timer.reset()


def _handle_volleyball_end(ui):
    """Dismiss end-of-match or training defeat/victory overlays after entering a match."""
    return (
        ui.appear_then_click(assets.VB_TRAINING_END, offset=OFFSET, interval=2)
        or ui.appear_then_click(assets.TAP_BLANK_EXIT, offset=(40, 100), similarity=0.80, interval=2)
        or ui.handle_operation_victory()
        or ui.appear_then_click(assets.OP_BACK, offset=OFFSET, interval=2)
    )


def play_single_volleyball_match(ui):
    """Play one complete beach volleyball match.

    Pages:
        in: volleyball mode select / char select
        out: volleyball mode select or island hub
    """
    match_entered = False
    qte_fired = False
    prev_x = None
    prev_t = None
    last_grid = None
    grid_timer = Timer(0.6).start()
    select_timer = Timer(0.5).start()

    ui.device.screenshot_interval_set(0.03)
    try:
        for _ in ui.loop(timeout=240):
            if ui.handle_reward_popup():
                continue
            if match_entered and (
                ui.appear(assets.VB_MODE_MATCH, offset=OFFSET)
                or ui.appear(assets.ISLAND_HUB_CHECK, offset=OFFSET)
            ):
                return True
            if ui.appear(assets.VB_CHAR_SELECT, offset=OFFSET):
                match_entered = True
                qte_fired = False
                prev_x = None
                prev_t = None
                ui.device.stuck_record_clear()
                _click_char_select(ui, select_timer)
                continue
            if ui.appear(assets.VB_TIMING_MISS, offset=OFFSET):
                match_entered = True
                ui.device.stuck_record_clear()
                now = time.monotonic()
                cur_x = detect_timing_bar_x(ui.device.image)
                if cur_x is not None and cur_x < 380:
                    qte_fired = False
                dt = (now - prev_t) if prev_t is not None else 0.0
                if (
                    not qte_fired
                    and not is_timing_bar_resolved(ui.device.image)
                    and should_trigger_timing_hit(cur_x, prev_x, dt)
                ):
                    ui.device.click(_box_button(TIMING_HIT_BOX, 'VB_TIMING_HIT'))
                    qte_fired = True
                    ui.device.click_record_clear()
                prev_x = cur_x
                prev_t = now
                continue
            qte_fired = False
            prev_x = None
            prev_t = None
            if ui.appear(assets.VB_COURT_EXIT, offset=OFFSET):
                match_entered = True
                ui.device.stuck_record_clear()
                pos = detect_grid_blue_marker(ui.device.image)
                if pos is not None and (
                    last_grid is None
                    or abs(pos[0] - last_grid[0]) + abs(pos[1] - last_grid[1]) > 45
                    or grid_timer.reached()
                ):
                    ui.device.click(_box_button((pos[0] - 18, pos[1] - 18, pos[0] + 18, pos[1] + 18), 'VB_GRID_TILE'))
                    last_grid = pos
                    grid_timer.reset()
                    ui.device.click_record_clear()
                continue
            if match_entered and _handle_volleyball_end(ui):
                continue
    finally:
        ui.device.screenshot_interval_set()
    raise GameStuckError('Volleyball match timed out')


def _open_and_check_volleyball(ui):
    """Open volleyball mode overlay from hub and read remaining reward attempts.

    Pages:
        in: page_resonance_island_hub (or already VB_MODE_MATCH)
        out: VB_MODE_MATCH overlay
    """
    for _ in ui.loop(skip_first=False, timeout=15):
        if ui.appear(assets.VB_MODE_MATCH, offset=OFFSET):
            return read_volleyball_attempts(ui.device.image)
        if ui.appear_then_click(assets.ISLAND_HUB_VOLLEYBALL, offset=OFFSET, interval=2):
            continue
    raise GameStuckError('Volleyball mode select did not open')


def _enter_volleyball_match(ui):
    """Click 比赛模式 until char select or court screen opens.

    Pages:
        in: VB_MODE_MATCH overlay
        out: VB_CHAR_SELECT or VB_COURT_EXIT
    """
    for _ in ui.loop(timeout=15):
        if ui.appear(assets.VB_CHAR_SELECT, offset=OFFSET) or ui.appear(assets.VB_COURT_EXIT, offset=OFFSET):
            return
        if ui.appear_then_click(assets.VB_MODE_MATCH, offset=OFFSET, interval=2):
            continue
    raise GameStuckError('Volleyball match did not enter character selection')


def _close_volleyball_mode_select(ui):
    """Dismiss volleyball mode overlay back to island hub.

    Pages:
        in: VB_MODE_MATCH overlay or page_resonance_island_hub
        out: page_resonance_island_hub
    """
    for _ in ui.loop(skip_first=False, timeout=15):
        if ui.appear(assets.ISLAND_HUB_CHECK, offset=OFFSET):
            return
        if ui.appear(assets.VB_MODE_MATCH, offset=OFFSET):
            if ui.appear_then_click(assets.TAP_BLANK_EXIT, offset=(40, 100), similarity=0.80, interval=2):
                continue
        if ui.handle_reward_popup():
            continue
    raise GameStuckError('Volleyball mode select did not close back to island hub')


def run_beach_volleyball(ui):
    """Play all remaining daily reward matches of Beach Volleyball.

    Pages:
        in: page_resonance_island_hub
        out: page_resonance_island_hub
    """
    try:
        for round_idx in range(3):
            attempts = _open_and_check_volleyball(ui)
            if attempts is not None:
                remaining, total = attempts
                logger.info(f'Beach volleyball reward attempts: {remaining}/{total}')
                if remaining <= 0:
                    break
            elif round_idx > 0:
                logger.warning('Beach volleyball attempts unreadable after match, stopping')
                break
            _enter_volleyball_match(ui)
            play_single_volleyball_match(ui)
    finally:
        _close_volleyball_mode_select(ui)
