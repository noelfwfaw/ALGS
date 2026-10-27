"""Print the names on the character page, so they can be typed into the config.

Scrolls the grid from top to bottom and reads the name of every card. The names
are what `LostswordAffection` matches against, and the in-game spelling is the
one that works.

Usage:
    ./toolkit/python.exe -m dev_tools.lostsword_list_characters
    ./toolkit/python.exe -m dev_tools.lostsword_list_characters --screens 4
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import module.config.server as server
from module.base.button import Button
from module.config.config import AlasConfig
from module.device.device import Device
from module.logger import logger
from module.ocr.ocr import Ocr

PACKAGE = 'com.wemadeconnect.aos.lostdgl'
COLUMNS = (289, 489, 689, 889, 1089)
NAME_Y = (266, 511)
NAME_WIDTH = 145
NAME_HEIGHT = 17


def read_name(image, area):
    button = Button(area=area, color=(0, 0, 0), button=area, name='NAME')
    ocr = Ocr(button, lang='cnocr', letter=(255, 255, 255), threshold=170,
              name='CHAR_NAME')
    text = ocr.ocr(image)
    return re.sub(r'[^\u4e00-\u9fa5]', '', str(text))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--screens', type=int, default=2,
                        help='How many screens to scroll through')
    args = parser.parse_args()

    config = AlasConfig('alas', task='LostswordAffection')
    device = Device(config=config)
    server.set_server('lostsword')
    device.package = PACKAGE

    from module.lostsword.lostsword_ui import LostswordUI, page_character, page_main
    ui = LostswordUI(config=config, device=device)
    ui.ui_ensure(page_main)
    ui.ui_ensure(page_character)

    seen = []
    for screen in range(args.screens):
        device.stuck_record_clear()
        device.screenshot()
        image = device.image
        names = []
        for name_y in NAME_Y:
            row = []
            for x1 in COLUMNS:
                area = (x1, name_y, x1 + NAME_WIDTH, name_y + NAME_HEIGHT)
                row.append(read_name(image, area))
            names.append(row)
        for row in names:
            for name in row:
                # A one character read is scrap: the third row of the grid is
                # half drawn, and the scroll lands between rows.
                if len(name) > 1 and name not in seen:
                    seen.append(name)
            print('  '.join(n or '------------' for n in row))
        if screen < args.screens - 1:
            device.swipe(p1=(640, 620), p2=(640, 220))
            device.sleep(1.5)

    print()
    print(f'--- {len(seen)} name(s) ---')
    for i, name in enumerate(seen, 1):
        print(f'{i:2d}. {name}')
    logger.info('Copy the names above into LostswordAffection.Name1 .. Name6')


if __name__ == '__main__':
    main()
