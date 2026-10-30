"""
Match matrix of a game's assets against a folder of screenshots.

Purpose: catch asset mistakes *before* they become "页面明明在那儿却报
Game page unknown". It reports the real similarity number of every asset on
every screenshot, so you can see:

- 目标页命中、其他页不命中       -> 这块素材可用
- 全都不命中                     -> 素材图有问题（区域错、被压缩过、不是 1280x720）
- 很多张都命中                   -> 误匹配，检测点选得太"通用"（大片纯色、通用图标）
- 色差很大                       -> 别用 appear(x, offset=None) 做颜色判定

Usage:
    python -m dev_tools.asset_check --module hazeworld --shots screenshots/asset_check

Screenshots should be named after the page they show, e.g.
    screenshots/asset_check/page_main.png
    screenshots/asset_check/page_room_sending.png

The `--expect` option takes "asset=page" pairs (comma separated) and turns the
matrix into a pass/fail check:
    --expect MAIN_ICON_MAIL=page_main,MAIN_ICON_ROOM=page_main

One asset may belong to several screenshots of the same page (a clean lobby and
the same lobby with a dialog), which is why the page side takes alternatives
separated by `|`:
    --expect "MAIN_MENU_STORY=主界面|主界面-对话"
"""
import argparse
import importlib
import os

import cv2
import numpy as np

from module.base.button import Button
from module.base.template import Template
from module.base.utils import crop, get_color, load_image
import module.config.server as server

IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')


def list_shots(folder):
    """
    Args:
        folder (str):

    Returns:
        list[tuple[str, str]]: [(page name, file path), ...]
    """
    shots = []
    for file in sorted(os.listdir(folder)):
        name, ext = os.path.splitext(file)
        if ext.lower() in IMAGE_EXT:
            shots.append((name, os.path.join(folder, file)))
    return shots


def collect_assets(module_name):
    """
    Args:
        module_name (str): e.g. 'hazeworld' -> module.hazeworld.assets

    Returns:
        list[tuple[str, Button or Template]]: Sorted by name.
    """
    module = importlib.import_module(f'module.{module_name}.assets')
    assets = []
    for name in dir(module):
        if name.startswith('_'):
            continue
        value = getattr(module, name)
        if isinstance(value, (Button, Template)):
            assets.append((name, value))
    assets.sort(key=lambda item: item[0])
    return assets


def button_similarity(button, image, offset=20):
    """
    Same search window as Button.match(): area +/- offset.

    Args:
        button (Button):
        image (np.ndarray): RGB screenshot.
        offset (int, tuple): 20 or (20, 20).

    Returns:
        float: 0~1

    Raises:
        ValueError: template bigger than the search window.
    """
    button.ensure_template()
    if isinstance(offset, tuple):
        x, y = offset
    else:
        x, y = offset, offset
    area = button.area
    region = crop(image, (area[0] - x, area[1] - y, area[2] + x, area[3] + y), copy=False)
    template = button.image
    if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        raise ValueError(f'area={button.area} is out of the screenshot')
    res = cv2.matchTemplate(template, region, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(res)[1])


def template_similarity(template, image):
    """
    Full screen search, same as Template.match().

    Args:
        template (Template):
        image (np.ndarray): RGB screenshot.

    Returns:
        float: 0~1
    """
    image_template = template.image
    if image_template.shape[0] > image.shape[0] or image_template.shape[1] > image.shape[1]:
        raise ValueError(f'template size {image_template.shape[:2]} is bigger than the screenshot')
    res = cv2.matchTemplate(image, image_template, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(res)[1])


def color_distance(button, image):
    """
    Distance used by Button.appear_on() (color only, no template).

    Args:
        button (Button):
        image (np.ndarray):

    Returns:
        int: Max channel difference, 0 means identical.
    """
    expect = button.color
    actual = get_color(image, button.area)
    return int(np.abs(np.array(expect) - np.array(actual)).max())


def print_matrix(assets, shots, matrix, threshold, cells_width=6, block=16):
    """
    Args:
        assets (list[tuple[str, object]]):
        shots (list[tuple[str, str]]):
        matrix (dict): {(asset name, shot name): similarity}
        threshold (float):
        cells_width (int): Width of one cell.
        block (int): Columns per block, the matrix is split to stay readable.
    """
    print('Screenshots')
    for index, (page, _) in enumerate(shots):
        print(f'  {index + 1:>2}. {page}')

    for start in range(0, len(shots), block):
        chunk = shots[start:start + block]
        header = ' ' * 34 + ''.join(str(start + i + 1).rjust(cells_width) for i in range(len(chunk)))
        print()
        print(header)
        print('-' * len(header))
        for name, _ in assets:
            row = ''.join(f'{matrix[(name, page)]:{cells_width}.2f}' for page, _ in chunk)
            print(f'{name[:33]:<34}{row}')

    print('-' * (34 + cells_width * min(len(shots), block)))
    print(f'similarity > {threshold} counts as hit (Button.match default 0.85)')

    # Row summary
    print()
    for name, _ in assets:
        hits = [page for page, _ in shots if matrix[(name, page)] > threshold]
        if not hits:
            print(f'[never hit]  {name}: 这批截图里一次都没命中，素材图或 area 可能有问题')
        elif len(shots) <= 8 and len(hits) > 2:
            print(f'[too common] {name}: 命中 {len(hits)}/{len(shots)} 张 -- {", ".join(hits[:6])}')


def check_expect(assets, shots, matrix, expect, threshold):
    """
    Args:
        expect (dict[str, list[str]]): asset name -> pages it may appear on. More
            than one entry means "this page has several states" (a clean lobby
            and the same lobby with a dialog), not "matches anywhere".

    Returns:
        int: Failed count.
    """
    names = {name for name, _ in assets}
    pages = {page for page, _ in shots}
    failed = 0
    print()
    print('Expectation check')
    for asset, wanted in expect.items():
        if asset not in names:
            print(f'  FAIL {asset}: 素材不存在于 assets.py')
            failed += 1
            continue
        missing = [page for page in wanted if page not in pages]
        if missing:
            print(f'  FAIL {asset}: 截图里没有名为 {"、".join(missing)} 的页面')
            failed += 1
            continue
        own = max(matrix[(asset, page)] for page in wanted)
        others = max([matrix[(asset, p)] for p in pages if p not in wanted], default=0)
        label = '|'.join(wanted)
        if own > threshold and others < threshold:
            print(f'  OK   {asset}: {label} {own:.3f} / 其他最高 {others:.3f}')
        else:
            failed += 1
            if own <= threshold:
                print(f'  FAIL {asset}: 在 {label} 上只有 {own:.3f}，识别不出来')
            else:
                print(f'  FAIL {asset}: 在别的页面也命中（最高 {others:.3f}），会误匹配')
    return failed


def main():
    parser = argparse.ArgumentParser(description='Check game assets against screenshots')
    parser.add_argument('--module', default='hazeworld', help='module package name, e.g. hazeworld')
    parser.add_argument('--namespace', default=None, help='asset namespace, default = module')
    parser.add_argument('--shots', default='screenshots/asset_check', help='folder of screenshots')
    parser.add_argument('--offset', type=int, default=20, help='search offset of Button.match')
    parser.add_argument('--threshold', type=float, default=0.85, help='similarity that counts as hit')
    parser.add_argument('--only', default=None, help='only check assets whose name contains this')
    parser.add_argument('--expect', default=None, help='asset=page,asset=page')
    parser.add_argument('--csv', default=None, help='write the matrix to a csv file')
    args = parser.parse_args()

    if args.namespace is None:
        args.namespace = args.module
    if args.namespace not in server.VALID_SERVER:
        print(f'[warn] "{args.namespace}" is not in VALID_SERVER={server.VALID_SERVER}, '
              f'assets will be read from the wrong namespace')
    else:
        server.set_server(args.namespace)

    if not os.path.isdir(args.shots):
        print(f'screenshot folder not found: {args.shots}')
        print('Put screenshots named after their page there, e.g. page_main.png')
        return 1

    shots = list_shots(args.shots)
    if not shots:
        print(f'no image in {args.shots}')
        return 1

    assets = collect_assets(args.module)
    if args.only:
        assets = [item for item in assets if args.only in item[0]]
    if not assets:
        print('no asset found, run dev_tools.button_extract first')
        return 1

    print(f'namespace: {args.namespace}')
    print(f'assets: {len(assets)}, screenshots: {len(shots)}')
    print()

    matrix = {}
    color = {}
    for page, file in shots:
        image = load_image(file)
        if image.shape[0:2] != (720, 1280):
            print(f'[warn] {file} is {image.shape[1]}x{image.shape[0]}, expected 1280x720')

        for name, asset in assets:
            try:
                if isinstance(asset, Template):
                    sim = template_similarity(asset, image)
                else:
                    sim = button_similarity(asset, image, offset=args.offset)
                    color[(name, page)] = color_distance(asset, image)
            except Exception as e:
                sim = 0.0
                print(f'[warn] {name} @ {page}: {e}')
            matrix[(name, page)] = sim

    print_matrix(assets, shots, matrix, args.threshold)

    # Color check: which assets would fail appear(x, offset=None)
    print()
    print('Color check (assumes the shot where the asset matches best)')
    bad = 0
    for name, asset in assets:
        if isinstance(asset, Template):
            continue
        best_page = max((p for p, _ in shots), key=lambda p: matrix[(name, p)])
        if matrix[(name, best_page)] <= args.threshold:
            continue
        diff = color[(name, best_page)]
        if diff > 10:
            bad += 1
            print(f'  [color] {name}: 色差 {diff} @ {best_page} -- '
                  f'appear(x, offset=None) 会失败，用带 offset 的匹配或 wait_until_settled()')
    if not bad:
        print('  all matched assets pass the color check')

    if args.csv:
        with open(args.csv, 'w', encoding='utf-8-sig') as f:
            f.write('asset,' + ','.join(page for page, _ in shots) + '\n')
            for name, _ in assets:
                f.write(name + ',' + ','.join(f'{matrix[(name, page)]:.3f}' for page, _ in shots) + '\n')
        print(f'\ncsv written to {args.csv}')

    failed = 0
    if args.expect:
        expect = {}
        for item in args.expect.split(','):
            if not item.strip():
                continue
            asset, _, page = item.partition('=')
            expect[asset.strip()] = [x.strip() for x in page.split('|') if x.strip()]
        failed = check_expect(assets, shots, matrix, expect, args.threshold)
        print()
        print('PASS' if failed == 0 else f'{failed} check(s) failed')

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
