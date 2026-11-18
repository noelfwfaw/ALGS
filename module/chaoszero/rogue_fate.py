# -*- coding: utf-8 -*-
"""Identify the standard Chaos Zero fate cards by their title glyphs."""

import re
from functools import lru_cache
from pathlib import Path
from random import choice

import cv2
import numpy as np

from module.chaoszero.rogue_cards import normalize


TITLE_AREAS = ((268, 378, 376, 410), (588, 378, 696, 410), (904, 378, 1012, 410))
CORE_NAMES = frozenset('熱情 啟迪 開朗 共情 勤勞 嫉妒 專注 支配 缺乏 擁有'.split())
TITLE_ALIASES = str.maketrans('启灵响窃盗应爱领导战贪坚韧热开劳专拥註', '啟靈響竊盜應愛領導戰貪堅韌熱開勞專擁注')


@lru_cache(maxsize=1)
def title_templates():
    with np.load(str(Path(__file__).with_name('rogue_fate_titles.npz'))) as bank:
        return {name: bank[name] for name in bank.files}


def read_titles(image, reader):
    patches = [image[y1:y2, x1:x2].min(axis=2) for x1, y1, x2, y2 in TITLE_AREAS]
    # The reveal can leave individual plaques blank or fully white.
    if any(not 80 <= np.count_nonzero(patch > 145) <= 700 for patch in patches):
        return None
    titles = []
    for patch, area in zip(patches, TITLE_AREAS):
        scores = sorted(
            (cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED).max(), name)
            for name, template in title_templates().items()
        )
        best, title = scores[-1]
        if best < .80 or best - scores[-2][0] < .09:
            title = reader.read_name(image, area, scale=1.6).translate(TITLE_ALIASES)
        titles.append(title)
    return titles


def phase(titles, core_started):
    known = set(titles).intersection(title_templates())
    if known and known <= CORE_NAMES:
        return 'core'
    if known and not known.intersection(CORE_NAMES):
        return 'main'
    return 'core' if core_started else 'main'


def pick(titles, priorities):
    for line in (priorities or '').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        for part in re.split(r'[>＞]+', stripped):
            name = normalize(part).translate(TITLE_ALIASES)
            if name and name in titles:
                return titles.index(name) + 1, True
    return choice(range(1, len(titles) + 1)), False
