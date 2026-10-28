"""Probe the summon entry's red dot on the live screen, and only that.

The task decided "no free pull today" in 34 ms on the first real run, which is
either a correct answer or a false negative that silently disables the whole
feature. The two are told apart by looking at the numbers, so this prints the
mean colour of the dot's area next to the colour it is compared against, and
saves both the full screen and an 8x crop of the area for the eye.

`--entries` goes one step further: it presses the two positions the badge scan
derives and reports which pool came up, which is the only way to check the click
points and the pool names without spending a pull. Nothing in this probe presses
「召唤1次」, so it cannot take a free pull even by mistake.

Usage:
    ./toolkit/python.exe -m dev_tools.probe_summon_dot
    ./toolkit/python.exe -m dev_tools.probe_summon_dot --entries
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image

from algs import AlGS
from module.config.config import Function
from module.config.server import set_server, to_package
from module.logger import logger

TASK = 'LostswordSummon'
OUT = os.path.join('log', 'probe')


def to_pil(image):
    """The fork hands screenshots out as ndarrays; upstream hands out PIL."""
    return image if isinstance(image, Image.Image) else Image.fromarray(image)


def mean_color(image, area):
    arr = np.array(to_pil(image).crop(area)).reshape(-1, 3).astype('float64')
    return tuple(int(round(v)) for v in arr.mean(axis=0))


def match_similarity(button, image, offset):
    """`Button.match`'s score, without its threshold. Copied from `button.py`."""
    import cv2

    from module.base.utils import crop

    button.ensure_template()
    if isinstance(offset, tuple):
        offset = np.array((-offset[0], -offset[1], offset[0], offset[1]))
    else:
        offset = np.array((-3, -offset, 3, offset))
    image = crop(image, offset + button.area, copy=False)
    res = cv2.matchTemplate(button.image, image, cv2.TM_CCOEFF_NORMED)
    _, sim, _, point = cv2.minMaxLoc(res)
    return sim


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--point', action='append', default=[],
                        help='x,y to press and report the pool it opened, repeatable')
    args = parser.parse_args()

    algs = AlGS()
    game = algs.task_game(TASK)
    config = algs.config
    config.overridden['Emulator_PackageName'] = to_package(game)
    config.task = Function(config.data[TASK])
    config.bind(TASK)
    set_server(game)
    algs.game = game
    algs.device.package = to_package(game)
    algs.game_in_foreground = True

    # Imported here, not at the top: the asset modules resolve their namespace
    # and read their file at import time, and the default namespace belongs to
    # the other game until `set_server` runs.
    import module.lostsword.assets as assets
    from module.lostsword.lostsword_ui import page_summon
    from module.lostsword.summon import LostswordSummon

    os.makedirs(OUT, exist_ok=True)

    ui = LostswordSummon(config, task=TASK)
    ui.device = algs.device

    logger.hr('Probe', level=1)
    ui.device.screenshot()
    image = ui.device.image
    logger.attr('Current page', ui.ui_get_current_page().check_button.name)

    to_pil(image).save(os.path.join(OUT, 'screen.png'))

    for name, offset in (('SUMMON_DOT', (10, 10)),
                         ('MAIN_BTN_SUMMON', (10, 10)),
                         ('SUMMON_FREE', (10, 10)),
                         ('SUMMON_POOL_CHAR', (30, 30)),
                         ('SUMMON_POOL_PET', (30, 30))):
        button = getattr(assets, name)
        area = button.area
        mean = mean_color(image, area)
        color = button.color
        diff = max(abs(a - b) for a, b in zip(mean, color))
        sim = match_similarity(button, image, offset)
        crop = to_pil(image).crop(area)
        crop.resize((crop.width * 4, crop.height * 4), Image.NEAREST).save(
            os.path.join(OUT, f'{name}.png'))
        logger.attr(name, f'area={area} expect={color} now={mean} color_diff={diff} '
                          f'color_pass={diff <= 10} sim={sim:.3f} '
                          f'offset_pass={sim > 0.85}')

    logger.info(f'Saved to {OUT}')

    for item in args.point:
        x, y = (int(v) for v in item.split(','))
        logger.hr(f'Press ({x}, {y})', level=2)
        # Same order as the task: the list is dragged to its end before any
        # entry is pressed, and the cards are only where the last measurement
        # put them in that state.
        ui.ui_goto(page_summon)
        ui.summon_scroll_to_pools()
        logger.attr('Marked entries', ui.summon_marked_entries())
        pool = ui.summon_open_pool((x, y))
        logger.attr('Pool opened', pool)

    if args.point:
        logger.hr('Back to main', level=2)
        ui.ui_goto_main()
        logger.attr('Current page', ui.ui_get_current_page().check_button.name)


if __name__ == '__main__':
    main()
