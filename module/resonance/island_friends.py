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
FRIEND_MONSTER_OCR = Ocr((325, 650, 385, 678), letter=(30, 30, 50), threshold=128, alphabet='0123456789', name='Friend monsters')
TOAST_OCR = Ocr((420, 336, 860, 384), lang='cnocr', threshold=140, name='Island toast')
FRIEND_ROW_Y0 = 207
FRIEND_ROW_PITCH = 124
FRIEND_VISIBLE_ROWS = 4
FRIEND_SORT_CHEVRON_BOXES = {'ISLAND_FRIEND_SORT_CLEAN': (298, 154, 328, 169), 'ISLAND_FRIEND_SORT_SEC': (388, 154, 418, 169)}


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
    r, g, b = roi[:, :, 0].astype(np.int16), roi[:, :, 1].astype(np.int16), roi[:, :, 2].astype(np.int16)
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
    r, g, b = roi[:, :, 0].astype(np.int16), roi[:, :, 1].astype(np.int16), roi[:, :, 2].astype(np.int16)
    return int(((r > 130) & (g > 100) & (b < 60) & ((r - b) > 90)).sum()) >= 120


def has_friend_clean_cooldown(image):
    """Return True when the pink clean-cooldown badge sits next to 可被清理."""
    p = image[65:88, 1030:1085]
    r, g, b = p[:, :, 0], p[:, :, 1].astype(np.int16), p[:, :, 2].astype(np.int16)
    return int(((r > 200) & (r.astype(np.int16) - g > 40) & (r.astype(np.int16) - b > 15)).sum()) >= 150


def _dismiss_clean_popup(ui):
    return (ui.handle_reward_popup() or ui.appear_then_click(assets.ISLAND_FRIEND_CLEAN_RESULT, offset=OFFSET, interval=1.5)
            or ui.appear_then_click(assets.TAP_BLANK_EXIT, offset=(40, 100), similarity=0.80, interval=1.5))


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


def friend_row_visit_box(row):
    """Return clickable triangle box `(x1, y1, x2, y2)` for visible friend `row` (`0..3`)."""
    dy = row * FRIEND_ROW_PITCH
    return (476, 216 + dy, 544, 272 + dy)

def has_friend_list_row(image, row):
    """Return True when friend list `row` shows a pink 访问 triangle."""
    dy = row * FRIEND_ROW_PITCH
    patch = image[210 + dy:276 + dy, 470:548]
    return int(((patch[:, :, 0] > 200) & (patch[:, :, 0].astype(np.int16) - patch[:, :, 1].astype(np.int16) > 30)).sum()) >= 1200

def has_friend_list_clean_icon(image, row):
    """Return True when friend list `row` displays the white broom+trashcan clean icon."""
    y1 = FRIEND_ROW_Y0 + row * FRIEND_ROW_PITCH
    p = image[y1:y1 + 30, 428:462]
    return int(((p[:, :, 0] > 225) & (p[:, :, 1] > 225) & (p[:, :, 2] > 225)).sum()) >= 40

def is_friend_list_row_current(image, row):
    """Return True when friend list `row` header stripe is pink (currently visiting)."""
    y1 = FRIEND_ROW_Y0 + row * FRIEND_ROW_PITCH
    bar = image[y1:y1 + 30, 300:360]
    return float(bar[:, :, 0].mean() - bar[:, :, 2].mean()) > 10.0

def is_friend_sort_active(image, sort_tab):
    """Return True when `sort_tab` already has the pink active chevron `⌄` underneath."""
    box = FRIEND_SORT_CHEVRON_BOXES.get(getattr(sort_tab, 'name', ''))
    if not box:
        return False
    x1, y1, x2, y2 = box
    p = image[y1:y2, x1:x2]
    return int(((p[:, :, 0] > 160) & (p[:, :, 0].astype(np.int16) - p[:, :, 1].astype(np.int16) > 15)).sum()) >= 15


def find_friend_list_clean_row(image, skip_current=False, skip_rows=()):
    """Return first visible row (`0..3`) with both a friend card and broom icon, or None."""
    for row in range(FRIEND_VISIBLE_ROWS):
        if row in skip_rows or not has_friend_list_row(image, row):
            continue
        if skip_current and is_friend_list_row_current(image, row):
            continue
        if has_friend_list_clean_icon(image, row):
            return row
    return None


def _open_friend_and_visit_first(ui, sort_tab, require_clean=False, skip_current=False,
                                 skip_rows=(), return_row=False):
    """Open friend drawer, sort by `sort_tab`, and enter top matching friend island."""
    sorted_done = False
    sort_settled = False
    closing = False
    visited = False
    selected_row = None
    sort_settle = Timer(0.6)
    visit_timer = Timer(2.0)
    empty_timer = Timer(3.0).start()
    drawer_close = _box_button((860, 360, 940, 420), 'FRIEND_DRAWER_CLOSE')
    for _ in ui.loop(skip_first=False, timeout=25):
        if closing:
            if ui.appear(assets.ISLAND_BEACH_CHECK, offset=OFFSET) or ui.appear(assets.ISLAND_FRIEND_CHECK, offset=OFFSET):
                return False
            if ui.appear(assets.ISLAND_FRIEND_LIST, offset=OFFSET) and visit_timer.reached():
                ui.device.click(drawer_close)
                visit_timer.reset()
            continue
        if ui.appear(assets.ISLAND_FRIEND_LIST, offset=OFFSET):
            if not sorted_done:
                if is_friend_sort_active(ui.device.image, sort_tab):
                    sorted_done = sort_settled = True
                    empty_timer.reset()
                elif ui.appear_then_click(sort_tab, offset=OFFSET, interval=1):
                    sorted_done = True
                    sort_settle.reset()
                    empty_timer.reset()
                    continue
                else:
                    continue
            if not sort_settled:
                if not sort_settle.reached():
                    continue
                sort_settled = True
            if require_clean:
                row = find_friend_list_clean_row(
                    ui.device.image, skip_current=skip_current, skip_rows=skip_rows,
                )
                if row is None:
                    ui.device.click(drawer_close)
                    visit_timer.reset()
                    closing = True
                    continue
            elif has_friend_list_row(ui.device.image, 0) or ui.appear(assets.ISLAND_FRIEND_VISIT_0, offset=OFFSET):
                row = 0
            else:
                if empty_timer.reached():
                    ui.device.click(drawer_close)
                    visit_timer.reset()
                    closing = True
                continue
            selected_row = row
            if visit_timer.reached():
                box = friend_row_visit_box(row)
                target = drawer_close if is_friend_list_row_current(ui.device.image, row) else _box_button(box, f'ISLAND_FRIEND_VISIT_{row}')
                ui.device.click(target)
                visited = True
                visit_timer.reset()
                empty_timer.reset()
            continue
        if sorted_done and ui.appear(assets.ISLAND_FRIEND_CHECK, offset=OFFSET):
            return selected_row if return_row else True
        if not visited and ui.appear_then_click(assets.ISLAND_FRIEND_TAB, offset=OFFSET, interval=2):
            continue
        if not visited and ui.appear_then_click(assets.ISLAND_FRIEND_TAB_VISIT, offset=OFFSET, interval=2):
            continue
    return False


def _handle_arrest_screens(ui, state):
    """Handle arrest quantity modal, animation skip, and arrest result screens."""
    if ui.appear(assets.ARREST_MODAL, offset=OFFSET):
        state['attempted'] = True
        if state['aborted'] or (state['confirm_clicks'] >= 2 and state['confirm_timer'].reached()):
            if not state['aborted']:
                logger.warning('海岛逮捕确认未生效，取消逮捕')
                state['aborted'] = True
            ui.appear_then_click(assets.ARREST_CANCEL, offset=OFFSET, interval=1.5)
            return True
        if not state['max_clicked'] and ui.appear_then_click(assets.ARREST_MAX, offset=OFFSET, interval=1):
            state['max_clicked'] = True
            return True
        if ui.appear_then_click(assets.ARREST_CONFIRM, offset=OFFSET, interval=2):
            state['confirmed'] = True
            state['confirm_clicks'] += 1
            state['confirm_timer'].reset()
        return True
    if ui.appear(assets.ARREST_ANIM_SKIP, offset=OFFSET):
        state['attempted'] = True
        state['confirmed'] = True
        ui.appear_then_click(assets.ARREST_ANIM_SKIP, offset=OFFSET, interval=1)
        return True
    if ui.appear(assets.ARREST_RESULT, offset=OFFSET):
        state['attempted'] = True
        state['confirmed'] = True
        ui.appear_then_click(assets.ARREST_RESULT, offset=OFFSET, interval=1.5)
        return True
    if state['confirmed'] and ui.appear(assets.TAP_BLANK_EXIT, offset=(40, 100), similarity=0.80):
        ui.appear_then_click(assets.TAP_BLANK_EXIT, offset=(40, 100), similarity=0.80, interval=1.5)
        return True
    return False


def _wait_friend_battle(ui, arrest=False):
    """Click START BATTLE on team panel and wait until back on friend's island."""
    started = False
    auto_off = Timer(0.5, count=2).start()
    auto_retry = Timer(4)
    arrest_state = {
        'attempted': False, 'open_clicks': 0, 'open_timer': Timer(2.0), 'max_clicked': False,
        'confirm_clicks': 0, 'confirm_timer': Timer(2.0), 'confirmed': False,
        'aborted': False, 'victory_seen': False, 'victory_settle': Timer(0.6),
    }
    for _ in ui.loop(timeout=240):
        if ui.handle_reward_popup():
            continue
        if started and ui.appear(assets.ISLAND_FRIEND_CHECK, offset=OFFSET):
            return
        if arrest and _handle_arrest_screens(ui, arrest_state):
            started = True
            continue
        if ui.operation_victory_ready():
            started = True
            if arrest and not arrest_state['attempted']:
                if ui.appear(assets.OP_WIN_ARREST, offset=OFFSET):
                    if arrest_state['open_clicks'] >= 2 and arrest_state['open_timer'].reached():
                        logger.warning('海岛逮捕入口未打开弹窗，跳过逮捕')
                        arrest_state['attempted'] = True
                    elif ui.appear_then_click(assets.OP_WIN_ARREST, offset=OFFSET, interval=1.5):
                        arrest_state['open_clicks'] += 1
                        arrest_state['open_timer'].reset()
                    continue
                if not arrest_state['victory_seen']:
                    arrest_state['victory_seen'] = True
                    arrest_state['victory_settle'].reset()
                    continue
                if not arrest_state['victory_settle'].reached():
                    continue
                arrest_state['attempted'] = True
            ui.handle_operation_victory()
            continue
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


def _click_and_fight_monster(ui, target, arrest=False):
    """Tap a friend monster `(x, y)` and complete combat if `OP_TEAM` opens."""
    tx, ty = target
    clicked = False
    wait_team = Timer(2.5).start()
    for _ in ui.loop(timeout=10):
        if ui.appear(assets.OP_TEAM, offset=OFFSET):
            _wait_friend_battle(ui, arrest=arrest)
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
    """Click 清扫 once and require positive evidence before reporting it cleaned."""
    if has_friend_clean_cooldown(ui.device.image):
        return 'cooldown'
    if not has_friend_clean_coin(ui.device.image):
        return 'none'
    before_remaining = read_friend_clean_remaining(ui.device.image)
    clicked = False
    reward_seen = False
    settle = Timer(0.8).start()
    for _ in ui.loop(timeout=8):
        if is_garbage_full_toast(ui.device.image):
            logger.warning('火车垃圾箱暂存区已满，停止好友清扫')
            return 'garbage_full'
        if clicked and ui.appear(assets.ISLAND_FRIEND_CLEAN_RESULT, offset=OFFSET):
            reward_seen = True
        if ui.appear_then_click(assets.ISLAND_FRIEND_CLEAN_RESULT, offset=OFFSET, interval=1.5):
            settle.reset()
            continue
        if ui.handle_reward_popup():
            if clicked:
                reward_seen = True
            settle.reset()
            continue
        if ui.appear_then_click(assets.TAP_BLANK_EXIT, offset=(40, 100), similarity=0.80, interval=1.5):
            settle.reset()
            continue
        if ui.appear(assets.ISLAND_FRIEND_CHECK, offset=OFFSET):
            remaining = read_friend_clean_remaining(ui.device.image) if clicked else None
            if has_friend_clean_cooldown(ui.device.image):
                return 'cooldown'
            if clicked and (
                reward_seen
                or (before_remaining is not None and remaining is not None and remaining < before_remaining)
            ):
                return 'cleaned'
            if not clicked and ui.appear_then_click(assets.ISLAND_FRIEND_CLEAN, offset=OFFSET, interval=2):
                clicked = True
                settle.reset()
                continue
            if settle.reached():
                break
    if has_friend_clean_cooldown(ui.device.image):
        return 'cooldown'
    return 'unknown' if clicked else 'none'


def _advance_next_friend(ui):
    """Click 下一位 if enabled and wait briefly for friend swap."""
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


def _clear_monsters_on_friend(ui, assists, arrest=False):
    """Fight up to `assists` visible monsters on the current friend's island."""
    panned = False
    for _ in range(6):
        if assists <= 0:
            break
        targets = detect_friend_monsters(ui.device.image)
        if targets:
            for target in targets:
                if _click_and_fight_monster(ui, target, arrest=arrest):
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


def _run_friend_fight_phase(ui, allow_clean, arrest=False):
    """Visit friends sorted by 治安 and fight daily monster assists (up to 5)."""
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
        after_assists = _clear_monsters_on_friend(ui, before_assists, arrest=arrest)
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
    """Visit each broom-marked friend once until a clean is positively confirmed."""
    attempted_rows = set()
    for _ in range(30):
        row = _open_friend_and_visit_first(
            ui, assets.ISLAND_FRIEND_SORT_CLEAN, require_clean=True,
            skip_rows=attempted_rows, return_row=True,
        )
        if row is False or row is None:
            logger.info('好友列表无更多可清扫候选，结束好友清扫')
            break
        attempted_rows.add(row)
        res = _clean_current_friend(ui)
        if res == 'garbage_full':
            break
        if res == 'cleaned' and has_friend_clean_coin(ui.device.image) and not has_friend_clean_cooldown(ui.device.image):
            attempted_rows.discard(row)


def _exit_friend_island(ui):
    """Return from friend island back to own beach (`ISLAND_BEACH_CHECK`)."""
    for _ in ui.loop(timeout=20):
        if _dismiss_clean_popup(ui):
            continue
        if ui.appear(assets.ISLAND_FRIEND_LIST, offset=OFFSET):
            ui.device.click(_box_button((860, 360, 940, 420), 'FRIEND_DRAWER_CLOSE'))
            continue
        if ui.appear(assets.ISLAND_BEACH_CHECK, offset=OFFSET):
            return
        if ui.appear_then_click(assets.OP_BACK, offset=OFFSET, interval=2):
            continue
    raise GameStuckError('Did not return from friend island to own beach')


def run_island_friends(ui, fight=True, clean=True, arrest=False):
    """Perform friend island monster combat and garbage cleaning."""
    garbage_full = False
    if fight:
        garbage_full = _run_friend_fight_phase(ui, allow_clean=clean, arrest=arrest)
    if clean and not garbage_full:
        _run_friend_clean_phase(ui)
    _exit_friend_island(ui)
