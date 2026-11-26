"""Friend island monster combat and garbage cleaning for 雷索纳斯 海岛物语."""

import re

import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.ocr.ocr import Ocr
from module.resonance import assets


OFFSET = (5, 5)
FRIEND_ASSIST_OCR = Ocr((815, 88, 940, 134), threshold=128, alphabet='0123456789/', name='Friend assists')
FRIEND_CLEAN_OCR = Ocr((955, 88, 1070, 134), threshold=128, alphabet='0123456789/', name='Friend clean')
FRIEND_MONSTER_OCR = Ocr(
    (325, 650, 385, 678), letter=(30, 30, 50), threshold=128, alphabet='0123456789', name='Friend monsters',
)
TOAST_OCR = Ocr((420, 336, 860, 384), lang='cnocr', threshold=140, name='Island toast')


def _box_button(box, name):
    return Button(area=box, color=(), button=box, name=name)


def read_fraction_first(ocr_obj, image):
    """Parse leading integer from `a/b` OCR output, or return None."""
    text = ocr_obj.ocr(image)
    match = re.search(r'(\d+)\s*/\s*\d+', str(text))
    return int(match.group(1)) if match else None


def read_friend_assist_remaining(image):
    """Return remaining friend monster assist count (`帮助次数`), or None."""
    return read_fraction_first(FRIEND_ASSIST_OCR, image)


def read_friend_clean_remaining(image):
    """Return remaining cleanable count (`可被清理`) on visited friend island, or None."""
    return read_fraction_first(FRIEND_CLEAN_OCR, image)


def read_friend_monster_count(image):
    """Return remaining monster count next to raccoon icon on friend island, or None."""
    text = str(FRIEND_MONSTER_OCR.ocr(image)).strip()
    digits = re.findall(r'\d+', text)
    return int(digits[0]) if digits else None


def detect_friend_monsters(image):
    """Detect `!!` red speech bubbles on a friend's beach and return `(tap_x, tap_y)` targets."""
    roi = image[140:590, :]
    r = roi[:, :, 0].astype(np.int16)
    g = roi[:, :, 1].astype(np.int16)
    b = roi[:, :, 2].astype(np.int16)
    red = ((r > 215) & (g < 140) & (b < 140) & ((r - g) > 90)).astype(np.uint8)
    count, _, stats, centroids = cv2.connectedComponentsWithStats(red)
    candidates = []
    for idx in range(1, count):
        x, y, w, h, area = stats[idx]
        if not (25 <= w <= 75 and 30 <= h <= 80 and 650 <= area <= 3500):
            continue
        if not (0.68 <= (w / float(h)) <= 1.05):
            continue
        y_abs = y + 140
        patch = image[y_abs:y_abs + h, x:x + w]
        white = (patch[:, :, 0] > 215) & (patch[:, :, 1] > 215) & (patch[:, :, 2] > 215)
        w_ratio = float(white.mean())
        if not (0.05 <= w_ratio <= 0.45):
            continue
        cx = int(centroids[idx][0])
        tap_x = max(75, min(cx, 1205))
        tap_y = min(y_abs + h + int(h * 0.55), 570)
        candidates.append((abs(cx - 640), tap_x, tap_y))
    candidates.sort(key=lambda item: item[0])
    return [(tx, ty) for _, tx, ty in candidates]


def has_friend_clean_coin(image):
    """Return True when the gold coin bubble sits above the friend 清扫 button."""
    roi = image[470:560, 705:780]
    r = roi[:, :, 0].astype(np.int16)
    g = roi[:, :, 1].astype(np.int16)
    b = roi[:, :, 2].astype(np.int16)
    gold = (r > 130) & (g > 100) & (b < 60) & ((r - b) > 90)
    return int(gold.sum()) >= 120


def is_friend_next_enabled(image):
    """Return True when bottom-right 下一位 button is pink (active) rather than gray."""
    patch = image[648:674, 1110:1215]
    return float(patch[:, :, 0].mean() - patch[:, :, 1].mean()) > 20.0


def is_garbage_full_toast(image):
    """Return True when train garbage storage full toast banner is visible."""
    band = image[336:384, 400:880]
    if float(band.mean()) >= 90.0:
        return False
    text = str(TOAST_OCR.ocr(image))
    return any(keyword in text for keyword in ('暂存区', '没有空间', '垃圾箱'))


def _open_friend_and_visit_first(ui, sort_tab):
    """Open friend drawer, sort by `sort_tab`, and enter the top friend's island.

    Pages:
        in: own beach or friend island
        out: friend island (`ISLAND_FRIEND_CHECK`) or back if empty
    """
    sorted_done = False
    sort_settle = Timer(0.6)
    empty_timer = Timer(3.0).start()
    for _ in ui.loop(skip_first=False, timeout=25):
        if ui.appear(assets.ISLAND_FRIEND_LIST, offset=OFFSET):
            if not sorted_done:
                if ui.appear_then_click(sort_tab, offset=OFFSET, interval=1):
                    sorted_done = True
                    sort_settle.reset()
                    empty_timer.reset()
                continue
            if not sort_settle.reached():
                continue
            if ui.appear_then_click(assets.ISLAND_FRIEND_VISIT_0, offset=OFFSET, interval=2):
                empty_timer.reset()
                continue
            if empty_timer.reached():
                ui.device.click(_box_button((860, 360, 940, 420), 'FRIEND_DRAWER_CLOSE'))
                return False
            continue
        if sorted_done and ui.appear(assets.ISLAND_FRIEND_CHECK, offset=OFFSET):
            return True
        if ui.appear_then_click(assets.ISLAND_FRIEND_TAB, offset=OFFSET, interval=2):
            continue
        if ui.appear_then_click(assets.ISLAND_FRIEND_TAB_VISIT, offset=OFFSET, interval=2):
            continue
    return False


def _wait_friend_battle(ui):
    """Click START BATTLE on team panel and wait until back on friend's island.

    Pages:
        in: OP_TEAM (friend monster combat)
        out: ISLAND_FRIEND_CHECK
    """
    started = False
    auto_off = Timer(0.5, count=2).start()
    auto_retry = Timer(4)
    for _ in ui.loop(timeout=240):
        if ui.handle_reward_popup():
            continue
        if ui.handle_operation_victory():
            continue
        if started and ui.appear(assets.ISLAND_FRIEND_CHECK, offset=OFFSET):
            return
        if ui.appear(assets.OP_TEAM, offset=OFFSET):
            if ui.appear_then_click(assets.OP_TEAM_START, offset=OFFSET, interval=2):
                started = True
            continue
        if ui.appear(assets.OP_PAUSE, offset=OFFSET):
            started = True
            ui.device.stuck_record_clear()
            if ui.image_color_count(assets.OP_PAUSE, (255, 255, 255), threshold=50, count=250):
                if (
                    ui.appear(assets.OP_AUTO_OFF, offset=OFFSET, similarity=0.74)
                    and ui.image_color_count(assets.OP_AUTO_OFF, (130, 130, 130), threshold=18, count=250)
                ):
                    if auto_off.reached() and auto_retry.reached():
                        ui.device.click(assets.OP_AUTO_OFF)
                        auto_off.reset()
                        auto_retry.reset()
                    continue
        auto_off.reset()
    raise GameStuckError('Friend island monster battle timed out')


def _click_and_fight_monster(ui, target):
    """Tap a friend monster `(x, y)` and complete combat if `OP_TEAM` opens.

    Pages:
        in: ISLAND_FRIEND_CHECK
        out: ISLAND_FRIEND_CHECK
    """
    tx, ty = target
    clicked = False
    wait_team = Timer(2.5).start()
    for _ in ui.loop(timeout=10):
        if ui.appear(assets.OP_TEAM, offset=OFFSET):
            _wait_friend_battle(ui)
            return True
        if ui.appear(assets.ISLAND_FRIEND_CHECK, offset=OFFSET):
            if not clicked:
                ui.device.click(_box_button((tx - 18, ty - 18, tx + 18, ty + 18), 'FRIEND_MONSTER'))
                ui.device.click_record_clear()
                clicked = True
                wait_team.reset()
                continue
            if wait_team.reached():
                return False
    return False


def _clean_current_friend(ui):
    """Click 清扫 on current friend while gold coin pin is visible.

    Pages:
        in: ISLAND_FRIEND_CHECK
        out: ISLAND_FRIEND_CHECK
    """
    cleaned_any = False
    for _ in range(3):
        if not has_friend_clean_coin(ui.device.image):
            return 'cleaned' if cleaned_any else 'none'
        before = read_friend_clean_remaining(ui.device.image)
        reward_seen = False
        settle = Timer(0.8).start()
        for _ in ui.loop(timeout=8):
            if is_garbage_full_toast(ui.device.image):
                logger.warning('火车垃圾箱暂存区已满，停止好友清扫')
                return 'garbage_full'
            if ui.handle_reward_popup():
                reward_seen = True
                cleaned_any = True
                settle.reset()
                continue
            if ui.appear_then_click(assets.ISLAND_FRIEND_CLEAN, offset=OFFSET, interval=2):
                settle.reset()
                continue
            if ui.appear(assets.ISLAND_FRIEND_CHECK, offset=OFFSET) and settle.reached():
                break
        if reward_seen:
            cleaned_any = True
            if not has_friend_clean_coin(ui.device.image):
                return 'cleaned'
            continue
        after = read_friend_clean_remaining(ui.device.image)
        if not has_friend_clean_coin(ui.device.image) or (before is not None and after is not None and after < before):
            cleaned_any = True
        else:
            break
    return 'cleaned' if cleaned_any else 'none'


def _advance_next_friend(ui):
    """Click 下一位 if enabled and wait briefly for friend swap.

    Pages:
        in: ISLAND_FRIEND_CHECK
        out: ISLAND_FRIEND_CHECK
    """
    clicked = False
    wait_next = Timer(1.2)
    for _ in ui.loop(timeout=12):
        if ui.appear(assets.ISLAND_FRIEND_CHECK, offset=OFFSET):
            if not clicked:
                if not is_friend_next_enabled(ui.device.image):
                    return False
                ui.device.click(assets.ISLAND_FRIEND_NEXT)
                ui.device.click_record_clear()
                clicked = True
                wait_next.reset()
                continue
            if wait_next.reached():
                return True
    return False


def _clear_monsters_on_friend(ui, assists):
    """Fight up to `assists` visible monsters on the current friend's island."""
    panned = False
    for _ in range(6):
        if assists <= 0:
            break
        targets = detect_friend_monsters(ui.device.image)
        if targets:
            for target in targets:
                if _click_and_fight_monster(ui, target):
                    assists -= 1
                    break
            else:
                break
            updated = read_friend_assist_remaining(ui.device.image)
            if updated is not None:
                assists = updated
            continue
        mon_cnt = read_friend_monster_count(ui.device.image)
        if not panned and (mon_cnt is None or mon_cnt > 0):
            if ui.appear(assets.ISLAND_FRIEND_CHECK, offset=OFFSET):
                ui.device.swipe((900, 420), (380, 420), duration=0.4, name='FRIEND_PAN')
                panned = True
                ui.device.screenshot()
                continue
        break
    return assists


def _run_friend_fight_phase(ui, allow_clean):
    """Visit friends sorted by 治安 and fight daily monster assists (up to 5).

    Pages:
        in: own beach
        out: friend island or own beach
    """
    if not _open_friend_and_visit_first(ui, assets.ISLAND_FRIEND_SORT_SEC):
        return False
    garbage_full = False
    no_monster_streak = 0
    for _ in range(25):
        assists = read_friend_assist_remaining(ui.device.image)
        if assists is not None and assists <= 0:
            logger.info('好友助力次数已用完 (0/5)')
            break
        if allow_clean and not garbage_full and has_friend_clean_coin(ui.device.image):
            if _clean_current_friend(ui) == 'garbage_full':
                garbage_full = True
        before_assists = assists if assists is not None else 5
        after_assists = _clear_monsters_on_friend(ui, before_assists)
        if after_assists <= 0:
            logger.info('好友助力次数已用完 (0/5)')
            break
        if after_assists < before_assists:
            no_monster_streak = 0
        else:
            no_monster_streak += 1
        if no_monster_streak >= 3:
            logger.info('连续多名好友无怪，结束好友打怪')
            break
        if not _advance_next_friend(ui):
            break
    return garbage_full


def _run_friend_clean_phase(ui):
    """Visit friends sorted by 清扫 and clean garbage where coin icon appears.

    Pages:
        in: own beach or friend island
        out: friend island or own beach
    """
    if not _open_friend_and_visit_first(ui, assets.ISLAND_FRIEND_SORT_CLEAN):
        return
    no_coin_streak = 0
    for _ in range(30):
        if has_friend_clean_coin(ui.device.image):
            result = _clean_current_friend(ui)
            if result == 'garbage_full':
                break
            no_coin_streak = 0
        else:
            no_coin_streak += 1
        if no_coin_streak >= 3:
            logger.info('连续多名好友无可清扫垃圾，结束好友清扫')
            break
        if not _advance_next_friend(ui):
            break


def _exit_friend_island(ui):
    """Return from friend island back to own beach (`ISLAND_BEACH_CHECK`).

    Pages:
        in: friend island or friend list drawer
        out: page_resonance_island_beach
    """
    for _ in ui.loop(timeout=20):
        if ui.handle_reward_popup():
            continue
        if ui.appear(assets.ISLAND_FRIEND_LIST, offset=OFFSET):
            ui.device.click(_box_button((860, 360, 940, 420), 'FRIEND_DRAWER_CLOSE'))
            continue
        if ui.appear(assets.ISLAND_BEACH_CHECK, offset=OFFSET):
            return
        if ui.appear_then_click(assets.OP_BACK, offset=OFFSET, interval=2):
            continue
    raise GameStuckError('Did not return from friend island to own beach')


def run_island_friends(ui, fight=True, clean=True):
    """Perform friend island monster combat and garbage cleaning.

    Pages:
        in: page_resonance_island_beach
        out: page_resonance_island_beach
    """
    garbage_full = False
    if fight:
        garbage_full = _run_friend_fight_phase(ui, allow_clean=clean)
    if clean and not garbage_full:
        _run_friend_clean_phase(ui)
    _exit_friend_island(ui)
