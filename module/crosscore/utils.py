"""Shared helpers of 交错战线 (Cross Core)."""

import cv2
import numpy as np

from module.base.utils import crop
from module.logger import logger


def find_all(image, template, region, similarity=0.85, distance=20):
    """Find every occurrence of a template inside a region.

    `Button.match()` returns only the best match, which is not enough for the
    order library: the same 构建订单 can be in any of the eight cards, and the
    facility list repeats the same 驻员预设 icon once per row.

    Args:
        image (np.ndarray): Screenshot, 1280x720.
        template (np.ndarray): Template, such as `Button.image`.
        region (tuple): Search area (x1, y1, x2, y2).
        similarity (float): Threshold of TM_CCOEFF_NORMED.
        distance (int): Peaks closer than this are the same occurrence.

    Returns:
        list[tuple[int, int]]: Top-left corner of each occurrence, top to bottom.
    """
    x1, y1, x2, y2 = region
    search = crop(image, region)
    if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
        logger.warning(f'Search region {region} is smaller than the template')
        return []

    result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(result >= similarity)
    points = sorted((int(x), int(y)) for x, y in zip(xs, ys))

    found = []
    for x, y in points:
        if all(abs(x - px) > distance or abs(y - py) > distance for px, py in found):
            found.append((x, y))

    found.sort(key=lambda p: p[1])
    return [(x1 + x, y1 + y) for x, y in found]


def template_of(button):
    """Template image of a Button, loaded on its first use.

    `Button.image` is None until `appear()` or `match()` has run once. The
    multi-target scans below skip `match()` on purpose, so they have to ask for
    the template explicitly or `cv2.matchTemplate` gets None.
    """
    button.ensure_template()
    return button.image


def image_diff(image1, image2):
    """Mean absolute difference of two crops, used to tell pages apart."""
    return float(np.mean(cv2.absdiff(image1, image2)))


def has_template(image, template, region, similarity=0.85):
    """Whether the template is anywhere in the region."""
    return bool(find_all(image, template, region, similarity=similarity, distance=5))
