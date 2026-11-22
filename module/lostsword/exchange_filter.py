"""Filter and currency helpers for Lost Sword Exchange (`交易所`) shop."""

import re

import numpy as np

from module.base.button import Button
from module.base.utils import crop

EXCHANGE_BLUE_CARD_MIN = 40
EXCHANGE_BLUE_DIALOG_MIN = 30


def exchange_norm(text):
    """Normalize an item name, stripping `(T1)`, `的`, punctuation, and lowercase OCR noise."""
    text = re.sub(r'[\(（][tT]\d+[\)）]', '', str(text))
    text = re.sub(r'[^0-9A-Z\u4e00-\u9fa5]', '', text)
    return text.replace('的', '')


def _is_subseq(short_s, long_s):
    it = iter(long_s)
    return all(ch in it for ch in short_s)


def exchange_keyword_hit(rule, title):
    """
    Match one rule keyword against one OCR title without conflating quantity or rarity.

    Exact normalized equality always passes; otherwise require identical numeric
    tokens (so `初级经验书` never matches `初级经验书10个`), and allow at most
    one OCR character substitution on length >= 4 or one dropped character on
    length >= 5.
    """
    if not rule:
        return True
    w, n = exchange_norm(rule), exchange_norm(title)
    if not w or not n:
        return False
    if w == n:
        return True
    if re.findall(r'\d+', w) != re.findall(r'\d+', n):
        return False
    if len(w) == len(n) >= 4 and sum(a != b for a, b in zip(w, n)) == 1:
        return True
    if len(w) >= 5 and len(n) == len(w) - 1 and _is_subseq(n, w):
        return True
    return False


def exchange_parse_filter(raw):
    """
    Parse a sub-shop filter string into `(includes, excludes)`.

    Tokens separated by newlines or `>` / `＞` / `,` / `，`. Lines starting
    with `#` are comments; entries starting with `!` / `！` are exclusions.
    Returns `(includes, excludes)` where `includes` is `[(rank, token), ...]`.
    """
    raw_str = str(raw or '').strip()
    if not raw_str or raw_str == '不买':
        return [], []

    includes, excludes = [], []
    rank = 0
    for line in raw_str.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        for token in re.split(r'[>＞,，]', line):
            token = token.strip()
            if not token:
                continue
            if token == '不买':
                return [], []
            if token[0] in ('!', '！'):
                ex = token[1:].strip()
                if ex:
                    excludes.append(ex)
            elif token.lower() in ('全部', '*', 'all'):
                includes.append((rank, ''))
                rank += 1
            else:
                includes.append((rank, token))
                rank += 1

    if excludes and not includes:
        includes.append((0, ''))
    return includes, excludes


def exchange_match_rank(title, includes, excludes):
    """Return lowest matching rank in `includes`, or None if excluded/unmatched."""
    if any(exchange_keyword_hit(ex, title) for ex in excludes):
        return None
    for rank, inc in includes:
        if exchange_keyword_hit(inc, title):
            return rank
    return None


def exchange_has_blue_diamond(image, area, min_pixels=EXCHANGE_BLUE_CARD_MIN):
    """
    Detect blue diamond currency icons inside `area` on an RGB screenshot.

    In ALAS `device.image` is RGB (ch0=R, ch1=G, ch2=B), so diamond icons
    stand out sharply in `(b - r > 40) & (g - r > 15) & (b > 140)`.
    """
    patch = crop(image, np.array(area)).astype(int)
    if patch.size == 0:
        return False
    r, g, b = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
    blue_px = int(((b - r > 40) & (g - r > 15) & (b > 140)).sum())
    return blue_px >= min_pixels


def exchange_area_button(area, name='EXCHANGE_AREA'):
    """Build a click-only Button covering `area`."""
    return Button(area=area, color=(0, 0, 0),  # alas-lint: allow - click-only area computed by scan
                  button=area, name=name)
