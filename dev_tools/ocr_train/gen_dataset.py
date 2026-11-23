# -*- coding: utf-8 -*-
"""Generate synthetic Chaos Zero OCR training & validation line images.

Renders lines from `work/corpus.tsv` using NotoSansTC + Windows TC/SC UI fonts
across three in-game visual domains:
  1. Dark UI panels with white & colored highlights (numbers/keywords) + drop shadow
  2. Real Chaos Zero card-art background patches + white/tinted text + dark outline
  3. High-contrast binarized `letters_mask`-style strokes (for compatibility with mask paths)

Outputs `work/dataset/images/*.png` and `train.tsv` / `dev.tsv`.

Usage:
    .venv_ocr\\Scripts\\python.exe -m dev_tools.ocr_train.gen_dataset --train 60000 --val 3000
"""

import argparse
import glob
import os
import random
from concurrent.futures import ProcessPoolExecutor

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

WORK = os.path.join(os.path.dirname(__file__), 'work')
FONT_NOTO = os.path.join(WORK, 'fonts', 'NotoSansTC.ttf')

HIGHLIGHT_COLORS = (
    (245, 175, 75),   # orange numbers
    (115, 235, 120),  # green %
    (95, 210, 255),   # cyan keywords
    (190, 145, 255),  # purple card title tint
)


def discover_fonts():
    candidates = [
        (FONT_NOTO, 0, 60, (350, 400, 450, 500)),
        (r'C:\Windows\Fonts\msjh.ttc', 0, 20, None),
        (r'C:\Windows\Fonts\MiSans-Regular.otf', 0, 10, None),
        (r'C:\Windows\Fonts\msyh.ttc', 0, 10, None),
    ]
    found = []
    for path, index, weight, axes in candidates:
        if os.path.exists(path):
            found.append((path, index, weight, axes))
    if not found:
        raise FileNotFoundError('No CJK fonts found for synthetic generation')
    return found


def load_corpus(path):
    lines, weights = [], []
    with open(path, encoding='utf-8') as f:
        for raw in f:
            raw = raw.rstrip('\n')
            if '\t' not in raw:
                continue
            w_str, text = raw.split('\t', 1)
            if text:
                lines.append(text)
                weights.append(max(1, int(w_str)))
    return lines, weights


class WorkerState:
    fonts = None
    bgs = None
    font_weights = None


def init_worker(font_specs, bg_paths):
    WorkerState.fonts = font_specs
    WorkerState.font_weights = [spec[2] for spec in font_specs]
    WorkerState.bgs = []
    for p in bg_paths:
        img = cv2.imread(p)
        if img is not None:
            WorkerState.bgs.append(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def get_font(rng, size):
    spec = rng.choices(WorkerState.fonts, weights=WorkerState.font_weights, k=1)[0]
    path, index, _, axes = spec
    font = ImageFont.truetype(path, size=size, index=index)
    if axes:
        try:
            font.set_variation_by_axes([rng.choice(axes)])
        except Exception:
            pass
    return font


def render_one(args):
    idx, text, out_dir, seed = args
    rng = random.Random(seed + idx * 1009)

    font_size = rng.randint(14, 26)
    font = get_font(rng, font_size)

    # Measure text bounding box accurately
    dummy = Image.new('RGB', (10, 10))
    draw_dummy = ImageDraw.Draw(dummy)
    try:
        bbox = draw_dummy.textbbox((0, 0), text, font=font)
        tw = max(4, bbox[2] - bbox[0])
        th = max(8, bbox[3] - bbox[1])
        ox, oy = -bbox[0], -bbox[1]
    except Exception:
        tw, th = max(8, len(text) * font_size), font_size + 4
        ox, oy = 0, 0

    # Mix tight crops (split rows / fate effects) and loose asymmetric UI crops (event titles / god banner)
    loose = rng.random() < 0.50
    if loose:
        pad_left = rng.randint(4, 24)
        pad_right = rng.randint(24, 210)
        pad_top = rng.randint(4, 18)
        pad_bottom = rng.randint(1, 12)
        if rng.random() < 0.25:
            # Centered wide banner (like god banner 靈光一閃：...)
            extra_x = rng.randint(40, 140)
            pad_left = extra_x
            pad_right = extra_x
    else:
        pad_left = rng.randint(3, 12)
        pad_right = rng.randint(3, 12)
        pad_top = rng.randint(2, 6)
        pad_bottom = rng.randint(2, 6)

    w = tw + pad_left + pad_right
    h = th + pad_top + pad_bottom

    mode_roll = rng.random()
    if mode_roll < 0.45 or not WorkerState.bgs:
        # Mode 0: Dark UI box + white/colored text + subtle shadow
        base_v = rng.randint(18, 52)
        bg = np.full((h, w, 3), base_v, dtype=np.uint8)
        bg = np.clip(bg.astype(np.int16) + rng.randint(-5, 5), 0, 255).astype(np.uint8)
        if rng.random() < 0.25:
            # Subtle UI border line near top/bottom/side
            line_v = rng.randint(120, 210)
            if rng.random() < 0.5:
                bg[0:1, :] = line_v
            else:
                bg[-1:, :] = line_v
        mode = 'dark'
    elif mode_roll < 0.85:
        # Mode 1: Real game card-art / event-panel background patch
        src = rng.choice(WorkerState.bgs)
        sh, sw = src.shape[:2]
        if sw < w or sh < h:
            src = cv2.resize(src, (max(sw, w + 8), max(sh, h + 8)), interpolation=cv2.INTER_LINEAR)
            sh, sw = src.shape[:2]
        y0 = rng.randint(0, sh - h)
        x0 = rng.randint(0, sw - w)
        bg = src[y0:y0 + h, x0:x0 + w].copy()
        alpha = rng.uniform(0.25, 0.80)
        bg = (bg.astype(np.float32) * alpha).astype(np.uint8)
        mode = 'art'
    else:
        # Mode 2: Binarized mask style (black-on-white or white-on-black)
        invert = rng.random() < 0.65
        bg = np.full((h, w, 3), 255 if invert else 0, dtype=np.uint8)
        mode = 'mask_bw' if invert else 'mask_wb'

    pil_img = Image.fromarray(bg)
    draw = ImageDraw.Draw(pil_img)

    tx = pad_left + ox
    ty = pad_top + oy

    if mode in ('dark', 'art'):
        # Subtle drop shadow (single offset or soft 4-neighbor on busy art), never heavy thick box
        shadow_color = (rng.randint(0, 22), rng.randint(0, 22), rng.randint(0, 22))
        if mode == 'art' and rng.random() < 0.4:
            for dx, dy in ((1, 0), (0, 1), (1, 1)):
                draw.text((tx + dx, ty + dy), text, font=font, fill=shadow_color)
        elif rng.random() < 0.7:
            draw.text((tx + 1, ty + 1), text, font=font, fill=shadow_color)

        # Draw character-by-character so numbers / highlighted spans match game colors
        cur_x = tx
        use_color = rng.random() < 0.55
        hl_color = rng.choice(HIGHLIGHT_COLORS)
        hl_start = rng.randint(0, max(0, len(text) - 2))
        hl_end = hl_start + rng.randint(1, 4)
        base_white = (rng.randint(230, 255), rng.randint(230, 255), rng.randint(230, 255))
        if mode == 'art' and rng.random() < 0.25:
            # Blue/purple sparked title tint
            base_white = rng.choice(((170, 205, 255), (205, 175, 255)))

        for ci, ch in enumerate(text):
            if use_color and (ch.isdigit() or ch in '%×+-'):
                color = hl_color
            elif use_color and mode == 'dark' and hl_start <= ci < hl_end and rng.random() < 0.4:
                color = hl_color
            else:
                color = base_white
            draw.text((cur_x, ty), ch, font=font, fill=color)
            try:
                cur_x += draw.textlength(ch, font=font)
            except Exception:
                cur_x += font_size
    else:
        fg = (0, 0, 0) if mode == 'mask_bw' else (255, 255, 255)
        draw.text((tx, ty), text, font=font, fill=fg)

    # Realism degradations: slight blur & resize jitter (simulating 1.5x-2x upscale of tiny text)
    if rng.random() < 0.30:
        pil_img = pil_img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.2, 0.55)))

    arr = np.array(pil_img)
    if font_size <= 18 and rng.random() < 0.45:
        scale = rng.uniform(1.3, 2.0)
        arr = cv2.resize(arr, (max(8, int(w * scale)), max(8, int(h * scale))),
                         interpolation=cv2.INTER_CUBIC)

    if mode in ('mask_bw', 'mask_wb') and rng.random() < 0.5:
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        _, binary = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY)
        arr = cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)

    rel_path = f'images/{idx:06d}.png'
    out_path = os.path.join(out_dir, rel_path)
    cv2.imwrite(out_path, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
    return rel_path, text


def write_tsv(records, path):
    with open(path, 'w', encoding='utf-8') as f:
        for rel_path, text in records:
            tokens = ' '.join('<space>' if ch == ' ' else ch for ch in text)
            f.write(f'{rel_path}\t{tokens}\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--train', type=int, default=60000)
    parser.add_argument('--val', type=int, default=3000)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--workers', type=int, default=max(2, (os.cpu_count() or 4) - 2))
    args = parser.parse_args()

    corpus_path = os.path.join(WORK, 'corpus.tsv')
    lines, weights = load_corpus(corpus_path)
    font_specs = discover_fonts()
    bg_paths = sorted(glob.glob(os.path.join(WORK, 'backgrounds', '*.png')))

    ds_dir = os.path.join(WORK, 'dataset')
    img_dir = os.path.join(ds_dir, 'images')
    os.makedirs(img_dir, exist_ok=True)

    rng = random.Random(args.seed)
    total = args.train + args.val
    sampled = rng.choices(lines, weights=weights, k=total)

    # Guarantee every corpus line appears at least once in train
    if args.train >= len(lines):
        unique_lines = list(dict.fromkeys(lines))
        rest = rng.choices(lines, weights=weights, k=args.train - len(unique_lines))
        train_texts = unique_lines + rest
        rng.shuffle(train_texts)
        val_texts = rng.choices(lines, weights=weights, k=args.val)
        sampled = train_texts + val_texts

    tasks = [(i, text, ds_dir, args.seed) for i, text in enumerate(sampled)]
    print(f'Generating {total} images ({args.train} train / {args.val} val) using {args.workers} workers...')

    results = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=init_worker,
                             initargs=(font_specs, bg_paths)) as pool:
        for i, rec in enumerate(pool.map(render_one, tasks, chunksize=256), 1):
            results.append(rec)
            if i % 10000 == 0 or i == total:
                print(f'  generated {i}/{total}')

    write_tsv(results[:args.train], os.path.join(ds_dir, 'train.tsv'))
    write_tsv(results[args.train:], os.path.join(ds_dir, 'dev.tsv'))
    print(f'Done -> {ds_dir}')


if __name__ == '__main__':
    main()

