"""Crew roster row localization, role matching, and 0..5 resonance classifier for 雷索纳斯."""

from difflib import SequenceMatcher

import cv2
import numpy as np

from module.ocr.ocr import Ocr
from module.resonance import assets
from module.resonance.shop import normalize_name

CREW_ROW_Y0 = (85, 388)
CREW_NAME_DY = 217
CREW_NAME_OCR = Ocr([], lang='cnocr', threshold=128, name='Crew name')

_BADGE_MASK = np.zeros((39, 28), dtype=bool)
_BADGE_MASK[:14, :] = True
_BADGE_MASK[24:38, :] = True
_BADGE_OFFSETS = tuple((dy, dx) for dy in range(5) for dx in range(5))
_CREW_RES_VECS = None


def _crew_x0(col):
    """Return left x-coordinate of crew roster column `col` (0..6)."""
    return int(round(16 + col * 179.3))


def _upscale_gray(gray, scale=2, pad_x=0, pad_y=0):
    """Cubic-upscale a grayscale crop with optional dark padding."""
    up = cv2.resize(gray, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if pad_x or pad_y:
        up = cv2.copyMakeBorder(up, pad_y, pad_y, pad_x, pad_x, cv2.BORDER_CONSTANT, value=0)
    return np.stack((up, up, up), axis=2)


def _load_badge_sobel(gray):
    """Return (gx, gy) Sobel gradient pair for a float32 badge array."""
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return gx, gy


def _crew_res_vectors():
    """Build and cache L2-normalized Sobel vectors for resonance digits 0..5."""
    global _CREW_RES_VECS
    if _CREW_RES_VECS is not None:
        return _CREW_RES_VECS

    vecs = {}
    for digit in range(6):
        tmpl = getattr(assets, 'TEMPLATE_CREW_RES_%d' % digit).image
        gray = tmpl.mean(axis=2).astype(np.float32)
        cleaned = np.zeros_like(gray)
        cleaned[:14] = np.where(gray[:14] > 140, gray[:14], 0.0)
        cleaned[24:38] = np.where(gray[24:38] > 115, gray[24:38], 0.0)
        gx, gy = _load_badge_sobel(cleaned)
        vec = np.concatenate((gx[_BADGE_MASK], gy[_BADGE_MASK]))
        vec = vec - vec.mean()
        norm = float(np.linalg.norm(vec))
        vecs[digit] = vec / norm if norm > 1e-6 else vec
    _CREW_RES_VECS = vecs
    return vecs


def _best_digit_score(pgx, pgy, tmpl_vec):
    """Return max cosine similarity between Sobel patch and a normalized digit vector."""
    best = -1.0
    for dy, dx in _BADGE_OFFSETS:
        sgx = pgx[dy:dy + 39, dx:dx + 28]
        sgy = pgy[dy:dy + 39, dx:dx + 28]
        if sgx.shape != _BADGE_MASK.shape:
            continue
        vec = np.concatenate((sgx[_BADGE_MASK], sgy[_BADGE_MASK]))
        vec = vec - vec.mean()
        denom = float(np.linalg.norm(vec))
        if denom > 1e-6:
            score = float(np.dot(vec, tmpl_vec)) / denom
            if score > best:
                best = score
    return best


def _best_role_match(clean, candidates, min_ratio=0.65, max_len_diff=1):
    """Return highest-scoring candidate within length tolerance and positional/prefix guard."""
    eligible = [
        c for c in candidates
        if abs(len(clean) - len(c)) <= max_len_diff and (
            (len(clean) == len(c) and sum(a == b for a, b in zip(clean, c)) >= max(1, len(c) - 1))
            or (abs(len(clean) - len(c)) == 1 and (clean in c or c in clean))
        )
    ]
    if not eligible:
        return None
    best = max(eligible, key=lambda r: SequenceMatcher(None, clean, r).ratio())
    if SequenceMatcher(None, clean, best).ratio() >= min_ratio:
        return best
    return None


def match_crew_role(raw_name, known_roles):
    """Match OCR crew name to a Columba skill role while preventing SP/prefix collisions."""
    clean = normalize_name(raw_name or '').strip('_l」|')
    if not clean:
        return None
    if clean in known_roles:
        return clean

    dot_roles = [r for r in known_roles if '·' in r]
    plain_dot_map = {r.replace('·', ''): r for r in dot_roles}
    no_dot = clean.replace('·', '')
    if no_dot in plain_dot_map:
        return plain_dot_map[no_dot]

    base_roles = [r for r in known_roles if '·' not in r]
    is_alter = ('·' in clean) or any(no_dot != b and no_dot.startswith(b) and len(no_dot) - len(b) >= 2 for b in base_roles)
    if is_alter:
        matched = _best_role_match(no_dot, plain_dot_map.keys(), min_ratio=0.72)
        return plain_dot_map[matched] if matched else None

    if len(clean) == 1:
        short = [r for r in base_roles if r.startswith(clean) and len(r) <= 2]
        return short[0] if len(short) == 1 else None
    matched = _best_role_match(clean, base_roles, min_ratio=0.65, max_len_diff=1)
    if matched:
        return matched
    if len(clean) == 2:
        pair = [r for r in base_roles if len(r) == 2 and r[0] == clean[0]]
        return pair[0] if len(pair) == 1 else None
    return None


def detect_crew_rows(image):
    """Detect fully visible crew roster row Y-tops regardless of scroll offset."""
    label = assets.TEMPLATE_CREW_RES_LABEL.image.mean(axis=2).astype(np.float32)
    best_per_y = np.zeros(720 - label.shape[0], dtype=np.float32)
    sum_per_y = np.zeros_like(best_per_y)
    for col in range(7):
        x0 = _crew_x0(col)
        band = image[65:660, x0 + 122:min(1280, x0 + 168)].mean(axis=2).astype(np.float32)
        if band.shape[1] < label.shape[1]:
            continue
        col_max = cv2.matchTemplate(band, label, cv2.TM_CCOEFF_NORMED).max(axis=1)
        best_per_y[65:65 + len(col_max)] = np.maximum(best_per_y[65:65 + len(col_max)], col_max)
        sum_per_y[65:65 + len(col_max)] += np.maximum(0.0, col_max)

    anchor_y_res = int(np.argmax(sum_per_y[75:520])) + 75
    if best_per_y[anchor_y_res] < 0.50:
        return list(CREW_ROW_Y0)

    rows = []
    anchor_y_top = anchor_y_res - 15
    for k in (-1, 0, 1, 2):
        y_top = anchor_y_top + k * 303
        if 65 <= y_top <= 482:
            lo = max(65, y_top + 15 - 3)
            hi = min(650, y_top + 15 + 4)
            fine_y_res = lo + int(np.argmax(best_per_y[lo:hi]))
            if best_per_y[fine_y_res] >= 0.50:
                rows.append(fine_y_res - 15)
    return rows or list(CREW_ROW_Y0)


def is_crew_slot_occupied(image, x0, y_top):
    """Return True when a roster grid slot holds a character card rather than empty background."""
    bottom = image[y_top + 190:min(720, y_top + 245), x0 + 15:min(1280, x0 + 160)]
    return float(bottom.mean()) < 160.0


def classify_crew_resonance(image, x0, y0):
    """Classify the top-right resonance digit (0..5) via background-free Sobel matching."""
    y1, y2 = max(0, y0 - 2), min(720, y0 + 41)
    x1, x2 = max(0, x0 + 132), min(1280, x0 + 164)
    patch = image[y1:y2, x1:x2]
    if patch.shape[0] < 39 or patch.shape[1] < 28:
        return 0
    pgx, pgy = _load_badge_sobel(patch.mean(axis=2).astype(np.float32))
    vecs = _crew_res_vectors()
    return max(vecs, key=lambda d: _best_digit_score(pgx, pgy, vecs[d]))


def _collect_row_cards(image, yb_row, name_y, known_roles, roles):
    """OCR one 7-column row of crew cards and update `roles` in place."""
    crops = []
    valid = []
    for col in range(7):
        x0 = _crew_x0(col)
        if not is_crew_slot_occupied(image, x0, yb_row):
            continue
        card = image[name_y:name_y + 22, x0 + 20:min(1280, x0 + 165)]
        crops.append(_upscale_gray(card.mean(axis=2).astype(np.uint8), scale=3, pad_x=10, pad_y=6))
        valid.append(x0)
    if not crops:
        return
    names = CREW_NAME_OCR.ocr(crops, direct_ocr=True)
    for x0, raw_name in zip(valid, names):
        role = match_crew_role(raw_name, known_roles)
        if not role:
            continue
        lv = classify_crew_resonance(image, x0, yb_row)
        if role not in roles or lv > roles[role]:
            roles[role] = lv


def parse_crew_roster_page(image, known_roles):
    """Scan all fully visible crew roster rows and return {role_name: level}."""
    roles = {}
    for yb in detect_crew_rows(image):
        _collect_row_cards(image, yb, yb + CREW_NAME_DY, known_roles, roles)
    return roles
