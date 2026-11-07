"""Turn an existing game module back into page cards for dev_tools/spec_editor.html.

Writing cards from scratch is only worth it for a new game. For a game that is
already running, the knowledge is in the code: `page.py` says which button
identifies each page and which button leads where, `assets.py` says where every
element sits. This script reads those two and produces a spec the editor can
open, so the graph can be looked at instead of imagined.

Two things cannot be read out of the code, so they are recovered instead:

- The screenshot of a page. Candidate screenshots are matched against the page's
  check button and the best score wins; a page whose best score is below the
  threshold is left without a picture rather than given the wrong one.
- The steps of a page. They are scanned out of the task files with a deliberately
  narrow set of shapes (`appear_then_click`, `appear ... break`, `appear ...
  device.click`). Anything else is dropped: a wrong step in a card is worse than
  a missing one, because it looks like it was reviewed.

Usage:
    python -m dev_tools.spec_import hazeworld
    python -m dev_tools.spec_import hazeworld -o dev_tools/specs/hazeworld.spec.json
"""

import argparse
import base64
import io
import json
import os
import re

import numpy as np
from PIL import Image

from module.base.utils import crop, load_image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREEN = (1280, 720)

PAGE_DEF = re.compile(r'^(\w+) = Page\((.+)\)\s*$')
PAGE_LINK = re.compile(r'^(\w+)\.link\(button=(\w+), destination=(\w+)\)\s*$')
LINK_LOOP = re.compile(r'^for (\w+) in \[(.*?)\]:\s*$')
LINK_IN_LOOP = re.compile(r'^(\w+)\.link\(button=(\w+), destination=(\w+)\)\s*$')
ASSET_LINE = re.compile(
    r"^(\w+) = Button\(area=\{[^:]+: \(([\d, ]+)\)\}, color=\{[^:]+: \(([\d, ]+)\)\},"
    r" button=\{[^:]+: \(([\d, ]+)\)\}, file=\{[^:]+: '([^']+)'\}\)"
)


def parse_pages(path):
    """
    Read the page graph.

    Returns:
        tuple: (pages, links) where pages is name -> list of check buttons and
            links is a list of (source, button, destination).
    """
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()

    pages, links = {}, []
    loop_var, loop_pages = None, []
    collecting = None
    for line in lines:
        if collecting is not None:
            collecting.append(line.strip())
            if line.strip().endswith(']:'):
                text = ' '.join(collecting)
                m = re.match(r'for (\w+) in \[(.*)\]:', text)
                if m:
                    loop_var = m.group(1)
                    loop_pages = re.findall(r'page_\w+', m.group(2))
                collecting = None
            continue

        m = PAGE_DEF.match(line)
        if m:
            check = re.findall(r'[A-Z][A-Z0-9_]*', m.group(2))
            pages[m.group(1)] = check
            continue

        if re.match(r'^for (\w+) in \[', line) and not line.strip().endswith(']:'):
            collecting = [line.strip()]
            continue

        m = LINK_LOOP.match(line)
        if m:
            loop_var, loop_pages = m.group(1), re.findall(r'\w+', m.group(2))
            continue

        m = PAGE_LINK.match(line)
        if m:
            links.append((m.group(1), m.group(2), m.group(3)))
            continue

        m = LINK_IN_LOOP.match(line.strip())
        if m and loop_var and m.group(1) == loop_var:
            for page in loop_pages:
                links.append((page, m.group(2), m.group(3)))
            continue

    return pages, links


def parse_assets(path, namespace):
    """
    Read the generated asset table.

    Returns:
        dict: name -> dict(area, color, button, file)
    """
    assets = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            m = ASSET_LINE.match(line)
            if not m:
                continue
            assets[m.group(1)] = dict(
                area=tuple(int(v) for v in m.group(2).split(',')),
                color=tuple(int(v) for v in m.group(3).split(',')),
                button=tuple(int(v) for v in m.group(4).split(',')),
                file=m.group(5),
            )
    return assets


def guess_type(asset, root):
    """A flat block is meant to be read as a colour, anything else as a template."""
    path = os.path.join(root, asset['file'].replace('./', ''))
    if not os.path.isfile(path):
        return 'image'
    try:
        image = load_image(path)
        patch = crop(image, asset['area'], copy=False)
        return 'color' if float(np.std(patch)) < 10 else 'image'
    except Exception:
        return 'image'


def scan_steps(path, page_names):
    """
    Pull the obvious steps out of a task file.

    Only four shapes are recognised, and only while a `ui_ensure(page_x)` is the
    last thing that switched pages. Everything else — scrolling, OCR, arithmetic
    — is left out on purpose: it cannot be represented on a card, and a card
    that pretends to describe it is worse than one that stays quiet.

    Returns:
        dict: page name -> list of steps
    """
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()

    steps = {}
    page = None
    for i, line in enumerate(lines):
        m = re.search(r'self\.ui_ensure\((\w+)\)', line)
        if m and m.group(1) in page_names:
            page = m.group(1)
            continue
        if page is None:
            continue

        if 'wait_until_appear(' in line and steps.get(page):
            m = re.search(r'self\.wait_until_appear\((\w+)', line)
            if m:
                steps[page][-1]['then'] = 'popup'
                steps[page][-1]['popup'] = m.group(1)
            continue

        m = re.search(r'if self\.appear_then_click\((\w+)', line)
        if m:
            steps.setdefault(page, []).append(
                dict(when=m.group(1), action='click', then='stay', to='', max=0))
            continue

        m = re.search(r'if self\.image_color_count\((\w+)', line)
        if m:
            steps.setdefault(page, []).append(
                dict(when=m.group(1), action='click', then='stay', to='', max=0))
            continue

        m = re.search(r'if self\.appear\((\w+)', line)
        if m:
            window = lines[i:i + 4]
            if any('break' in w for w in window):
                steps.setdefault(page, []).append(
                    dict(when=m.group(1), action='none', then='stay', to='', max=0))
            else:
                for w in window:
                    n = re.search(r'self\.device\.click\((\w+)', w)
                    if n:
                        steps.setdefault(page, []).append(
                            dict(when=m.group(1), action='other', then='stay', to='', max=0,
                                 target=n.group(1)))
                        break
            continue

    return steps


def candidates(game, root):
    """Screenshots worth matching: the game's own folder first, then the newest root ones."""
    found = []
    own = os.path.join(root, 'screenshots', game)
    if os.path.isdir(own):
        found += [os.path.join(own, f) for f in sorted(os.listdir(own)) if f.endswith('.png')]

    shared = os.path.join(root, 'screenshots')
    if os.path.isdir(shared):
        files = [os.path.join(shared, f) for f in os.listdir(shared) if f.endswith('.png')]
        files.sort(key=os.path.getmtime, reverse=True)
        found += files[:400]
    return found


def match_shots(buttons, shots, threshold=0.85):
    """
    Find the screenshot each page was captured on.

    Each candidate is loaded once and scored against every page's check button,
    which is one pass over the folder instead of one pass per page: loading
    1280x720 PNGs is the expensive part, matching is not.

    A page whose best score stays under the threshold gets no picture at all: a
    wrong screenshot is worse than a black canvas, because every box is drawn on
    top of it and the whole card then reads as nonsense.

    Args:
        buttons (dict): page name -> Button.
        shots (list[str]): Candidate screenshots.
        threshold (float): Similarity to accept.

    Returns:
        dict: page name -> (path or None, best score)
    """
    best = {name: (None, 0.0) for name in buttons}
    for path in shots:
        try:
            image = load_image(path)
        except Exception:
            continue
        if image.shape[:2] != (SCREEN[1], SCREEN[0]):
            continue
        for name, button in buttons.items():
            try:
                score = _score(button, image)
            except Exception:
                continue
            if score > best[name][1]:
                best[name] = (path, score)
    return {name: (path if score >= threshold else None, score)
            for name, (path, score) in best.items()}


def _score(button, image):
    """Best match score of a button inside a screenshot, 0 when the area does not fit."""
    import cv2

    button.ensure_template()
    area = button.area
    window = crop(image, (max(0, area[0] - 20), max(0, area[1] - 20),
                          min(SCREEN[0], area[2] + 20), min(SCREEN[1], area[3] + 20)), copy=False)
    template = button.image
    if window.shape[0] < template.shape[0] or window.shape[1] < template.shape[1]:
        return 0.0
    res = cv2.matchTemplate(window, template, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(res)[1])


def compose(elements, assets, root):
    """
    Draw a stand-in screenshot out of the assets themselves.

    Most pages of a game in development have no screenshot lying around, but
    every element does: each asset is already a full screen with only its own
    region visible. Stacking them gives a dark canvas with the real elements at
    their real positions, which is enough to see the layout and place a box. It
    is marked as composed so nobody mistakes it for a capture.

    Args:
        elements (list[dict]): Card elements of one page.
        assets (dict): The asset table.
        root (str): Repository root.

    Returns:
        np.ndarray: RGB image.
    """
    canvas = np.full((SCREEN[1], SCREEN[0], 3), 26, np.uint8)
    for element in elements:
        asset = assets.get(element['name'])
        if not asset:
            continue
        path = os.path.join(root, asset['file'].replace('./', ''))
        if not os.path.isfile(path):
            continue
        try:
            image = load_image(path)
        except Exception:
            continue
        x1, y1, x2, y2 = asset['area']
        canvas[y1:y2, x1:x2] = image[y1:y2, x1:x2]
    return canvas


def encode(source):
    """Screenshot as a data URL, the same shape the editor exports."""
    if isinstance(source, np.ndarray):
        image = Image.fromarray(source)
    else:
        image = Image.open(source).convert('RGB')
    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


def build(game, root, namespace=None, with_shots=True):
    """Assemble the spec."""
    module = game
    namespace = namespace or game
    module_dir = os.path.join(root, 'module', module)

    pages, links = parse_pages(os.path.join(module_dir, 'page.py'))
    assets = parse_assets(os.path.join(module_dir, 'assets.py'), namespace)
    page_names = set(pages)

    steps = {}
    for name in sorted(os.listdir(module_dir)):
        if not name.endswith('.py'):
            continue
        if name in ('assets.py', 'page.py', f'{module}_ui.py', '__init__.py', 'utils.py'):
            continue
        steps.update(scan_steps(os.path.join(module_dir, name), page_names))

    shots = candidates(game, root) if with_shots else []
    print(f'pages {len(pages)}  links {len(links)}  assets {len(assets)}  shots {len(shots)}')

    buttons = {}
    if with_shots:
        for name, checks in pages.items():
            if checks and checks[0] in assets:
                buttons[name] = assets_button(checks[0], assets)
    found = match_shots(buttons, shots) if buttons else {}

    out = []
    for name, checks in pages.items():
        elements = []
        check = checks[0] if checks else ''
        for button in checks:
            if button in assets:
                elements.append(element(button, assets[button], root))
        for source, button, _ in links:
            if source == name and button in assets:
                if button not in [e['name'] for e in elements]:
                    elements.append(element(button, assets[button], root))
        for step in steps.get(name, []):
            for key in ('when', 'target', 'popup'):
                button = step.get(key)
                if button and button in assets and button not in [e['name'] for e in elements]:
                    elements.append(element(button, assets[button], root))

        exits = [dict(button=b, to=d) for s, b, d in links if s == name]
        shot, score = found.get(name, (None, 0.0))
        kind = 'real'
        if not shot:
            shot = compose(elements, assets, root)
            kind = 'composed'
        print(f'  {name:22s} elements={len(elements):2d} steps={len(steps.get(name, [])):2d} '
              f'{"真截图" if kind == "real" else "素材拼图"} {score:.2f}')

        out.append(dict(
            title=name.replace('page_', ''),
            name=name,
            check=check,
            shot=encode(shot) if shot is not None else '',
            shot_kind=kind,
            elements=elements,
            steps=dedupe(steps.get(name, [])),
            exits=exits,
            delay='server_update',
            note='',
        ))

    return dict(game=game, namespace=namespace, module=module,
                task='', task_title='', pages=out)


def element(name, asset, root):
    """One card element from one asset line."""
    area, click = asset['area'], asset['button']
    pad = max(0, area[0] - click[0], area[1] - click[1], click[2] - area[2], click[3] - area[3])
    return dict(name=name, box=list(area), type=guess_type(asset, root), pad=pad, stable=1, text='')


def assets_button(name, assets):
    """A Button object without importing the generated module (avoids namespace side effects)."""
    from module.base.button import Button

    asset = assets[name]
    return Button(area=asset['area'], color=asset['color'], button=asset['button'],
                  file=asset['file'], name=name)


def dedupe(steps):
    """
    Drop repeated steps, keeping the first.

    The scanner walks the source linearly, so a branch that is written twice
    (once for the first run, once for the retry) shows up twice. On a card that
    is noise: the state loop tries every row on every frame anyway.

    Returns:
        list[dict]: Steps in source order, first occurrence only.
    """
    seen, out = set(), []
    for step in steps:
        key = (step.get('when'), step.get('action'), step.get('target', ''))
        if key in seen:
            continue
        seen.add(key)
        out.append(clean_step(step))
    return out


def clean_step(step):
    """Keep the keys the editor reads, so an imported step and a typed one look the same."""
    return dict(
        when=step.get('when', ''),
        action=step.get('action', 'click'),
        target=step.get('target', ''),
        then=step.get('then', 'stay'),
        popup=step.get('popup', ''),
        to=step.get('to', ''),
        max=step.get('max', 0),
    )


def main():
    parser = argparse.ArgumentParser(description='Import a game module as page cards.')
    parser.add_argument('game', help='module folder name, e.g. hazeworld')
    parser.add_argument('-o', '--output', default=None)
    parser.add_argument('--no-shots', action='store_true', help='skip screenshot matching')
    parser.add_argument('--root', default=ROOT)
    args = parser.parse_args()

    spec = build(args.game, args.root, with_shots=not args.no_shots)

    output = args.output or os.path.join(args.root, 'dev_tools', 'specs', f'{args.game}.spec.json')
    folder = os.path.dirname(output)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(output, 'w', encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False)

    size = os.path.getsize(output) / 1024 / 1024
    print(f'\nwritten {output}  ({size:.1f} MB, {len(spec["pages"])} pages)')
    print('open it in dev_tools/spec_editor.html with 导入 spec')


if __name__ == '__main__':
    main()
