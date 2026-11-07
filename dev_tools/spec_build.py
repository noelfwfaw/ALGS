"""Build ALAS source files from a page-card spec written in spec_editor.html.

The editor is the human side: one card per page, elements drawn as boxes on a
screenshot, steps written in order. This script is the machine side: it turns a
card into the four things a task actually needs.

    assets/<namespace>/<module>/<NAME>.png   full screen, black elsewhere
    module/<module>/assets.py                Button entries, sorted, idempotent
    module/<module>/page.py                  Page(...) + link(...) block
    module/<module>/<task>.py                run() skeleton with the steps

Nothing is written unless --write is given; the default prints what would
change, so a spec can be reviewed before it touches the repository.

Usage:
    python -m dev_tools.spec_build dev_tools/specs/mail.spec.json
    python -m dev_tools.spec_build dev_tools/specs/mail.spec.json --write
"""

import argparse
import base64
import io
import json
import os
import re

import cv2
import numpy as np
from PIL import Image

from module.base.utils import get_bbox, get_color, save_image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCREEN = (1280, 720)

# 模板灰度标准差的两个门槛，见 flat_contrast()。
FLAT_DEAD = 2.0
FLAT_WEAK = 8.0

# Assignment lines of a generated assets.py, e.g. `MAIL_TITLE = Button(area=...`.
ASSIGN = re.compile(r'^([A-Z][A-Z0-9_]*) = (Button|Template)\(')

PAGE_BEGIN = '# >>> spec_editor pages'
PAGE_END = '# <<< spec_editor pages'

# 常驻按钮（SKIP / 跳过 / 关闭）的判据，见 ink_ratio()。
RATIO_HELPER = '''

def ink_ratio(image, area, threshold=200, bright=True):
    """
    How much of an area is ink.

    A resident button — SKIP, 跳过, a close cross — keeps its shape but not its
    backdrop, and a template match is dragged around by that backdrop: the same
    icon scores 0.99 on a dark screen and 0.16 on a bright one, because
    TM_CCOEFF_NORMED compares structure and the background is part of the
    picture. Counting how many pixels are stroke-coloured only looks at the
    stroke: the hole shows whatever is behind it and is simply not counted.

    The range matters in both directions. A lower bound rejects "nothing here",
    an upper bound rejects a plain white screen that has no button on it at all.

    Args:
        image (np.ndarray): Screenshot.
        area (tuple): x1, y1, x2, y2 in screen coordinates.
        threshold (int): Brightness above (or below) which a pixel is ink.
        bright (bool): Count bright ink; False counts dark ink.

    Returns:
        float: Share of the area covered by ink, 0.0 to 1.0.
    """
    patch = crop(image, area)
    gray = patch[:, :, 0] * 0.299 + patch[:, :, 1] * 0.587 + patch[:, :, 2] * 0.114
    hit = gray > threshold if bright else gray < threshold
    return float(hit.mean())

'''



def snake(name):
    """CamelCase or spaced text to snake_case."""
    name = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name or '')
    name = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', name)
    name = re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_').lower()
    return name or 'generated_task'


def pascal(name):
    """Game folder name to its UI class prefix, e.g. hazeworld -> Hazeworld."""
    parts = re.split(r'[^A-Za-z0-9]+', name or '')
    return ''.join(p[:1].upper() + p[1:].lower() for p in parts if p) or 'Game'


def upper(name):
    """
    Element name to a Python identifier.

    Users name elements after the page they sit on (`1_1`, `23_1`), which is a
    fine label and an illegal identifier: the leading digit makes `1_1 = Button(
    ...)` a syntax error. Such a name gets an `E_` prefix instead of being
    rejected, so a card never has to be re-typed for the sake of the generator.
    """
    ident = re.sub(r'[^A-Z0-9_]', '_', (name or '').upper())
    if ident and not ident[0].isalpha() and ident[0] != '_':
        ident = 'E_' + ident
    return ident


def decode_shot(data_url):
    """Decode the screenshot embedded in the spec, as RGB."""
    if not data_url:
        raise ValueError('page has no screenshot')
    if ',' in data_url:
        data_url = data_url.split(',', 1)[1]
    image = Image.open(io.BytesIO(base64.b64decode(data_url))).convert('RGB')
    if image.size != SCREEN:
        raise ValueError(f'screenshot is {image.size}, expected {SCREEN}')
    return np.array(image)


def element_asset(shot, box, pad=0, tap=None):
    """
    Turn a drawn box into the asset the framework expects.

    An ALAS asset is a full 1280x720 image that is black everywhere except the
    region of interest: `button_extract` derives `area` from the bounding box of
    the non-black content and `color` from the mean of that box. Drawing the
    same shape here keeps a later regeneration byte-identical instead of
    silently moving the area to the drawn box.

    `area` and `button` are separate fields because the thing that proves where
    you are is often not the thing you press: "添加其他账号" is stable text and
    makes a good check, while the account above it is what has to be clicked and
    its name changes on every account. So the check stays on the text and the
    press moves to `tap`.

    Args:
        shot (np.ndarray): Screenshot the box was drawn on.
        box (list[int]): x1, y1, x2, y2 as drawn.
        pad (int): How far the clickable area extends past the drawn box.
        tap (tuple[int, int] | None): Where to press, if not the box itself.

    Returns:
        tuple: (full screen image, area, color, click area)
    """
    x1, y1, x2, y2 = [int(v) for v in box]
    full = np.zeros((SCREEN[1], SCREEN[0], 3), dtype=np.uint8)
    full[y1:y2, x1:x2] = shot[y1:y2, x1:x2]

    area = get_bbox(full)
    color = tuple(int(round(v)) for v in get_color(full, area))
    if tap:
        cx, cy = [int(v) for v in tap]
        cx = min(max(cx, 6), SCREEN[0] - 6)
        cy = min(max(cy, 6), SCREEN[1] - 6)
        click = (cx - 6, cy - 6, cx + 6, cy + 6)
    else:
        click = (
            max(0, area[0] - pad), max(0, area[1] - pad),
            min(SCREEN[0], area[2] + pad), min(SCREEN[1], area[3] + pad),
        )
    return full, tuple(int(v) for v in area), color, click


def flat_contrast(shot, box):
    """
    Standard deviation of a box's brightness.

    A patch with no variation is not a picture of anything: `TM_CCOEFF_NORMED`
    divides by the template's own deviation, so a flat patch scores 1.000 at
    every location on every screen. A card that boxes empty background by
    mistake therefore yields a button that is always on screen — the task
    presses it on every frame and never advances, which reads as "it is stuck"
    or "it is clicking at random".

    Two thresholds, because they mean different things: under `FLAT_DEAD` the
    patch is a single colour and the template is worthless; under `FLAT_WEAK`
    it is nearly flat and will produce false positives on dark backgrounds.

    Args:
        shot (np.ndarray): Screenshot the box was drawn on.
        box (list[int]): x1, y1, x2, y2.

    Returns:
        float: Standard deviation of the patch's grey value.
    """
    x1, y1, x2, y2 = [int(v) for v in box]
    patch = shot[y1:y2, x1:x2].astype(np.int32)
    if patch.size == 0:
        return 0.0
    gray = patch[:, :, 0] * 0.299 + patch[:, :, 1] * 0.587 + patch[:, :, 2] * 0.114
    return float(gray.std())


def measure_ink(shot, box, mode='light'):
    """
    Measure the stroke colour of a hollow icon and how many pixels it covers.

    A hollow icon has no colour of its own where it is cut out: the hole shows
    whatever is behind it, so both a mean-colour check and a whole-box template
    drift with the background. What does not drift is the stroke, and the number
    of stroke pixels in the box, which is what `image_color_count()` counts.

    Args:
        shot (np.ndarray): Screenshot the box was drawn on.
        box (list[int]): x1, y1, x2, y2.
        mode (str): 'light' for a bright stroke, 'dark' for a dark one.

    Returns:
        tuple: (rgb of the stroke, pixels of stroke in the box)
    """
    x1, y1, x2, y2 = [int(v) for v in box]
    patch = shot[y1:y2, x1:x2].astype(np.int32)
    if patch.size == 0:
        return (255, 255, 255), 0

    gray = patch[:, :, 0] * 0.299 + patch[:, :, 1] * 0.587 + patch[:, :, 2] * 0.114
    threshold = np.percentile(gray, 5 if mode == 'dark' else 95)
    mask = gray <= threshold if mode == 'dark' else gray >= threshold
    if not mask.any():
        return (255, 255, 255), int(patch.shape[0] * patch.shape[1])

    color = tuple(int(round(v)) for v in patch[mask].mean(axis=0))
    return color, int(mask.sum())


def guard(name, element):
    """
    The condition that decides "this element is on screen".

    Four kinds of element need four different judgements: a template survives a
    fade, a flat colour block is recognised by its colour, a hollow icon has no
    stable colour in its hole at all so it is counted by stroke pixels, and a
    resident button on a changing backdrop is judged by the share of pixels that
    are ink rather than by where the ink sits.
    """
    if element.get('type') == 'ratio':
        low = float(element.get('ratio_lo', 0.02))
        high = float(element.get('ratio_hi', 0.45))
        bright = element.get('ink') != 'dark'
        return (f'{low} <= ink_ratio(self.device.image, {name}_AREA, '
                f'threshold={200 if bright else 55}, bright={bright}) <= {high}')
    if element.get('type') == 'hollow':
        color = tuple(element.get('ink_color') or (255, 255, 255))
        count = max(10, int((element.get('ink_count') or 0) * 0.5))
        return f'self.image_color_count({name}, color={color}, threshold=60, count={count})'
    offset = 'None' if element.get('type') == 'color' else '(20, 20)'
    return f'self.appear({name}, offset={offset})'


def button_line(name, area, color, click, namespace, module):
    """One `NAME = Button(...)` line, in the same shape button_extract writes."""
    return (
        f'{name} = Button(area={{{namespace!r}: {area}}}, '
        f'color={{{namespace!r}: {color}}}, '
        f'button={{{namespace!r}: {click}}}, '
        f'file={{{namespace!r}: {make_path(namespace, module, name)!r}}})'
    )


def make_path(namespace, module, name):
    """Asset path as stored in assets.py, relative to the repository root."""
    return f'./assets/{namespace}/{module}/{name}.png'


def insert_assets(path, entries):
    """
    Insert new `NAME = Button(...)` lines into a generated assets.py.

    The file is sorted by name and regenerated by dev_tools/button_extract.py,
    so a line is inserted at its alphabetical place instead of appended: an
    appended line would be reordered by the next regeneration and show up as a
    spurious diff. Existing names are never rewritten; a mismatch is reported
    and left for a human.

    Args:
        path (str): Path to assets.py.
        entries (list[tuple]): (name, line, area) to add.

    Returns:
        tuple: (new file content, added names, skipped names, conflicts)
    """
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()

    index = {}
    last = -1
    for i, line in enumerate(lines):
        m = ASSIGN.match(line)
        if m:
            index[m.group(1)] = i
            last = i

    added, skipped, conflicts = [], [], []
    for name, line, area in entries:
        if name in index:
            skipped.append(name)
            old = re.search(r'area=\{[^:]+: (\([^)]*\))', lines[index[name]])
            if old and old.group(1) != str(area):
                conflicts.append(f'{name}: 旧 {old.group(1)} / 新 {area}')
            continue

        at = None
        for i, line_i in enumerate(lines):
            m = ASSIGN.match(line_i)
            if m and m.group(1) > name:
                at = i
                break
        if at is None:
            # Nothing to sort against: an empty table has only its header, and
            # inserting at 0 would put the entry above the imports it needs.
            at = last + 1 if last >= 0 else len(lines)
        lines.insert(at, line)
        last += 1
        added.append(name)

    return '\n'.join(lines) + '\n', added, skipped, conflicts


def wrap_import(head, names, width=100):
    """
    One import statement, wrapped when the name list gets long.

    A card with sixty elements produces a single 500-character line, which no
    editor shows without scrolling and no diff reads.
    """
    one = head + ', '.join(names)
    if len(one) <= width:
        return one
    pad = '    '
    lines, line = [], ''
    for name in names:
        piece = name + ', '
        if line and len(head) + len(line) + len(piece) > width:
            lines.append(line.rstrip())
            line = ''
        line += piece
    if line:
        lines.append(line.rstrip().rstrip(','))
    body = ('\n' + pad).join(lines)
    return f'{head}(\n{pad}{body}\n)'


def page_exits(page):
    """
    Every link of a page, as (button, destination).

    A page may have many: the main screen's menu has one entry per destination,
    and they all look the same once the menu is open. That is fine here — a link
    is not "what to click when you see it", it is "the button that leads to that
    page", and `ui_goto` only presses the one on the way to where it is going.

    Specs written before `exits` existed carry a single `exit`; both are read.
    """
    exits = page.get('exits')
    if not exits:
        legacy = page.get('exit') or {}
        exits = [legacy] if legacy.get('button') else []
    return [(e.get('button'), e.get('to') or 'page_main') for e in exits if e.get('button')]


def render_page_block(spec, elements):
    """
    Build the `page.py` block: one Page per card, one link per exit.

    A page object takes its variable name from the source line it was created
    on (`Page.__init__` reads it back with traceback), so every declaration has
    to stay on a single line. The block is delimited so a rebuild replaces it
    instead of appending a second copy.

    Args:
        spec (dict): The whole spec.
        elements (dict): Element name -> (area, ...) of every page.

    Returns:
        str: The block, ready to replace the old one.
    """
    namespace = spec['namespace']
    module = spec.get('module') or spec['game']

    names = []
    for page in spec['pages']:
        check = upper(page.get('check') or '')
        if check:
            names.append(check)
        for button, _ in page_exits(page):
            names.append(upper(button))
    names = sorted(set(n for n in names if n))

    lines = [PAGE_BEGIN]
    lines.append('# Generated from the page-card spec by dev_tools/spec_build.py.')
    lines.append('# Edit the spec, not this block; a rebuild replaces it entirely.')
    lines.append('# Pages are checked in declaration order, so these come after the')
    lines.append('# hand-written ones; move the block up if a generated page overlaps.')
    if names:
        imports = ', '.join(names) if len(names) > 1 else names[0]
        lines.append(f'from module.{module}.assets import {imports}  # noqa: E402')
    for page in spec['pages']:
        check = upper(page.get('check') or '')
        if not check:
            lines.append(f'# TODO: {page.get("name")} has no check element, skipped')
            continue
        lines.append(f'{page["name"]} = Page({check})')
    declared = {page['name'] for page in spec['pages'] if page.get('check')}
    for page in spec['pages']:
        for button, destination in page_exits(page):
            if destination not in declared:
                # A link to a page that has no check button would reference a
                # name that is never defined, so it is dropped and reported.
                lines.append(f'# skipped {page["name"]}.link({button} -> {destination}): 目标页没有判据')
                continue
            lines.append(f'{page["name"]}.link(button={upper(button)}, destination={destination})')
    lines.append(PAGE_END)
    return '\n'.join(lines)


def parse_point(text):
    """Parse "x,y" from a card into two ints, clamped to the screen."""
    x, y = 640, 360
    try:
        a, b = str(text or '').split(',')
        x, y = int(float(a)), int(float(b))
    except (ValueError, TypeError):
        pass
    x = min(max(x, 6), SCREEN[0] - 6)
    y = min(max(y, 6), SCREEN[1] - 6)
    return x, y


def collect_taps(pages):
    """Every point any card presses, in a stable order."""
    seen = []
    for page in pages:
        for step in page['steps']:
            if step.get('action') == 'tap':
                point = parse_point(step.get('target'))
                if point not in seen:
                    seen.append(point)
    return seen


def func_name(page):
    """
    Method name for one card's loop.

    A page may be called `page_23` — this user numbers the tutorial pages — and
    stripping the prefix would leave `23_loop`, which is not an identifier.
    """
    base = re.sub(r'^page_', '', page['name'] or 'page')
    base = re.sub(r'[^0-9A-Za-z_]', '_', base)
    if not base or base[0].isdigit():
        base = 'p' + base
    return base + '_loop'


def label(page):
    """Page variable name to the English label used in logs, e.g. task_claim."""
    return page['name'].replace('page_', '').replace('_', ' ')


def chain_steps(spec):
    """
    The presses a chain spec describes, in card order.

    It reads each step's `when`, not the page's `check`, because the two answer
    different questions: `check` is "how do I know I am on this page" and is
    usually a line of title text, `when` is "what do I press". page_2 spells it
    out — check is 2_1 (131x28, text) and the press is 2_2 (47x37, a button).

    Returns:
        list[tuple[str, dict, dict]]: (asset name, step, element) per press.
    """
    chain, skipped = [], []
    for page in spec['pages']:
        for step in page.get('steps') or []:
            if step.get('action') == 'none':
                continue
            name = upper(step.get('when') or '')
            if not name:
                continue
            if step.get('action') not in (None, '', 'click', 'type'):
                # "press another element" and "press a point" need two names
                # per entry, which the chain does not carry. Left out and
                # reported rather than silently pressed in the wrong place.
                skipped.append(f'{page["name"]}:{step["when"]}')
                continue
            element = next((e for e in page['elements'] if e['name'] == step['when']), {})
            chain.append((name, step, element))
    if skipped:
        print('  链式模式只支持「点它」，这些行被略过: ' + ', '.join(skipped))
    return chain


def _grey(image):
    """Brightness of an RGB image, as uint8 for cv2."""
    grey = image[:, :, 0] * 0.299 + image[:, :, 1] * 0.587 + image[:, :, 2] * 0.114
    return grey.astype(np.uint8)


def _template_hit(template, shot, box, offset):
    """Whether `template` is found near `box` in `shot`, scored 0..1."""
    x1, y1, x2, y2 = box
    search = shot[max(0, y1 - offset):min(SCREEN[1], y2 + offset),
                  max(0, x1 - offset):min(SCREEN[0], x2 + offset)]
    if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
        return 0.0
    result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
    return float(result.max()) if result.size else 0.0


def order_chain(chain, spec, offset=60, threshold=0.85):
    """
    Sort the chain so the most specific check wins, and report what it beats.

    In a tutorial only one button is usually on screen, so the order looks
    irrelevant — until two are. Touch to Start stays readable in the blurred
    backdrop of the account dialog, scores 0.85+ there, and if it sits first in
    the chain the dialog gets a press aimed at a spot behind it, which closes
    the dialog instead of picking an account.

    So the chain is ordered by how few *other* cards each check matches: a check
    that only ever appears on its own card goes first, a generic one like
    "tap to start" goes last. Order only decides who wins when two match at the
    same time, so reordering cannot break a step that has to happen first —
    that is what `seg` (segments) is for.

    Args:
        chain (list[tuple[str, dict, dict]]): (name, step, element) per press.
        spec (dict): The spec, for its screenshots.
        offset (int): Match offset, same as the generated code uses.
        threshold (float): Score that counts as a hit.

    Returns:
        tuple: (ordered chain, list[str] of notes worth printing).
    """
    shots = {}
    for page in spec['pages']:
        if page.get('shot'):
            shots[page['name']] = _grey(decode_shot(page['shot']))
    if len(shots) < 2:
        return chain, []

    templates = {}
    for name, _, element in chain:
        box = element.get('box')
        if not box or name in templates:
            continue
        # The check is `area`, derived from the drawn box; the screenshot the
        # box was drawn on is the one that contains it.
        owner = next(p['name'] for p in spec['pages']
                     if p.get('shot') and any(e['name'] == element['name'] for e in p['elements']))
        image = shots.get(owner)
        if image is None:
            continue
        x1, y1, x2, y2 = [int(v) for v in box]
        patch = image[y1:y2, x1:x2]
        if patch.size:
            templates[name] = (patch, box, owner)

    collisions = []
    for name, (template, box, owner) in templates.items():
        others = [page for page in shots if page != owner
                  and _template_hit(template, shots[page], box, offset) >= threshold]
        collisions.append((len(others), name, others))

    weight = {name: count for count, name, _ in collisions}
    ordered = sorted(chain, key=lambda item: weight.get(item[0], 99))

    notes = []
    for count, name, others in collisions:
        if not count:
            continue
        beaten = [item[0] for item in chain
                  if item[0] != name and weight.get(item[0], 99) > count]
        if not beaten:
            continue
        notes.append(f'{name}（在 {count} 张别的截图上也能认出来）排在 '
                     f'{", ".join(beaten[:4])} 前面 —— 否则那些画面会被它抢先点掉')
    return ordered, notes


def render_chain(spec):
    """
    Build a task that walks the whole tutorial in one loop.

    The card-per-page model needs every page to have a check button and an end
    condition, which a tutorial never has: 62 cards, 59 presses, zero end
    conditions means 59 loops that each burn their 30s timeout, pressing the
    same spot every 3 seconds after the screen has already moved on. A chain
    has neither pages nor navigation — it presses whatever it recognises and
    stops when the screen goes quiet.

    Args:
        spec (dict): The whole spec, with `chain` set.

    Returns:
        str: Contents of the task file.
    """
    game = spec['game']
    module = spec.get('module') or game
    task = spec.get('task') or 'GeneratedTask'
    ui = pascal(game) + 'UI'
    title = spec.get('task_title') or spec.get('taskTitle') or task
    offset = int(spec.get('chain_offset') or 60)
    chain = chain_steps(spec)
    chain, notes = order_chain(chain, spec, offset)
    for note in notes:
        print(f'  链条顺序  {note}')

    # 常驻打断键（ratio 类型）单独一组：它们一直在屏幕上，混进链条会把后面的
    # 每一步都抢掉，所以放在链条前面每帧判一次，点一次就冷却。
    guide = [(name, step, el) for name, step, el in chain if el.get('type') != 'ratio']
    resident = [(name, el) for name, _, el in chain
                if el.get('type') == 'ratio' and el.get('box')]

    typed = [(name, (step.get('text') or '').strip()) for name, step, _ in chain
             if step.get('action') == 'type']
    typed = [(name, content) for name, content in typed if content]

    names = sorted({name for name, _, _ in chain})

    lines = [
        f'"""{task}: {title} - built from the page-card spec by dev_tools/spec_build.py.',
        '',
        'Chain:',
        f'    {len(guide)} presses in card order, one loop for the whole tutorial.',
        f'    {len(resident)} resident keys checked before every frame of the chain.',
        '    Regenerate with dev_tools/spec_build.py; edit the cards, not this file.',
        '"""',
        '',
    ]
    lines.extend(wrap_import(f'from module.{module}.assets import ', names).splitlines())
    lines.append('from module.base.timer import Timer')
    if resident:
        lines.append('from module.base.utils import crop')
    lines.extend([
        f'from module.{module}.{module}_ui import {ui}',
        'from module.logger import logger',
        '',
        '',
        '# 允许按钮偏离框选位置多少像素。引导气泡的位置会变，所以不能按固定坐标点；',
        '# 但开得越大越慢：64 个模板全屏扫一遍要 1 秒，外扩 60 像素只要 50 毫秒。',
        f'CHAIN_OFFSET = {offset}',
        '',
    ])
    for name, el in resident:
        lines.append(f'{name}_AREA = {tuple(int(v) for v in el["box"])}')
    if resident:
        lines.extend([
            '',
            '# 常驻键点一次之后歇多久。点完到画面变化之间有一段延迟，不冷却就会连着点',
            '# 好几下，把刚弹出来的确认窗顺手点掉，然后又回到同一个键上，死循环。',
            'INTERRUPT_COOLDOWN = 2',
            '',
        ])
    # Always emitted, even when empty: the loop body reads it unconditionally,
    # and a name that only exists on some cards is a NameError waiting for the
    # first task that does not need to type anything.
    lines.extend([
        '# 需要往里打字的按钮：{Button: 内容}。其余按钮都只点一下。',
        '# `input text` 只认 ASCII，所以内容只能是英文和数字。',
        'TEXT_INPUT = {',
    ])
    for name, content in typed:
        lines.append(f'    {name}: {content!r},')
    lines.extend([
        '}',
        '',
    ])
    lines.extend([
        '# 按卡片顺序。顺序就是优先级：两个按钮同时出现时，点上面的那个。',
        'GUIDE_CHAIN = (',
    ])
    for name, _, _ in guide:
        lines.append(f'    {name},')
    lines.extend([
        ')',
        '',
    ])
    if resident:
        lines.extend([
            '# 常驻键：不属于链条的某一步，每帧单独判一次。',
            'INTERRUPTS = (',
        ])
        for name, _ in resident:
            lines.append(f'    {name},')
        lines.extend([
            ')',
            '',
            '',
        ])
    if resident:
        lines.append(RATIO_HELPER.strip('\n'))
        lines.append('')
    lines.extend([
        '',
        f'class {task}({ui}):',
        f'    """{title}."""',
        '',
        '    def __init__(self, *args, **kwargs):',
        '        super().__init__(*args, **kwargs)',
        '        # 常驻键的冷却表，key 是 button.name',
        '        self._cool = {}',
        '',
        '    def run(self):',
        '        """',
        '        Pages:',
        '            in: any',
        '            out: page_main',
        '        """',
        f"        logger.hr('{title}', level=1)",
        '        self.guide_chain()',
    ])

    delay = (spec['pages'][0] or {}).get('delay') if spec['pages'] else 'server_update'
    if delay == 'once':
        lines.append('        self.config.Scheduler_Enable = False')
        lines.append("        self.config.task_stop('done once')")
    elif delay == 'half_day':
        lines.append('        self.config.task_delay(minute=720)')
    elif delay == 'day':
        lines.append('        self.config.task_delay(minute=1440)')
    elif delay == 'retry':
        lines.extend([
            '        # 刷到目标为止：这一轮没成，1 分钟后再排一次。',
            '        # TODO: 达成目标时改成下面两行，而且两行都要——',
            '        #       只 task_stop() 会让 NextRun 停在过去，立刻又刷一轮。',
            '        #       self.config.Scheduler_Enable = False',
            "        #       self.config.task_stop('goal reached')",
            '        self.config.task_delay(minute=1)',
        ])
    else:
        lines.append('        self.config.task_delay(server_update=True)')

    if resident:
        lines.extend([
            '',
            '    def _interrupt(self):',
            '        """',
            '        点一下常驻打断键，点到了返回 True。',
            '',
            '        它们不属于引导链的某一步：会一直待在屏幕上，混进链里会把后面每一步',
            '        都抢掉。冷却是因为点完到画面变化之间有一段延迟，不冷却就会连着点，',
            '        把刚弹出来的确认窗顺手点掉，然后又回到同一个键上。',
            '',
            '        Returns:',
            '            bool: True if one was pressed this frame.',
            '        """',
            '        for button in INTERRUPTS:',
            '            if button.name in self._cool and not self._cool[button.name].reached():',
            '                continue',
        ])
        for name, el in resident:
            lines.extend([
                f'            if button is {name}:',
                f'                if not ({guard(name, el)}):',
                '                    continue',
            ])
        lines.extend([
            '            self.device.click(button)   # alas-lint: allow R13 判据是上面的'
            ' ink_ratio，不是 appear，lint 认不出这种守卫',
            '            self._cool[button.name] = Timer(INTERRUPT_COOLDOWN).start()',
            '            return True',
            '        return False',
            '',
        ])
    else:
        lines.extend([
            '',
            '    def _interrupt(self):',
            '        """没有常驻键要处理，这条链纯靠模板。"""',
            '        return False',
            '',
        ])

    lines.extend([
        '',
        '    def guide_chain(self, timeout=900, idle=20, idle_start=60):',
        '        """',
        "        Press the tutorial's buttons one after another.",
        '',
        '        Every frame tries the whole chain and presses the first button on',
        '        screen. Doing it this way — instead of "wait for step N, then step',
        '        N+1" — is what keeps a dropped frame or a re-entered tutorial from',
        '        derailing the run: whatever is on screen gets pressed, and the order',
        '        of the chain only decides who wins when two buttons are up at once.',
        '',
        '        A press is not finished until the same button leaves the screen.',
        '        Without that wait the next frame matches the same button again and',
        '        presses it a second time — for a dialog that means opening it and',
        '        closing it on the next tick, forever.',
        '',
        '        The chain ends when nothing has matched for `idle` seconds: a',
        '        tutorial with no button left has nothing more to press. Raise',
        '        `idle` if the flow has a fight or a cutscene longer than that.',
        '',
        '        Args:',
        '            timeout (int): Give up after this many seconds.',
        '            idle (int): Seconds without a match before the chain is done.',
        '            idle_start (int): Same, but before the first button is found. A',
        '                cold start spends 30-60s on logos and loading where nothing',
        '                matches; with the short budget the chain would call it done',
        '                while the game is still booting. Tightened automatically on',
        '                the first hit, so a finished tutorial does not wait for it.',
        '',
        '        Returns:',
        '            bool: True if the chain went quiet on its own, False on timeout.',
        '        """',
        '        quiet = Timer(idle_start).start()',
        '        started = False',
        '        # 点过却不消失的按钮，说明它不是「推进型」的：SKIP、返回、关闭都在此列。',
        '        # 记次数、两次之后跳过，免得整个链条卡在它身上空转。',
        '        stubborn = {}',
        '        typed = set()',
        '        for _ in self.loop(timeout=timeout):',
        '            # 常驻键排在最前：它会盖住引导，而且一直都在',
        '            if self._interrupt():',
        '                quiet.reset()',
        '                if not started:',
        '                    started = True',
        '                    quiet.limit = idle',
        '                continue',
        '            for button in GUIDE_CHAIN:',
        '                if stubborn.get(button.name, 0) >= 2:',
        '                    continue',
        '                if button.name in typed:',
        '                    continue',
        '                if self.appear(button, offset=CHAIN_OFFSET):',
        '                    self.device.click(button)',
        '                    content = TEXT_INPUT.get(button.name)',
        '                    if content:',
        '                        self.device.adb_shell([\'input\', \'text\', content])',
        '                        typed.add(button.name)',
        '                        quiet.reset()',
        '                        if not started:',
        '                            started = True',
        '                            quiet.limit = idle',
        '                        break',
        '                    quiet.reset()',
        '                    if not started:',
        '                        started = True',
        '                        quiet.limit = idle',
        '                    # 等它从画面上消失：没了才说明这一步真的生效了。',
        '                    gone = self.wait_until_disappear(button, offset=CHAIN_OFFSET,',
        '                                                     timeout=4, settle=2)',
        '                    if gone:',
        '                        stubborn.pop(button.name, None)',
        '                    else:',
        '                        stubborn[button.name] = stubborn.get(button.name, 0) + 1',
        '                        if stubborn[button.name] >= 2:',
        "                            logger.warning(f'{button.name} 点了两次都没消失，跳过它')",
        '                    break',
        '            else:',
        '                if quiet.reached():',
        '                    logger.info(f\'Guide chain: nothing for {idle}s, done\')',
        '                    return True',
        '',
        '        logger.warning(f\'Guide chain: still pressing after {timeout}s\')',
        '        return False',
    ])
    return '\n'.join(lines) + '\n'


def render_task(spec):
    """
    Build the task skeleton.

    Only the skeleton: order, checks, intervals, OCR bounds and the schedule
    come from the card, while anything that needs a real decision (a price
    comparison, a reroll verdict) is left as a TODO next to the sentence the
    human wrote.
    """
    module = spec.get('module') or spec['game']
    task = spec.get('task') or 'GeneratedTask'
    ui = pascal(spec['game']) + 'UI'
    # A page without a check button cannot be declared in page.py, so it must
    # not appear in run() either: the name would not exist at import time.
    pages = [page for page in spec['pages'] if page.get('check')]

    used, digits, areas, kinds = [], [], [], set()
    for page in pages:
        for e in page['elements']:
            used.append(upper(e['name']))
            kinds.add(e['type'])
            if e['type'] == 'digit':
                digits.append(upper(e['name']))
            if e['type'] in ('text', 'digit', 'ratio'):
                areas.append((upper(e['name']), tuple(int(v) for v in e['box'])))
        if page.get('check'):
            used.append(upper(page['check']))
        for button, _ in page_exits(page):
            used.append(upper(button))
    # A popup or a click target may live on another card, and the generated code
    # still needs its name imported — asset constants are module level, but only
    # if the import line mentions them.
    for page in pages:
        for step in page.get('steps') or []:
            for key in ('popup', 'target'):
                value = step.get(key)
                if value and ',' not in str(value):
                    used.append(upper(value))
    used = sorted(set(n for n in used if n))

    taps = collect_taps(pages)
    title = spec.get('task_title') or spec.get('taskTitle') or ''
    # 弹窗元素可能在别的页面上，offset 要按它自己的类型算，所以查表要跨页
    all_elements = {e['name']: e for page in pages for e in page['elements']}

    out = [
        f'"""{task}: {title + " - " if title else ""}built from the page-card spec by dev_tools/spec_build.py.',
        '',
        'Cards:',
    ]
    for page in pages:
        out.append(f'    {page["name"]} - {page.get("title") or ""}')
    out.extend([
        '',
        'Pages:',
        '    in: page_main',
        '    out: page_main',
        '"""',
        '',
    ])

    imports = [wrap_import(f'from module.{module}.assets import ', used)]
    if len(pages) == 1:
        imports.append(f'from module.{module}.page import {pages[0]["name"]}')
    elif pages:
        imports.append(wrap_import(f'from module.{module}.page import ',
                                   [p['name'] for p in pages]))
    imports.append(f'from module.{module}.{module}_ui import {ui}')
    imports.append('from module.logger import logger')
    if taps:
        imports.append('from module.base.button import Button')
    if 'text' in kinds:
        imports.append('from module.coupon.text import read_text')
    if digits:
        imports.append('from module.ocr.ocr import Digit')
    if 'ratio' in kinds:
        imports.append('from module.base.utils import crop')
    out.extend(sorted(imports))
    out.append('')

    for x, y in taps:
        name = f'TAP_{x}_{y}'
        out.append(f'{name} = Button(area=({x - 6}, {y - 6}, {x + 6}, {y + 6}), color=(0, 0, 0),')
        out.append(f'{" " * 21}button=({x - 6}, {y - 6}, {x + 6}, {y + 6}), name={name!r})')
    for name, _ in areas:
        if name in digits:
            out.append(f'{name}_DIGIT = Digit({name})')
        else:
            out.append(f'{name}_AREA = {dict(areas)[name]}')
    if taps or areas:
        out.append('')
    out.append('')
    if 'ratio' in kinds:
        out.append(RATIO_HELPER.strip('\n'))
        out.append('')

    first = label(pages[0]).capitalize() if pages else task
    out.append(f'class {task}({ui}):')
    out.append(f'    """{first}."""')
    out.append('')
    out.append('    def run(self):')
    out.append('        """')
    out.append('        Pages:')
    out.append('            in: page_main')
    out.append('            out: page_main')
    out.append('        """')
    out.append(f"        logger.hr('{first}', level=1)")
    for page in pages:
        body = [f"self.ui_ensure({page['name']})", f"self.{func_name(page)}()"]
        repeat = int(page.get('repeat') or 1)
        if repeat > 1:
            out.append(f'        for _ in range({repeat}):')
            out.extend(f'            {line}' for line in body)
        else:
            for line in body:
                out.append(f'        {line}')
    out.append('        self.ui_goto_main()')

    delay = pages[-1].get('delay') if pages else 'server_update'
    if delay == 'once':
        out.append('        # 只做一次：关掉自己再结束。只 task_stop() 是不够的，')
        out.append('        # NextRun 还停在过去，调度器下一轮立刻又会捡回来。')
        out.append('        self.config.Scheduler_Enable = False')
        out.append("        self.config.task_stop('done once')")
    elif delay == 'retry':
        out.append('        # 刷到目标为止：这一轮没成，1 分钟后再排一次。')
        out.append('        # TODO: 达成目标时改成下面两行，而且两行都要——')
        out.append('        #       只 task_stop() 会让 NextRun 停在过去，立刻又刷一轮。')
        out.append('        #       self.config.Scheduler_Enable = False')
        out.append("        #       self.config.task_stop('goal reached')")
        out.append('        self.config.task_delay(minute=1)')
    elif delay == 'half_day':
        out.append('        self.config.task_delay(minute=720)')
    elif delay == 'day':
        out.append('        self.config.task_delay(minute=1440)')
    else:
        out.append('        self.config.task_delay(server_update=True)')

    for page in pages:
        out.append('')
        out.extend(render_page_loop(page, all_elements))

    return '\n'.join(out) + '\n'


def split_segments(steps):
    """
    Cut a card's steps into segments.

    A step may be marked `seg`, which starts a new segment. Segments are run in
    order and never overlap: the first one has to finish before the second one
    is even looked at. That is the only way to say "this button may not be
    pressed before that tutorial is over" — row order alone cannot, because a
    state loop re-reads every row on every frame and only uses the order to
    decide who wins when two rows match at the same time.

    Returns:
        list[list[dict]]: Steps grouped by segment, in source order.
    """
    groups, current = [], []
    for step in steps:
        if step.get('seg') and current:
            groups.append(current)
            current = []
        current.append(step)
    if current:
        groups.append(current)
    return groups


def render_page_loop(page, all_elements=None):
    """
    One state loop per segment of a card.

    End conditions first, then the actions in the order the card lists them:
    that order is the priority, so a popup handler above a "click the button"
    row wins on every frame the popup is up. Segments break that: they run one
    after another, which is how a tutorial gets finished before the button it
    unlocks is even considered.
    """
    fn = func_name(page)
    elements = all_elements or {e['name']: e for e in page['elements']}
    segments = split_segments(page['steps'])
    capped = [step for seg in segments for step in seg
              if step.get('action') != 'none' and int(step.get('max') or 0) > 0]

    out = [
        f'    def {fn}(self, skip_first_screenshot=True):',
        '        """',
        f'        {label(page).capitalize()}.',
        '',
        '        Pages:',
        f'            in: {page["name"]}',
        f'            out: {page["name"]}',
        '        """',
        f"        logger.hr('{label(page).capitalize()}', level=2)",
    ]
    for step in capped:
        out.append(f'        count_{step["when"].lower()} = 0')

    for index, seg in enumerate(segments):
        ends = [s for s in seg if s.get('action') == 'none']
        acts = [s for s in seg if s.get('action') != 'none']
        if index == 0:
            out.append('        for _ in self.loop(timeout=30, skip_first=skip_first_screenshot):')
        else:
            out.append('        # 上一段做完了才走到这里：段与段是先后关系，不是优先级。')
            out.append('        for _ in self.loop(timeout=30, skip_first=False):')

        if not ends:
            out.append('            # TODO: 这一段没有「不点」的结束条件，只能等 30 秒超时。')
            if index < len(segments) - 1:
                out.append('            #       段与段要分开，靠的就是上一段的结束条件。')

        for step in ends:
            out.extend(render_end_step(step, elements))
        for step in acts:
            out.extend(render_act_step(step, elements))

        if index < len(segments) - 1:
            out.append('        else:')
            out.append(f"            # 上一段没做完就不许往下走：段与段之间是前置条件，不是优先级")
            out.append(f"            logger.warning('{label(page).capitalize()}: segment {index + 1} "
                       f"did not finish, skip the rest')")
            out.append('            return')

    note = (page.get('note') or '').strip().replace('\n', ' ')
    if note:
        out.append(f'            # {note}')
    return out


def render_end_step(step, elements):
    """The `if ...: break` that stops one segment."""
    element = elements.get(step.get('when'), {'type': 'image', 'stable': 1})
    name = upper(step['when'])
    stable = int(element.get('stable') or 1)
    offset = 'None' if element['type'] == 'color' else '(20, 20)'
    out = ['            # End']

    if element.get('type') == 'hollow':
        out.append(f'            if {guard(name, element)}:')
        out.append('                break')
    elif element['type'] in ('digit', 'text'):
        out.append('            # OCR 判据不适合当结束条件，这里只用"在不在"')
        out.append(f'            if self.appear({name}, offset=(20, 20)):')
        out.append('                break')
    elif stable > 1:
        pad = ' ' * (16 + len('if self.wait_until_appear('))
        out.append(f'            # 这一条要连续 {stable} 帧成立，动画帧不算')
        out.append(f'            if self.appear({name}, offset={offset}):')
        out.append(f'                if self.wait_until_appear({name}, offset={offset},')
        out.append(f'{pad}timeout=2, settle={stable}):')
        out.append('                    break')
    else:
        out.append(f'            if self.appear({name}, offset={offset}):')
        out.append('                break')
    return out


def render_act_step(step, elements):
    """One action row: the judgement, the press, the counter and the popup wait."""
    element = elements.get(step.get('when'), {'type': 'image'})
    name = upper(step['when'])
    cap = int(step.get('max') or 0)
    counter = f'count_{step["when"].lower()}'
    prefix = f'{counter} < {cap} and ' if cap else ''
    bump = [f'                {counter} += 1'] if cap else []

    if element['type'] in ('text', 'digit'):
        return render_ocr_step(
            step, element, name,
            prefix=prefix, counter=counter if cap else '',
        )

    wait = popup_wait(step, elements)
    out = []
    if step.get('then') == 'popup' and not step.get('popup'):
        out.append('            # TODO: 这一行点完会弹窗，但没指定弹窗长什么样。')
        out.append('            #       不指定的话，下一帧会再判到同一个按钮，把刚开的窗点掉。')

    offset = 'None' if element['type'] == 'color' else '(20, 20)'

    if element.get('type') == 'hollow':
        target = name if step.get('action') != 'other' else upper(step.get('target') or '')
        out.append(f'            if {prefix}{guard(name, element)}:')
        out.append(f'                self.device.click({target or name})')
        out.extend(bump)
        out.extend(wait)
        out.append('                continue')
        return out

    if step.get('action') == 'type':
        # 输入文字：点一下聚焦，再把字打进去。`input text` 只认 ASCII，
        # 所以中文昵称打不进去 —— 这不是限制，游戏本来就允许英文数字。
        content = (step.get('text') or '').strip()
        if not content:
            out.append('            # TODO: 这一行要输入文字，但卡片上没填内容')
            return out
        if not content.isascii():
            out.append(f'            # 警告：{content!r} 含非 ASCII 字符，`input text` 打不进去')
        out.append(f'            if {prefix}self.appear({name}, offset={offset}):')
        out.append(f'                self.device.click({name})')
        out.append(f"                self.device.adb_shell(['input', 'text', {content!r}])")
        out.extend(bump)
        out.append('                continue')
        return out

    if step.get('action') == 'other':
        target = upper(step.get('target') or '')
        if not target:
            out.append('            # TODO: 卡片说要点"另一个东西"，但没选是哪一个')
            return out
        out.append(f'            if {prefix}self.appear({name}, offset={offset}):')
        out.append(f'                self.device.click({target})  # 判据和点击不是同一个')
        out.extend(bump)
        out.extend(wait)
        out.append('                continue')
        return out

    if step.get('action') == 'tap':
        x, y = parse_point(step.get('target'))
        out.append(f'            if {prefix}self.appear({name}, offset={offset}):')
        out.append(f'                self.device.click(TAP_{x}_{y})  # 判据和点击不是同一个')
        out.extend(bump)
        out.extend(wait)
        out.append('                continue')
        return out

    out.append(f'            if {prefix}self.appear_then_click({name}, offset={offset}, interval=3):')
    out.extend(bump)
    out.extend(wait)
    out.append('                continue')
    return out


def popup_wait(step, elements):
    """The wait that keeps a delayed popup from being clicked away by the next frame."""
    if step.get('then') != 'popup':
        return []
    popup = upper(step.get('popup') or '')
    if not popup:
        return []
    popup_el = elements.get(step.get('popup') or '', {})
    offset = 'None' if popup_el.get('type') == 'color' else '(20, 20)'
    pad = ' ' * (16 + len('self.wait_until_appear('))
    return [
        '                # 点完会弹窗：等它真的出来再回头，',
        '                # 否则下一帧又判到同一个按钮，一按就把刚开的窗点掉了。',
        f'                self.wait_until_appear({popup}, offset={offset},',
        f'{pad}timeout=4, settle=2)',
    ]


def render_ocr_step(step, element, name, prefix='', counter=''):
    """
    One step whose check is an OCR reading, not a template.

    The template still guards the model: OCR costs milliseconds and is wrong
    often enough that it must not run on every frame. `Digit` answers 0 when it
    cannot read, which is the same value as a real zero, so the comparison
    always carries `value and` — a read of 0 means "no answer", not "empty".
    """
    out = [
        f'            if self.appear({name}, offset=(20, 20)):',
        '                # OCR 前先用模板确认这块在，OCR 每帧都跑要几十毫秒',
    ]
    if element['type'] == 'digit':
        op = element.get('cmp') or '>='
        num = int(element.get('num') or 0)
        out.append(f'                value = {name}_DIGIT.ocr(self.device.image)')
        cond = f'value and value {op} {num}'
        out.append(f'                if {prefix}{cond}:  # 0 = 读不到，和真的 0 分不开')
    else:
        expect = (element.get('text') or '').strip()
        out.append(f'                text = read_text(self.device.image, {name}_AREA)')
        cond = f'{expect!r} in text' if expect else 'text'
        out.append(f'                if {prefix}{cond}:')

    action = step.get('action')
    if action == 'tap':
        x, y = parse_point(step.get('target'))
        out.append(f'                    self.device.click(TAP_{x}_{y})')
    elif action == 'other' and step.get('target'):
        out.append(f'                    self.device.click({upper(step["target"])})')
    else:
        out.append(f'                    self.device.click({name})')
    if counter:
        out.append(f'                    {counter} += 1')
    out.extend('    ' + line for line in popup_wait(step, {}))
    out.append('                    continue')
    return out


def add_entry(spec, root):
    """
    Register the task where the framework looks for it.

    Three places, all required: `task.yaml` gives it a config group, the
    `SCHEDULER_PRIORITY` string is the only list the scheduler filters by (a
    task missing from it is never picked no matter what the config says), and
    `algs.py` needs a method named after the task, because the scheduler calls
    it by name.

    Nothing is written unless every anchor is found: a half-registered task is
    worse than an unregistered one, it shows up in the GUI and then refuses to
    run.

    Args:
        spec (dict): The whole spec.
        root (str): Repository root.

    Returns:
        list[str]: Human readable lines of what changed.
    """
    game = spec['game']
    module = spec.get('module') or game
    task = spec.get('task') or 'GeneratedTask'
    method = snake(task)
    prefix = pascal(game)
    done = []

    task_yaml = os.path.join(root, 'module', 'config', 'argument', 'task.yaml')
    manual_py = os.path.join(root, 'module', 'config', 'config_manual.py')
    algs_py = os.path.join(root, 'algs.py')
    for path in (task_yaml, manual_py, algs_py):
        if not os.path.isfile(path):
            raise SystemExit(f'anchor file missing: {path}')

    # 1) task.yaml: the task needs a group of its own under its game.
    with open(task_yaml, encoding='utf-8') as f:
        lines = f.read().splitlines()
    if any(re.match(rf'^\s{{4}}{task}:', line) for line in lines):
        done.append(f'task.yaml   {task} already registered')
    else:
        header = [i for i, line in enumerate(lines) if line.startswith('# ====')
                  and prefix in line]
        if not header:
            # First task of a new game: the whole section has to exist before a
            # task can hang under it, and its shape is the same for every game.
            lines.extend([
                '',
                '',
                f'# ==================== {prefix} ====================',
                '',
                f'{prefix}:',
                "  menu: 'collapse'",
                "  page: 'setting'",
                '  tasks:',
                f'    {task}:',
                '      - Scheduler',
            ])
            tasks_at = len(lines) - 1
        else:
            tasks_at = None
            for i in range(header[0], len(lines)):
                if lines[i].strip() == 'tasks:':
                    tasks_at = i
                    break
                if i > header[0] and lines[i].startswith('# ===='):
                    break
            if tasks_at is None:
                raise SystemExit(f'task.yaml section {prefix} has no "tasks:", add it by hand')
            lines[tasks_at + 1:tasks_at + 1] = [f'    {task}:', '      - Scheduler']
        with open(task_yaml, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(lines) + '\n')
        done.append(f'task.yaml   + {task}: [Scheduler]')

    # 2) SCHEDULER_PRIORITY: the only list get_next_task() filters by.
    with open(manual_py, encoding='utf-8') as f:
        lines = f.read().splitlines()
    if any(re.match(rf'^\s*[>]?\s*{task}\b', line) and line.startswith('    >') for line in lines):
        done.append(f'priority    {task} already listed')
    else:
        target = next((i for i, line in enumerate(lines)
                       if re.match(rf'^    > {prefix}\w*', line)), None)
        if target is not None:
            lines[target] = '    > ' + task + ' > ' + lines[target][len('    > '):]
        else:
            last = max((i for i, line in enumerate(lines) if line.startswith('    > ')), default=None)
            if last is None:
                raise SystemExit('SCHEDULER_PRIORITY not found in config_manual.py')
            lines.insert(last + 1, f'    > {task}')
        with open(manual_py, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(lines) + '\n')
        done.append(f'priority    + {task}')

    # 3) algs.py: two things — the `games` table, and the method the scheduler calls.
    #
    # `games` is easy to forget and it fails loudly at the worst moment: without
    # an entry, `AlGS.task_game()` cannot tell which game a task belongs to, and
    # `run_task` exits with "Cannot tell which game" before it touches the
    # emulator. Nothing else in the chain complains, so it looks like the task
    # was never written at all.
    with open(algs_py, encoding='utf-8') as f:
        lines = f.read().splitlines()

    ui_class = prefix + 'UI'
    if any(re.match(rf"^\s*'{re.escape(game)}':", line) for line in lines):
        done.append(f'algs.py     games 表里已有 {game}')
    else:
        start = next((i for i, line in enumerate(lines) if line.strip() == 'games = {'), None)
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == '}')
                   if start is not None else None)
        if start is None or end is None:
            raise SystemExit('algs.py 里找不到 games 字典，请手动登记这个游戏')
        lines.insert(end, f"        '{game}': ('module.{module}.{module}_ui', '{ui_class}'),")
        done.append(f'algs.py     games += {game} -> {ui_class}')

    if any(re.match(rf'^    def {method}\(', line) for line in lines):
        done.append(f'algs.py     {method}() already there')
    else:
        body = [
            f'    def {method}(self):',
            f'        from module.{module}.{method} import {task}',
            f'        {task}(config=self.config, device=self.device).run()',
        ]
        header = [i for i, line in enumerate(lines) if line.startswith('# ====') and prefix in line]
        if header:
            after = next((i for i in range(header[0] + 1, len(lines))
                          if lines[i].startswith('# ====')), len(lines))
            at = after
            while at > header[0] and not lines[at - 1].strip():
                at -= 1
            block = [''] + body + ['', '']
            lines[at:at] = block
        else:
            at = next((i for i, line in enumerate(lines) if line.startswith('if __name__')), len(lines))
            block = [''] + body + ['', '']
            lines[at:at] = block
        done.append(f'algs.py     + def {method}()')

    with open(algs_py, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')

    # 4) server.py: the namespace itself. Only reportable, not writable — the
    # package name has to come from `adb shell pm list packages`, and a guessed
    # one sends the task to the wrong game without any error.
    server_py = os.path.join(root, 'module', 'config', 'server.py')
    if os.path.isfile(server_py):
        with open(server_py, encoding='utf-8') as f:
            text = f.read()
        if f"'{game}'" not in text:
            done.append(f'! server.py   还没登记 {game}：要加 VALID_SERVER / VALID_PACKAGE / '
                        f'VALID_SERVER_LIST 三处，包名用 `adb shell pm list packages` 读')

    return done


ASSETS_HEADER = """from module.base.button import Button
from module.base.template import Template

# This file was automatically generated by dev_tools/button_extract.py.
# Don't modify it manually.

"""

PAGE_HEADER = '''"""Pages of {game}.

Every page is identified by a unique button, and `link()` records "click this
-> go there"; `UI.ui_goto()` then finds the shortest path from wherever the game
currently is.
"""

from module.ui.page import Page
'''


def ensure_module(root, game, module):
    """
    Lay down the minimum a game needs before its first card is written.

    A new game may have assets and no module at all. The three files here are
    the ones every other game starts with, and they are only written when
    missing, so calling this on an established game changes nothing.

    `assets.py` gets the same header `button_extract` writes, so an empty module
    survives a regeneration instead of being reported as broken.

    Args:
        root (str): Repository root.
        game (str): Game name, used in the docstring.
        module (str): Module folder name.

    Returns:
        list[str]: Files created, for the printout.
    """
    folder = os.path.join(root, 'module', module)
    if not os.path.isdir(folder):
        os.makedirs(folder)

    created = []

    init_py = os.path.join(folder, '__init__.py')
    if not os.path.isfile(init_py):
        open(init_py, 'w', encoding='utf-8').close()
        created.append(f'module/{module}/__init__.py')

    assets_py = os.path.join(folder, 'assets.py')
    if not os.path.isfile(assets_py):
        with open(assets_py, 'w', encoding='utf-8', newline='\n') as f:
            f.write(ASSETS_HEADER)
        created.append(f'module/{module}/assets.py')

    page_py = os.path.join(folder, 'page.py')
    if not os.path.isfile(page_py):
        with open(page_py, 'w', encoding='utf-8', newline='\n') as f:
            f.write(PAGE_HEADER.format(game=game))
        created.append(f'module/{module}/page.py')

    return created


def build(spec_path, write=False, root=ROOT):
    """Read a spec and write (or print) everything it generates."""
    with open(spec_path, encoding='utf-8') as f:
        spec = json.load(f)

    game = spec['game']
    module = spec.get('module') or game
    namespace = spec.get('namespace') or game
    task = spec.get('task') or 'GeneratedTask'

    assets_dir = os.path.join(root, 'assets', namespace, module)
    assets_py = os.path.join(root, 'module', module, 'assets.py')
    page_py = os.path.join(root, 'module', module, 'page.py')
    task_py = os.path.join(root, 'module', module, snake(task) + '.py')

    print(f'spec      {spec_path}')
    print(f'game      {game}   module {module}   namespace {namespace}   task {task}')
    print('')

    images, entries = {}, []
    flat, weak = [], []
    for page in spec['pages']:
        shot = decode_shot(page.get('shot')) if page.get('shot') else None
        if shot is None:
            # An empty card — no screenshot, nothing drawn on it. Keeping it out
            # instead of failing means a spec can be exported half-finished.
            continue
        for e in page['elements']:
            name = upper(e['name'])
            tap = parse_point(e['tap']) if e.get('tap') else None
            full, area, color, click = element_asset(shot, e['box'], int(e.get('pad') or 0), tap)
            images[name] = full
            entries.append((name, button_line(name, area, color, click, namespace, module), area))
            std = flat_contrast(shot, e['box'])
            if std < FLAT_DEAD:
                flat.append((page['name'], name, round(std, 2), tuple(int(v) for v in e['box'])))
            elif std < FLAT_WEAK:
                weak.append((page['name'], name, round(std, 2), tuple(int(v) for v in e['box'])))
            if e.get('type') == 'hollow':
                e['ink_color'], e['ink_count'] = measure_ink(shot, e['box'], e.get('ink') or 'light')
                print(f'  png   {name:24s} area={area} hollow ink={e["ink_color"]} '
                      f'pixels={e["ink_count"]} -> needs {max(10, e["ink_count"] // 2)}')
            else:
                extra = f' tap={tap}' if tap else ''
                print(f'  png   {name:24s} area={area} color={color} click={click} std={std:.1f}{extra}')

    if write:
        for line in ensure_module(root, game, module):
            print(f'  new   {line}')

    if spec.get('chain'):
        no_press = [p['name'] for p in spec['pages'] if not any(
            s.get('action') not in (None, 'none') for s in p.get('steps') or [])]
        if no_press:
            print('')
            print(f'  这些卡片没有「点它」的行，不会进链条: {", ".join(no_press)}')
    else:
        blank = [page['name'] for page in spec['pages'] if not page.get('check')]
        if blank:
            print('')
            print(f'  跳过没有判据的页面（不会生成代码）: {", ".join(blank)}')

    print('')
    print(f'assets.py  {len(entries)} entries -> {os.path.relpath(assets_py, root)}')
    if os.path.isfile(assets_py):
        content, added, skipped, conflicts = insert_assets(assets_py, entries)
    else:
        print('  (module has no assets.py yet, --write lays down the skeleton first)')
        content, added, skipped, conflicts = None, [n for n, _, _ in entries], [], []
    for name in added:
        print(f'  + {name}')
    for name in skipped:
        print(f'  = {name} (already there)')
    for line in conflicts:
        print(f'  ! area changed: {line}')

    if flat or weak:
        print('')
        print('  模板检查：')
    for page, name, std, box in flat:
        print(f'  !! {page}/{name}  std={std}  box={box}  —— 框里是纯色，模板会对任何画面都得 1.00，')
        print(f'     这个按钮等于"永远在屏幕上"。重新框：只框按钮本身，别框空白背景或黑边。')
    for page, name, std, box in weak:
        print(f'  !  {page}/{name}  std={std}  box={box}  —— 对比度很低，深色背景上容易误命中。')
        print(f'     能框紧一点就框紧一点。')

    chain_mode = bool(spec.get('chain'))
    if chain_mode:
        block = None
        print('')
        print('page.py    跳过：串联链模式不按页面导航，不需要 Page/link')
    else:
        block = render_page_block(spec, {})
        print('')
        print(f'page.py    -> {os.path.relpath(page_py, root)}')
        for line in block.splitlines():
            print(f'  | {line}')

    code = render_chain(spec) if chain_mode else render_task(spec)
    print('')
    print(f'task       -> {os.path.relpath(task_py, root)}')
    for line in code.splitlines():
        print(f'  | {line}')

    if not write:
        print('')
        print('Nothing written. Run again with --write to apply.')
        return

    if not os.path.isdir(assets_dir):
        os.makedirs(assets_dir)
    for name, image in images.items():
        save_image(image, os.path.join(assets_dir, name + '.png'))

    if content is not None:
        with open(assets_py, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)

    if block is not None:
        with open(page_py, encoding='utf-8') as f:
            old = f.read()
        if PAGE_BEGIN in old:
            head, _, rest = old.partition(PAGE_BEGIN)
            _, _, tail = rest.partition(PAGE_END)
            old = head + block + tail
        else:
            old = old.rstrip('\n') + '\n\n\n' + block + '\n'
        with open(page_py, 'w', encoding='utf-8', newline='\n') as f:
            f.write(old)

    if os.path.exists(task_py):
        print(f'! {os.path.relpath(task_py, root)} already exists, left untouched')
    else:
        with open(task_py, 'w', encoding='utf-8', newline='\n') as f:
            f.write(code)

    print('')
    print('Written. Registering the task:')
    for line in add_entry(spec, root):
        print(f'  {line}')
    print('')
    print('Next:')
    print('  1. python -m module.config.config_updater     # 生成 args.json / menu.json，GUI 才看得到')
    print('  2. python -m dev_tools.alas_lint --severity high')
    print('  3. fill the TODO lines in the task skeleton')


def main():
    parser = argparse.ArgumentParser(description='Build ALAS files from a page-card spec.')
    parser.add_argument('spec', help='spec.json exported by dev_tools/spec_editor.html')
    parser.add_argument('--write', action='store_true', help='apply instead of printing')
    parser.add_argument('--root', default=ROOT, help='repository root to write into (testing)')
    args = parser.parse_args()
    build(args.spec, write=args.write, root=args.root)


if __name__ == '__main__':
    main()
