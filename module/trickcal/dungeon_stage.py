"""CV, OCR, and layout helpers for Trickcal resource dungeons."""

from collections import Counter
import re

import cv2
import numpy as np

from module.base.button import Button
from module.base.utils import crop, get_color
from module.logger import logger
from module.ocr.ocr import Ocr
from module.trickcal.assets import (
    DUNGEON_BAKERY_SWEEP,
    DUNGEON_CANDY_SWEEP,
    DUNGEON_CLONE_SWEEP,
    DUNGEON_CRAYON_SWEEP,
    DUNGEON_GOLD_SWEEP,
)

# Star-candy stamina pill on top bar (bakery omits currency, shifting pill left).
STAMINA_AREA_DEFAULT = (708, 24, 810, 52)
STAMINA_AREA_BAKERY = (574, 24, 672, 52)

CLONE_SPLASH_COUNT_AREA = (1120, 344, 1190, 380)
CLONE_STAGE_COUNT_AREA = (1176, 576, 1208, 604)

# Selected stage number badges on each dungeon's right detail panel.
SELECTED_STAGE_AREAS = {
    'gold': (858, 118, 898, 162),
    'candy': (758, 160, 790, 186),
    'crayon': (742, 120, 786, 152),
    'clone': (914, 96, 956, 130),
}
BAKERY_BADGE_SEARCH_AREA = (835, 172, 985, 222)

BAKERY_TABS = {
    'bakery_macaron': (74, 82, 356, 132),
    'bakery_cream': (384, 82, 666, 132),
}
BAKERY_TAB_PINK_PIXELS = 3000

CANDY_MACHINE_AREAS = {
    'candy_red': (200, 220, 400, 480),
    'candy_blue': (560, 220, 760, 480),
    'candy_green': (930, 220, 1130, 480),
}

CRAYON_PAGE_AREA = (320, 664, 364, 710)
CRAYON_PREV_AREA = (232, 662, 268, 706)
CRAYON_NEXT_AREA = (415, 662, 450, 706)
CRAYON_COLS = (88, 210, 330, 452, 572)
CRAYON_ROWS = (240, 520)

CLONE_COLS = (115, 280, 445, 610)
CLONE_ROWS = (215, 405, 595)

BAKERY_COLS = (144, 370, 596)
CANDY_COLS = (122, 352, 582)

SWEEP_COLOR_THRESHOLD = 35
CANDY_SWEEP_SAT_THRESHOLD = 30.0

_OCR_CACHE = {}


def tap_box(area, name):
    """Build a dynamic tap-only Button inside functions (avoids module-level R9)."""
    return Button(area=area, color=(0, 0, 0), button=area, name=name)


def _get_stamina_ocr(area, name):
    key = ('stamina', area)
    if key not in _OCR_CACHE:
        _OCR_CACHE[key] = Ocr(
            tap_box(area, name),
            lang='azur_lane',
            letter=(65, 65, 65),
            threshold=128,
            alphabet='0123456789/',
            name=name,
        )
    return _OCR_CACHE[key]


def _get_cnocr():
    if 'cnocr' not in _OCR_CACHE:
        _OCR_CACHE['cnocr'] = Ocr(
            tap_box((0, 0, 10, 10), 'DUNGEON_CNOCR'),
            lang='cnocr',
            alphabet='0123456789/',
            name='DUNGEON_CNOCR',
        )
    return _OCR_CACHE['cnocr']


def _ocr_bw(bw_img, alphabet='0123456789'):
    """OCR a tight binary mask (`0=text, 255=background`) with cnocr."""
    if bw_img.size == 0 or int((bw_img == 0).sum()) < 8:
        return ''
    ys, xs = np.where(bw_img == 0)
    y1 = max(0, int(ys.min()) - 2)
    y2 = min(bw_img.shape[0], int(ys.max()) + 3)
    x1 = max(0, int(xs.min()) - 2)
    x2 = min(bw_img.shape[1], int(xs.max()) + 3)
    tight = bw_img[y1:y2, x1:x2]
    h, w = tight.shape
    scale = 28.0 / max(h, 1)
    resized = cv2.resize(tight, (max(6, int(w * scale)), 28), interpolation=cv2.INTER_AREA)
    padded = cv2.copyMakeBorder(resized, 4, 4, 14, 14, cv2.BORDER_CONSTANT, value=255)
    ocr = _get_cnocr()
    ocr.cnocr.set_cand_alphabet(alphabet)
    res = ocr.cnocr.ocr_for_single_line(padded)
    return ''.join(res) if isinstance(res, list) else str(res)


def _ocr_int_bw(bw_img):
    """Read a positive integer from a binary mask (`0=text, 255=background`), or None."""
    txt = _ocr_bw(bw_img, alphabet='0123456789')
    m = re.search(r'\d+', txt)
    return int(m.group(0)) if m else None


def _otsu_bw(patch_rgb, invert=False):
    """Binarize a small RGB crop via Otsu thresholding into `0=text, 255=bg`."""
    gray = cv2.cvtColor(patch_rgb, cv2.COLOR_RGB2GRAY)
    if invert:
        gray = 255 - gray
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    return bw


def read_dungeon_stamina(image, bakery=False):
    """Read current star-candy stamina (`cur/cap`) from top bar, or None."""
    area = STAMINA_AREA_BAKERY if bakery else STAMINA_AREA_DEFAULT
    raw = _get_stamina_ocr(area, 'OCR_STAR_STAMINA').ocr(image)
    m = re.match(r'^(\d+)\s*/\s*(\d+)$', raw.strip())
    if not m:
        logger.warning(f'Could not parse star-candy stamina: {raw!r}')
        return None
    return int(m.group(1))


def read_clone_daily_remaining(image, on_splash=True):
    """Read remaining daily entries (`0..8`) in 克隆工厂."""
    if on_splash:
        patch = crop(image, CLONE_SPLASH_COUNT_AREA)
        bw = _otsu_bw(patch, invert=True)
        txt = _ocr_bw(bw, alphabet='0123456789/')
        m = re.search(r'(\d+)\s*/\s*(\d+)', txt)
        if m:
            return int(m.group(1))
        logger.warning(f'Could not parse clone splash remaining entries: {txt!r}')
        return None
    patch = crop(image, CLONE_STAGE_COUNT_AREA)
    bw = _otsu_bw(patch, invert=True)
    return _ocr_int_bw(bw)


def read_selected_stage(image, kind):
    """Read the currently selected stage number from the right detail panel, or None."""
    if kind == 'bakery':
        bx1, by1, bx2, by2 = BAKERY_BADGE_SEARCH_AREA
        roi = crop(image, BAKERY_BADGE_SEARCH_AREA)
        pm = (roi[:, :, 0] > 180) & (roi[:, :, 1] < 130) & (roi[:, :, 2] < 140)
        ys, xs = np.where(pm)
        if len(xs) < 20:
            return None
        sub = image[
            by1 + int(ys.min()) + 4 : by1 + int(ys.max()) - 3,
            bx1 + int(xs.min()) + 4 : bx1 + int(xs.max()) - 3,
        ]
        bw = np.where(sub.min(axis=2) > 195, 0, 255).astype(np.uint8)
        return _ocr_int_bw(bw)

    area = SELECTED_STAGE_AREAS[kind]
    patch = crop(image, area)
    bw = _otsu_bw(patch, invert=(kind == 'clone'))
    return _ocr_int_bw(bw)


def read_crayon_page(image):
    """Read current bottom page number (`1`, `2`, ...) in 到手蜡."""
    patch = crop(image, CRAYON_PAGE_AREA)
    mask = (patch[:, :, 0] > 180) & (patch[:, :, 1] < 110) & (patch[:, :, 2] < 120)
    bw = np.where(mask, 0, 255).astype(np.uint8)
    return _ocr_int_bw(bw)


def crayon_target_page(stage):
    """Return 1-based page index for stage number `stage` (10 stages per page)."""
    return (max(1, int(stage)) - 1) // 10 + 1


def crayon_slot_area(stage):
    """Return fixed `(x1, y1, x2, y2)` tap area on page for a 到手蜡 stage."""
    idx = (max(1, int(stage)) - 1) % 10
    row, col = divmod(idx, 5)
    cx, cy = CRAYON_COLS[col], CRAYON_ROWS[row]
    return (cx - 32, cy - 48, cx + 32, cy + 48)


def clone_slot_area(stage):
    """Return fixed `(x1, y1, x2, y2)` tap area for 克隆工厂 stage `1..12`."""
    idx = max(1, min(12, int(stage))) - 1
    row, col = divmod(idx, 4)
    cx, cy = CLONE_COLS[col], CLONE_ROWS[row]
    return (cx - 45, cy - 45, cx + 45, cy + 45)


def bakery_tab_selected(image, tab_key):
    """Return True when the given 神秘面包房 top tab is selected (pink)."""
    patch = crop(image, BAKERY_TABS[tab_key])
    pink = (patch[:, :, 0] > 210) & (patch[:, :, 1] < 175) & (patch[:, :, 2] < 185)
    return int(pink.sum()) >= BAKERY_TAB_PINK_PIXELS


def _resolve_three_col_row(row_reads):
    """
    Infer all 3 stage numbers in a 3-column shelf row from partial OCR reads.

    Args:
        row_reads (list[tuple[int, int, int, int | None]]): `(col, cx, cy, val)`.

    Returns:
        dict[int, tuple[int, int]]: Mapping `{stage_num: (cx, cy)}`.
    """
    candidates = []
    for col, _, _, val in row_reads:
        if val is not None and val >= 1:
            base = val - col
            if base >= 1:
                candidates.append(base)
    if not candidates:
        return {}
    counts = Counter(candidates)
    best_base = max(counts.keys(), key=lambda b: (counts[b], (b - 1) % 3 == 0, -b))
    return {best_base + col: (cx, cy) for col, cx, cy, _ in row_reads}


def find_gold_vaults(image):
    """Locate visible vault tiles (`1..20 -> (cx, cy)`) in 金币大作战 blueprint map."""
    gx1, gy1, gx2, gy2 = 0, 75, 760, 715
    roi = image[gy1:gy2, gx1:gx2]
    r_ch = roi[:, :, 0].astype(np.int16)
    g_ch = roi[:, :, 1].astype(np.int16)
    border = (
        (roi.min(axis=2) > 180) | ((r_ch - g_ch > 45) & (roi[:, :, 0] > 140))
    ).astype(np.uint8) * 255
    closed = cv2.morphologyEx(border, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11)))
    inv = 255 - closed
    num, _, stats, _ = cv2.connectedComponentsWithStats(inv)
    found = {}
    for idx in range(1, num):
        x, y, w, h, area = stats[idx]
        if 60 <= w <= 135 and 60 <= h <= 135 and area > 2500:
            cx, cy = gx1 + int(x + w // 2), gy1 + int(y + h // 2)
            patch = image[gy1 + y + 12 : gy1 + y + int(h * 0.50), gx1 + x + 20 : gx1 + x + w - 20]
            bw = np.where(patch.min(axis=2) > 195, 0, 255).astype(np.uint8)
            val = _ocr_int_bw(bw)
            if val is not None and 1 <= val <= 20:
                found[val] = (cx, cy)
    return found


def find_bakery_stages(image):
    """Locate visible 3-column shelf stage tiles in 神秘面包房 (`stage -> (cx, cy)`)."""
    gx1, gy1, gx2, gy2 = 35, 150, 705, 700
    roi = image[gy1:gy2, gx1:gx2]
    wood = (
        (roi[:, :, 0] > 100)
        & (roi[:, :, 0] < 195)
        & (roi[:, :, 1] > 55)
        & (roi[:, :, 1] < 135)
        & (roi[:, :, 2] < 85)
    ).mean(axis=1)
    s_ys = np.where(wood > 0.50)[0] + gy1
    shelves = []
    for y in s_ys:
        if not shelves or y > shelves[-1][1] + 80:
            shelves.append([int(y), int(y)])
        else:
            shelves[-1][1] = int(y)

    found = {}
    for _, sy2 in shelves:
        cy = sy2 - 9
        if cy < 170 or cy > 690:
            continue
        reads = []
        for col, cx in enumerate(BAKERY_COLS):
            patch = image[cy - 14 : cy + 14, cx - 26 : cx + 26]
            val = _ocr_int_bw(_otsu_bw(patch, invert=True))
            reads.append((col, cx, cy, val))
        found.update(_resolve_three_col_row(reads))
    return found


def find_candy_stages(image):
    """Locate visible 3-column jar stage tiles in 糖果自由 (`stage -> (cx, cy)`)."""
    gx1, gy1, gx2, gy2 = 30, 75, 680, 700
    roi = image[gy1:gy2, gx1:gx2]
    shelf = (roi[:, :, 0] > 140) & (roi[:, :, 1] < 105) & (roi[:, :, 2] < 110)
    s_ys = np.where(shelf.mean(axis=1) > 0.70)[0] + gy1
    shelves = []
    for y in s_ys:
        if not shelves or y > shelves[-1][1] + 15:
            shelves.append([int(y), int(y)])
        else:
            shelves[-1][1] = int(y)

    found = {}
    for sy1, _ in shelves:
        by = sy1 - 108
        if by < 78 or by > 685:
            continue
        reads = []
        for col, cx in enumerate(CANDY_COLS):
            patch = image[by - 18 : by + 18, cx - 24 : cx + 24]
            val = _ocr_int_bw(_otsu_bw(patch, invert=False))
            reads.append((col, cx, by, val))
        found.update(_resolve_three_col_row(reads))
    return found


def dungeon_sweep_lit(image, kind):
    """Return True if the dungeon's 速战 button is lit (3-starred & usable)."""
    if kind == 'candy':
        rgb = np.array(get_color(image, DUNGEON_CANDY_SWEEP.area))
        return float(rgb.max() - rgb.min()) >= CANDY_SWEEP_SAT_THRESHOLD

    btn = {
        'gold': DUNGEON_GOLD_SWEEP,
        'bakery': DUNGEON_BAKERY_SWEEP,
        'crayon': DUNGEON_CRAYON_SWEEP,
        'clone': DUNGEON_CLONE_SWEEP,
    }[kind]
    return btn.appear_on(image, threshold=SWEEP_COLOR_THRESHOLD)
