# -*- coding: utf-8 -*-
"""
在真机上验证一条链：每帧告诉你每个模板得了多少分，默认不点击。

为什么需要它：生成出来的任务要跑一整轮才知道哪一步认错了，一轮 40 分钟，而且
日志里只有"点了"没有"看到什么"。这里反过来——先把每一帧的分数打出来，看一眼
就知道是模板不行、还是 offset 不够、还是这一页根本还没有那个东西。

    python -m dev_tools.spec_live spec.json                # 只看，不动手
    python -m dev_tools.spec_live spec.json --click        # 真点
    python -m dev_tools.spec_live spec.json --step         # 每帧等回车，一步步看
    python -m dev_tools.spec_live spec.json --frames 30    # 跑 30 帧
    python -m dev_tools.spec_live spec.json --save         # 每帧存图到 log/spec_live

输出长这样：

    帧 12   0.41s
      0.981  E_2_1      模板  (463,526) -> 点 (480,440)   <- 会点
      0.712  E_1_1      模板  (639,629)
      0.403  E_3_1      模板  (633,466)

    占比 5.3%  E_5_1  常驻键区间 2.0%~45.0%   <- 会点

最后给一张汇总表：每个模板在这么多帧里的最高分、最低分、命中几帧。最高分都上不去
的模板，就是框错了或者素材不对，不用等整轮跑完。
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dev_tools.spec_build import (SCREEN, _grey, _template_hit, chain_steps,
                                  decode_shot, order_chain, parse_point)
from module.base.utils import save_image

ADB = os.path.join(ROOT, 'toolkit', 'Lib', 'site-packages', 'adbutils', 'binaries', 'adb.exe')
SHOT_DIR = os.path.join(ROOT, 'log', 'spec_live')
THRESHOLD = 0.85


def connect(serial):
    """adb server 会被沙箱回收，每条命令前都要重连一次。"""
    if not os.path.isfile(ADB):
        raise SystemExit(f'找不到 adb：{ADB}')
    subprocess.run([ADB, 'connect', serial], stdout=subprocess.PIPE,
                   stderr=subprocess.DEVNULL, timeout=20)


def capture(serial, timeout=12):
    """
    截一帧，返回 RGB 数组；失败返回 None。

    `exec-out screencap -p` 偶尔会吐半截 PNG（模拟器卡一下、和别的 adb 命令撞车），
    PIL 直接抛异常会把循环打死，所以这里只返回 None，由调用方重试。
    """
    try:
        proc = subprocess.run([ADB, '-s', serial, 'exec-out', 'screencap', '-p'],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    if len(proc.stdout) < 1024:
        return None
    try:
        image = Image.open(io.BytesIO(proc.stdout)).convert('RGB')
    except Exception:
        return None
    return np.array(image)


def tap(serial, x, y):
    subprocess.run([ADB, '-s', serial, 'shell', 'input', 'tap', str(int(x)), str(int(y))],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)


def ratio_of(shot, box, threshold=200, bright=True):
    """这块区域里亮（或暗）像素占多少，和生成的 ink_ratio 是同一套算法。"""
    x1, y1, x2, y2 = [int(v) for v in box]
    patch = shot[y1:y2, x1:x2].astype(np.int32)
    if patch.size == 0:
        return 0.0
    grey = patch[:, :, 0] * 0.299 + patch[:, :, 1] * 0.587 + patch[:, :, 2] * 0.114
    hit = grey > threshold if bright else grey < threshold
    return float(hit.mean())


def collect(spec, offset):
    """
    把链条模板准备出来。

    模板从 spec 自己内嵌的截图裁，和 `spec_build` 生成素材是同一条路 —— 这样
    "生成器认为的模板"和"这里测的模板"是同一个东西，测出来的分数才有意义。

    Returns:
        tuple: (list of (name, template or None, box, element), notes)
    """
    element_shot = {}
    for page in spec['pages']:
        if not page.get('shot'):
            continue
        for element in page['elements']:
            element_shot.setdefault(element['name'], page['shot'])

    chain = chain_steps(spec)
    chain, notes = order_chain(chain, spec, offset)

    items, missing = [], []
    for name, step, element in chain:
        box = [int(v) for v in element['box']]
        raw = element_shot.get(element['name'])
        if raw is None:
            missing.append(name)
            continue
        image = _grey(decode_shot(raw))
        patch = image[box[1]:box[3], box[0]:box[2]]
        if patch.size == 0:
            missing.append(name)
            continue
        items.append((name, patch, box, element))
    if missing:
        notes.append('这些元素在 spec 里找不到截图，跳过: ' + ', '.join(missing))
    return items, notes


def point_of(element):
    """这一行点在哪：优先 tap，其次框中心。"""
    if element.get('tap'):
        return parse_point(element['tap'])
    box = element['box']
    return (int(box[0]) + int(box[2])) // 2, (int(box[1]) + int(box[3])) // 2


def describe(element):
    box = [int(v) for v in element['box']]
    centre = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    text = f'模板  ({centre[0]},{centre[1]})'
    if element.get('tap'):
        text += f' -> 点 {element["tap"]}'
    return text


def main():
    parser = argparse.ArgumentParser(description='在真机上验证一条链，默认不点击。')
    parser.add_argument('spec', help='spec.json')
    parser.add_argument('--serial', default='127.0.0.1:16640', help='adb 地址，默认 127.0.0.1:16640')
    parser.add_argument('--click', action='store_true', help='真的点下去（默认只看）')
    parser.add_argument('--step', action='store_true', help='每帧停下等回车')
    parser.add_argument('--frames', type=int, default=10, help='看多少帧，默认 10')
    parser.add_argument('--save', action='store_true', help='每帧存图到 log/spec_live')
    parser.add_argument('--top', type=int, default=5, help='每帧打印前几名，默认 5')
    args = parser.parse_args()

    with open(args.spec, encoding='utf-8') as f:
        spec = json.load(f)

    offset = int(spec.get('chain_offset') or 60)
    items, notes = collect(spec, offset)

    print(f'spec      {args.spec}')
    print(f'链条      {len(items)} 个模板，offset={offset}，阈值 {THRESHOLD}')
    print(f'模式      {"真点击" if args.click else "只看，不点击"}'
          f'{"" if not args.step else "，每帧等回车"}')
    for note in notes:
        print(f'  ! {note}')
    print('')

    if not items:
        raise SystemExit('链条是空的：这张 spec 里没有可点的步骤。')

    connect(args.serial)
    shot = capture(args.serial)
    if shot is None:
        raise SystemExit(f'截不到图。先确认模拟器开着、`adb connect {args.serial}` 能连上。')
    if shot.shape[:2] != (SCREEN[1], SCREEN[0]):
        raise SystemExit(f'截图是 {shot.shape[1]}x{shot.shape[0]}，需要 {SCREEN[0]}x{SCREEN[1]}。')

    stats = {name: {'best': 0.0, 'worst': 1.0, 'hits': 0,
                    'ratio': element.get('type') == 'ratio'}
             for name, _, _, element in items}
    failures = 0

    for frame in range(1, args.frames + 1):
        started = time.time()
        if frame > 1 or shot is None:
            shot = capture(args.serial)
        if shot is None:
            failures += 1
            print(f'帧 {frame}  截图失败，跳过')
            if failures >= 3:
                raise SystemExit('连续 3 帧截不到图，先检查 adb。')
            continue
        failures = 0

        grey = _grey(shot)
        rows = []
        for name, template, box, element in items:
            if element.get('type') == 'ratio':
                bright = element.get('ink') != 'dark'
                value = ratio_of(shot, box, 200 if bright else 55, bright)
                low = float(element.get('ratio_lo', 0.02))
                high = float(element.get('ratio_hi', 0.45))
                hit = low <= value <= high
                rows.append((value, name, element, hit, 'ratio', (low, high)))
            else:
                value = _template_hit(template, grey, box, offset)
                rows.append((value, name, element, value >= THRESHOLD, 'tpl', None))
            row = stats[name]
            row['best'] = max(row['best'], value)
            row['worst'] = min(row['worst'], value)
            if rows[-1][3]:
                row['hits'] += 1

        # ratio 的分数和模板分不能直接比大小，分开排
        templates = sorted([r for r in rows if r[4] == 'tpl'], key=lambda r: -r[0])
        ratios = [r for r in rows if r[4] == 'ratio']
        winner = next((r for r in templates if r[3]), None) or \
                 next((r for r in ratios if r[3]), None)

        print(f'帧 {frame:<3d} 匹配 {time.time() - started:.2f}s  '
              f'命中 {sum(1 for r in rows if r[3])} 个')
        for value, name, element, hit, kind, extra in templates[:args.top]:
            mark = '  <- 会点' if (winner and name == winner[1]) else ''
            print(f'  {value:.3f}  {name:10s} {describe(element)}{mark}')
        for value, name, element, hit, kind, extra in ratios:
            low, high = extra
            mark = '  <- 会点' if (winner and name == winner[1]) else ''
            print(f'  占比 {value * 100:5.1f}%  {name:10s} 常驻键区间 {low * 100:.1f}%~{high * 100:.1f}%'
                  f'{"  在" if hit else "  不在"}{mark}')

        if args.save:
            if not os.path.isdir(SHOT_DIR):
                os.makedirs(SHOT_DIR)
            save_image(shot, os.path.join(SHOT_DIR, f'frame_{frame:04d}.png'))

        if winner and args.click:
            x, y = point_of(winner[2])
            tap(args.serial, x, y)
            print(f'  点了 ({x},{y})')
            time.sleep(0.4)
            shot = None          # 下一步重新截，别拿旧的判断

        if args.step:
            command = input('  回车继续，q 退出 > ').strip().lower()
            if command == 'q':
                break
        print('')

    print('=== 汇总（每个模板在这些帧里的表现）===')
    print('  模板        最高分   最低分   命中帧')
    plain = [i for i in items if not stats[i[0]]['ratio']]
    for name, _, _, _ in sorted(plain, key=lambda i: -stats[i[0]]['best']):
        row = stats[name]
        flag = '' if row['best'] >= THRESHOLD else '   <- 最高分都不够：模板框错、或这一页还没到'
        print(f'  {name:10s}  {row["best"]:.3f}   {row["worst"]:.3f}   {row["hits"]:3d}{flag}')

    resident = [i for i in items if stats[i[0]]['ratio']]
    if resident:
        print('')
        print('  常驻键        占比最高   占比最低   落在区间')
        for name, _, _, element in resident:
            row = stats[name]
            low = float(element.get('ratio_lo', 0.02)) * 100
            high = float(element.get('ratio_hi', 0.45)) * 100
            print(f'  {name:10s}  {row["best"] * 100:6.1f}%   {row["worst"] * 100:6.1f}%'
                  f'   {row["hits"]:3d} 帧   （区间 {low:.1f}%~{high:.1f}%）')


if __name__ == '__main__':
    main()
