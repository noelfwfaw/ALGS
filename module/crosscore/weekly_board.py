"""Tactical board and crystal split helpers for Cross Core weekly dungeon (`碎星虚影`)."""

import cv2
import numpy as np
from scipy import ndimage

from module.base.utils import crop
from module.crosscore.assets import WEEKLY_BOSS_ICON, WEEKLY_ENEMY_LV, WEEKLY_MY_TURN
from module.crosscore.utils import template_of

ENEMY_SEARCH_AREA = (60, 0, 1085, 620)
TILE_SEARCH_AREA = (120, 60, 1040, 640)
RING_SCALES = ((125, 95, 55, 43, 180), (85, 65, 33, 25, 110))


def is_near_any(x, y, points, dx, dy):
    """Whether `(x, y)` lies within `(dx, dy)` of any recorded `(ox, oy, ...)`."""
    return any(abs(x - p[0]) <= dx and abs(y - p[1]) <= dy for p in points)


def is_my_turn(image):
    """Whether bottom-right `我方回合` yellow badge is active (background-invariant)."""
    roi = crop(image, WEEKLY_MY_TURN.area, copy=False).astype(int)
    r, g, b = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
    return int(((r > 180) & (g > 130) & (b < 95) & (r - b > 95)).sum()) >= 80


def split_crystal_num_end(image):
    """Find `x_cut` right before `/` between weekly crystal numerator and cap."""
    top = image[629:637, 130:185].min(axis=2)
    top_cols = np.where(top.max(axis=0) > 170)[0]
    if not len(top_cols):
        return 156
    slash_right = int(top_cols[-1]) + 130
    full = image[629:651, 130:slash_right + 1].min(axis=2)
    col_has = (full.max(axis=0) > 165)
    in_slash = False
    for cx in range(len(col_has) - 1, 5, -1):
        if col_has[cx]:
            in_slash = True
        elif in_slash:
            return 130 + cx + 1
    return 156


def _match_plate_enemies(roi, enemies):
    """Detect enemies by overhead `- 等级.` plate inside `ENEMY_SEARCH_AREA`."""
    ox, oy = ENEMY_SEARCH_AREA[0], ENEMY_SEARCH_AREA[1]
    res = cv2.matchTemplate(roi, template_of(WEEKLY_ENEMY_LV), cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(res >= 0.75)
    for y, x in sorted(zip(ys, xs), key=lambda t: -res[t[0], t[1]]):
        ex, ey = int(x + ox + 46), int(y + oy + 12 + 118)
        if not is_near_any(ex, ey, enemies, 45, 35):
            enemies.append((ex, ey, False))


def _match_badge_enemies(roi, enemies):
    """Detect enemies by yellow `[1]`/`[2]` turn badge (catches top-edge units)."""
    ox, oy = ENEMY_SEARCH_AREA[0], ENEMY_SEARCH_AREA[1]
    roi_i = roi.astype(int)
    ymask = (
        (roi_i[:, :, 0] > 200) & (roi_i[:, :, 1] > 155)
        & (roi_i[:, :, 2] < 85) & (roi_i[:, :, 0] - roi_i[:, :, 2] > 130)
    )
    lbl, n = ndimage.label(ymask)
    for idx in range(1, n + 1):
        bys, bxs = np.where(lbl == idx)
        if 150 <= len(bxs) <= 1200:
            ex, ey = int(bxs.mean()) + ox - 55, int(bys.mean()) + oy + 73
            if not is_near_any(ex, ey, enemies, 45, 35):
                enemies.append((ex, ey, False))


def find_map_enemies(image):
    """Return `[(ex, ey, is_boss), ...]` ground tile centers for visible enemies."""
    ox, oy = ENEMY_SEARCH_AREA[0], ENEMY_SEARCH_AREA[1]
    roi = crop(image, ENEMY_SEARCH_AREA, copy=False)
    enemies = []
    res_b = cv2.matchTemplate(roi, template_of(WEEKLY_BOSS_ICON), cv2.TM_CCOEFF_NORMED)
    _, max_v, _, max_l = cv2.minMaxLoc(res_b)
    if max_v >= 0.75:
        enemies.append((int(max_l[0] + ox + 25), int(max_l[1] + oy + 13) + 157, True))
    _match_plate_enemies(roi, enemies)
    _match_badge_enemies(roi, enemies)
    return enemies


def _snap_green_tile(gmask, tx, ty):
    """Snap `(tx, ty)` to its surrounding green-border bounding-box midpoint."""
    tx0, ty0, tx1, ty1 = TILE_SEARCH_AREA
    x1, y1 = max(tx0, tx - 70), max(ty0, ty - 55)
    x2, y2 = min(tx1, tx + 70), min(ty1, ty + 55)
    ys, xs = np.where(gmask[y1:y2, x1:x2] > 0)
    if len(xs) < 120 or int(xs.max() - xs.min()) < 75 or int(ys.max() - ys.min()) < 50:
        return None
    return int(x1 + (int(xs.min()) + int(xs.max())) // 2), int(y1 + (int(ys.min()) + int(ys.max())) // 2)


def _ray_enclosed(gmask, tx, ty):
    """Verify `(tx, ty)` lies inside a green-bordered tile rather than a chasm or line."""
    tx0, ty0, tx1, ty1 = TILE_SEARCH_AREA
    center = int(gmask[max(ty0, ty - 16):min(ty1, ty + 16), max(tx0, tx - 16):min(tx1, tx + 16)].sum())
    if center > 15:
        return False
    up = int(gmask[max(ty0, ty - 58):max(ty0, ty - 14), tx - 14:tx + 14].sum())
    dn = int(gmask[min(ty1, ty + 14):min(ty1, ty + 58), tx - 14:tx + 14].sum())
    lt = int(gmask[ty - 12:ty + 12, max(tx0, tx - 68):max(tx0, tx - 14)].sum())
    rt = int(gmask[ty - 12:ty + 12, min(tx1, tx + 14):min(tx1, tx + 68)].sum())
    tb = (up >= 10 and dn >= 10)
    lr = (lt >= 10 and rt >= 10)
    if not (tb or lr):
        return False
    sides = (up >= 10) + (dn >= 10) + (lt >= 10) + (rt >= 10)
    return sides >= 3 or (tb and up + dn >= 35) or (lr and lt + rt >= 35)


def _collect_ring_peaks(roi_f, gmask, tiles, spec):
    """Run one hollow-ring convolution scale and append valid unique tile centers."""
    w, h, iw, ih, min_score = spec
    k_outer = cv2.getStructuringElement(cv2.MORPH_RECT, (w, h)).astype(np.float32)
    k_inner = np.zeros((h, w), dtype=np.float32)
    y0, x0 = (h - ih) // 2, (w - iw) // 2
    k_inner[y0:y0 + ih, x0:x0 + iw] = 1.0
    score = cv2.filter2D(roi_f, -1, k_outer - 2.2 * k_inner)
    max_f = ndimage.maximum_filter(score, size=45)
    pys, pxs = np.where((score == max_f) & (score >= min_score))
    tx0, ty0 = TILE_SEARCH_AREA[0], TILE_SEARCH_AREA[1]
    for y, x in sorted(zip(pys, pxs), key=lambda t: -score[t[0], t[1]]):
        tx, ty = int(x) + tx0, int(y) + ty0
        if _ray_enclosed(gmask, tx, ty) and not is_near_any(tx, ty, tiles, 55, 45):
            tiles.append((tx, ty))


def _sample_polygon_row(dist, cy, tiles):
    """Sample walkable tile centers along one horizontal band inside a merged polygon."""
    tx0, ty0 = TILE_SEARCH_AREA[0], TILE_SEARCH_AREA[1]
    band = dist[max(0, cy - 18):min(dist.shape[0], cy + 18), :]
    rxs = np.where(band.max(axis=0) >= 8)[0]
    if not len(rxs):
        return
    rx0, rx1 = int(rxs.min()), int(rxs.max())
    ncols = max(1, int(round((rx1 - rx0 + 25) / 120.0)))
    cxs = [int(round(v)) for v in np.linspace(rx0 + 42, rx1 - 42, ncols)] if ncols > 1 else [(rx0 + rx1) // 2]
    for cx in cxs:
        px, py = cx + tx0, cy + ty0
        if not is_near_any(px, py, tiles, 55, 45):
            tiles.append((px, py))


def _sample_polygon_component(comp_mask, ys, tiles):
    """Extract tile centers inside one bounded-scanline enclosed region."""
    dist = cv2.distanceTransform(comp_mask, cv2.DIST_L2, 5)
    gy0, gy1 = int(ys.min()), int(ys.max())
    nrows = max(1, int(round((gy1 - gy0 + 25) / 130.0)))
    cys = [int(round(v)) for v in np.linspace(gy0 + 42, gy1 - 42, nrows)] if nrows > 1 else [(gy0 + gy1) // 2]
    for cy in cys:
        _sample_polygon_row(dist, cy, tiles)


def _collect_polygon_tiles(roi, tiles):
    """Use 4-direction bounded scanline enclosure to recover tiles inside merged polygons."""
    thick = cv2.dilate(roi, np.ones((15, 15), np.uint8))
    l_near = ndimage.maximum_filter1d(thick, size=300, axis=1, origin=149) > 0
    r_near = ndimage.maximum_filter1d(thick, size=300, axis=1, origin=-150) > 0
    u_near = ndimage.maximum_filter1d(thick, size=300, axis=0, origin=149) > 0
    d_near = ndimage.maximum_filter1d(thick, size=300, axis=0, origin=-150) > 0
    interior = (l_near & r_near & u_near & d_near & (thick == 0)).astype(np.uint8)
    lbl, n = ndimage.label(interior)
    for idx in range(1, n + 1):
        ys, xs = np.where(lbl == idx)
        if len(xs) >= 350:
            _sample_polygon_component((lbl == idx).astype(np.uint8), ys, tiles)


def find_green_tiles(image):
    """Return `(tiles, gmask)` where `tiles` is walkable green-bordered `(gx, gy)` centers."""
    img_i = image.astype(int)
    r, g, b = img_i[:, :, 0], img_i[:, :, 1], img_i[:, :, 2]
    gmask = ((g > 95) & (g - r >= 16) & (g - b >= 20) & (r >= b - 15)).astype(np.uint8)
    roi = crop(gmask, TILE_SEARCH_AREA, copy=False)
    roi_f = roi.astype(np.float32)
    tiles = []
    for spec in RING_SCALES:
        _collect_ring_peaks(roi_f, gmask, tiles, spec)
    _collect_polygon_tiles(roi, tiles)
    return tiles, gmask


def find_push_switches(image, pushed=()):
    """Return `[(sx, sy), ...]` centers of active neon-pink `PUSH` switch tiles."""
    tx0, ty0, _, _ = TILE_SEARCH_AREA
    roi = crop(image, TILE_SEARCH_AREA, copy=False).astype(int)
    r, g, b = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
    pmask = ((r > 185) & (b > 150) & (r - g > 45) & (b - g > 20) & (r >= b - 10)).astype(np.uint8)
    dilated = cv2.dilate(pmask, np.ones((7, 7), np.uint8))
    num, labels, stats, centroids = cv2.connectedComponentsWithStats(dilated)
    switches = []
    for idx in range(1, num):
        w, h = int(stats[idx, cv2.CC_STAT_WIDTH]), int(stats[idx, cv2.CC_STAT_HEIGHT])
        if 50 <= w <= 140 and 35 <= h <= 110 and int(pmask[labels == idx].sum()) >= 400:
            sx, sy = tx0 + int(centroids[idx][0]), ty0 + int(centroids[idx][1])
            if not is_near_any(sx, sy, pushed, 45, 45):
                switches.append((sx, sy))
    return switches


def pick_combat_candidates(image, pushed=()):
    """Rank `(point, action)` clicks: reachable enemies, `PUSH` switches, else move closer."""
    enemies = find_map_enemies(image)
    tiles, gmask = find_green_tiles(image)
    switches = find_push_switches(image, pushed)
    candidates = []
    for ex, ey, is_boss in sorted(enemies, key=lambda e: (not e[2], e[1])):
        px = int(gmask[max(0, ey - 55):min(720, ey + 55), max(0, ex - 75):min(1280, ex + 75)].sum())
        if px >= 40:
            target = _snap_green_tile(gmask, ex, ey) or (ex, ey)
            candidates.append((target, 'attack_boss' if is_boss else 'attack_mob'))
    for sx, sy in switches:
        px = int(gmask[max(0, sy - 55):min(720, sy + 55), max(0, sx - 75):min(1280, sx + 75)].sum())
        if px >= 40:
            candidates.append(((sx, sy), 'push_switch'))
    if switches and tiles:
        ranked = sorted(tiles, key=lambda t: min((t[0] - s[0]) ** 2 + (t[1] - s[1]) ** 2 for s in switches))
        candidates.extend((tile, 'move') for tile in ranked)
    elif enemies and tiles:
        bosses = [e for e in enemies if e[2]]
        pool = bosses if bosses else enemies
        ranked = sorted(tiles, key=lambda t: min((t[0] - e[0]) ** 2 + (t[1] - e[1]) ** 2 for e in pool))
        candidates.extend((tile, 'move') for tile in ranked)
    elif tiles:
        candidates.extend((tile, 'move') for tile in tiles)
    return candidates
