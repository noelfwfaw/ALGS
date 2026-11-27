"""Text parsing and target-matching helpers for Resonance Solstice exchange trade."""

from difflib import SequenceMatcher
import re

from module.resonance.shop import normalize_name


def parse_cargo_text(text):
    """Parse cargo indicator like '108+226/994' or '3-3/994' into (loaded, delta, capacity)."""
    match = re.fullmatch(r'(\d+)([+-]\d+)?/(\d+)', normalize_name(text or ''))
    if not match:
        return None
    loaded = int(match.group(1))
    delta = int(match.group(2)) if match.group(2) else 0
    return loaded, delta, int(match.group(3))


def parse_fraction_text(text):
    """Parse 'cur/total' OCR output into (cur, total)."""
    match = re.fullmatch(r'(\d+)/(\d+)', normalize_name(text or ''))
    return (int(match.group(1)), int(match.group(2))) if match else None


def parse_fatigue_text(text, known_max=None):
    """Parse 'cur/max' fatigue OCR, recovering dropped '/' (e.g. '894912' -> (894, 912))."""
    frac = parse_fraction_text(text)
    if frac is not None and frac[1] > 0:
        return frac
    digits = normalize_name(text or '')
    if not digits.isdigit():
        return None
    if known_max and known_max > 0:
        ms = str(known_max)
        if digits.endswith(ms):
            for sep in (0, 1):
                cut = len(digits) - len(ms) - sep
                if cut > 0 and (sep == 0 or digits[cut] == '1') and int(digits[:cut]) <= known_max:
                    return int(digits[:cut]), known_max
    for n_total, lo, hi in ((3, 150, 999), (4, 1000, 1500)):
        for sep in (0, 1):
            cut = len(digits) - n_total - sep
            if cut > 0 and (sep == 0 or digits[cut] == '1'):
                cur, total = int(digits[:cut]), int(digits[-n_total:])
                if lo <= total <= hi and cur <= total:
                    return cur, total
    return None


def parse_pct_text(text):
    """Parse percentage string like '13.0%' into float."""
    match = re.fullmatch(r'(\d+(?:\.\d+)?)%', normalize_name(text or ''))
    return float(match.group(1)) if match else None


def split_buy_targets(plan_or_items):
    """Split a route leg dict or name sequence into (full_names_set, partial_tail_name)."""
    if isinstance(plan_or_items, dict):
        full_names = set()
        tail_name = None
        for item in plan_or_items.get('combinations', ()):
            name = normalize_name(item.get('name', ''))
            if not name:
                continue
            buy_lot = item.get('buy_lot', 0)
            avail_lot = item.get('available_lot', buy_lot)
            if buy_lot < avail_lot:
                tail_name = name
            else:
                full_names.add(name)
        return full_names, tail_name

    full_names = {normalize_name(name) for name in (plan_or_items or ()) if normalize_name(name)}
    return full_names, None


def match_buy_target(ocr_name, target_names):
    """Match an OCR commodity name to `target_names` (exact first, then fuzzy >= 0.75)."""
    if ocr_name in target_names:
        return ocr_name
    if len(ocr_name) < 3:
        return None
    score, tgt = max(
        ((SequenceMatcher(None, ocr_name, t).ratio(), t) for t in target_names),
        default=(0.0, None),
    )
    return tgt if score >= 0.75 else None
