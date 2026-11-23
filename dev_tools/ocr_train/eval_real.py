# -*- coding: utf-8 -*-
"""Evaluate Chaos Zero OCR models on real logged screenshots.

Measures:
  1. Flash & God-flash card identification rate, mean score, mean margin,
     and god-banner (`靈光一閃：...`) text accuracy.
  2. Event option title matching rate on `log/rogue_event_pages/*.png`.
  3. Fate effect text readability on `log/rogue_fate_pages/*/*_effect*.png`.

Usage:
    toolkit\\python.exe -m dev_tools.ocr_train.eval_real
    toolkit\\python.exe -m dev_tools.ocr_train.eval_real --model bin/ocr_models/chaoszero_rec.onnx --height 32 --norm cnocr
"""

import argparse
import glob
import os
import time

import cv2
import numpy as np

from module.config.server import set_server

set_server('chaoszero')

from module.chaoszero import rogue_cards, rogue_events
from module.chaoszero.rogue_ocr import ChtOcr

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
GOD_BANNER_AREA = (430, 600, 850, 650)
EVENT_TITLE_BOX = (-150, -125, 150, -95)
EVENT_POINTS = ((308, 677), (640, 677), (974, 677))


class OnnxTester(ChtOcr):
    """Configurable ONNX OCR reader supporting both PP-OCRv3 (h=48) and CnOCR (h=32)."""

    def __init__(self, model, dictionary=None, height=48, norm='ppocr', rgb_direct=False):
        super().__init__(model=model, dictionary=dictionary or './bin/ocr_models/ppocr_keys_v1.txt')
        self.height = height
        self.norm = norm
        self.rgb_direct = rgb_direct

    def available(self):
        if self.failed or not os.path.exists(self.model_file):
            return False
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            return False
        return True

    def line(self, image):
        if image is None or image.shape[0] < 8:
            return ''
        if self.session is None:
            if not self.available():
                self.failed = True
                return ''
            self._load()
        meta = self.session.get_modelmeta().custom_metadata_map or {}
        if meta.get('preprocess') == 'cnocr_gray_32_01':
            if image.ndim == 3:
                if image.shape[2] == 4:
                    gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
                else:
                    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            else:
                gray = image
            h, w = gray.shape[:2]
            target_w = max(16, min(1200, int(round(32 * (w / float(h))))))
            resized = cv2.resize(gray, (target_w, 32), interpolation=cv2.INTER_LINEAR)
            arr = (resized.astype(np.float32) / 255.0)[None, None, :, :]
            inputs = {
                'x': arr,
                'input_lengths': np.array([target_w], dtype=np.int64),
            }
            logits = self.session.run(None, inputs)[0]
            vocab = meta['character'].splitlines()
            blank = len(vocab)
            index = logits.argmax(axis=2)[0]
            res = []
            last = -1
            for item in index:
                item = int(item)
                if item != last and item != blank and item < len(vocab):
                    ch = vocab[item]
                    res.append(' ' if ch == '<space>' else ch)
                last = item
            return ''.join(res)

        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        elif image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2RGB)
        h, w = image.shape[:2]
        target_w = max(8, min(1200, int(round(self.height * (w / float(h))))))
        resized = cv2.resize(image, (target_w, self.height), interpolation=cv2.INTER_LINEAR)
        arr = resized.astype(np.float32) / 255.0
        if self.norm == 'ppocr':
            arr = (arr - 0.5) / 0.5
        elif self.norm == 'imagenet':
            mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
            std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
            arr = (arr - mean) / std
        arr = np.transpose(arr, (2, 0, 1))[None, ...]
        out = self.session.run(None, {self.session.get_inputs()[0].name: arr})[0]
        return self.decode(out)


def read_column_lines(reader, image, column, use_mask=True):
    x0, x1 = column
    area = (x0 + 12, rogue_cards.DESC_AREA[0], x1 - 12, rogue_cards.DESC_AREA[1])
    crop = image[area[1]:area[3], area[0]:area[2]]
    mask = rogue_cards.letters_mask(crop)
    rows = rogue_cards.split_rows(mask)
    if not rows:
        return ''
    texts = []
    for y0, y1 in rows:
        ya, yb = max(0, y0 - 4), min(crop.shape[0], y1 + 4)
        if yb - ya < 10:
            continue
        if use_mask:
            patch = cv2.cvtColor(mask[ya:yb, :], cv2.COLOR_GRAY2RGB)
        else:
            patch = crop[ya:yb, :]
        texts.append(reader.line(patch))
    return rogue_cards.normalize(''.join(texts))


def eval_cards(reader, use_mask=True):
    lib = rogue_cards.CardLibrary()
    files = sorted(
        glob.glob(os.path.join(ROOT, 'log', 'rogue_card_pages', 'flash', '*.png'))
        + glob.glob(os.path.join(ROOT, 'log', 'rogue_card_pages', 'god', '*.png'))
    )
    ok = 0
    scores, margins = [], []
    god_ok = god_total = 0
    full_count = 0
    for path in files:
        bgr = cv2.imread(path)
        if bgr is None or bgr.shape[:2] != (720, 1280):
            continue
        full_count += 1
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        texts = [read_column_lines(reader, rgb, col, use_mask=use_mask) for col in rogue_cards.COLUMNS]
        card, score, margin = lib.identify(texts)
        if card:
            ok += 1
            scores.append(score)
            margins.append(margin)
        if os.sep + 'god' + os.sep in path:
            god_total += 1
            gx1, gy1, gx2, gy2 = GOD_BANNER_AREA
            gcrop = rgb[gy1:gy2, gx1:gx2]
            gtext = reader.line(gcrop)
            if '靈光一閃' in gtext:
                god_ok += 1
            if not card or '靈光一閃' not in gtext:
                print(f'  [card/god] {os.path.relpath(path, ROOT)}: card={card} ({score or 0:.3f}, m={margin or 0:.3f}) god="{gtext}"')
    print(
        f'Cards (flash+god): {ok}/{full_count} identified '
        f'| avg_score={np.mean(scores) if scores else 0:.3f} '
        f'| avg_margin={np.mean(margins) if margins else 0:.3f} '
        f'| god_banner_exact={god_ok}/{god_total}'
    )


def eval_events(reader):
    import json
    lib = rogue_events.EventLibrary()
    files = sorted(glob.glob(os.path.join(ROOT, 'log', 'rogue_event_pages', '*.png')))
    matched = 0
    for path in files:
        bgr = cv2.imread(path)
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        jpath = os.path.splitext(path)[0] + '.json'
        points = EVENT_POINTS
        if os.path.exists(jpath):
            meta = json.load(open(jpath, encoding='utf-8'))
            if meta.get('points'):
                points = meta['points']
        titles = []
        for cx, cy in points:
            x1 = max(0, cx + EVENT_TITLE_BOX[0])
            y1 = max(0, cy + EVENT_TITLE_BOX[1])
            x2 = min(1280, cx + EVENT_TITLE_BOX[2])
            y2 = min(720, cy + EVENT_TITLE_BOX[3])
            titles.append(rogue_cards.normalize(reader.line(rgb[y1:y2, x1:x2])))
        ranked = lib.candidates(titles, None)
        if ranked:
            matched += 1
    print(f'Events: {matched}/{len(files)} matched an encounter')


def eval_fate_effects(reader):
    files = sorted(glob.glob(os.path.join(ROOT, 'log', 'rogue_fate_pages', '*', '*_effect*.png')))[:15]
    print(f'Fate effect samples ({len(files)} shown):')
    for path in files[:6]:
        bgr = cv2.imread(path)
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        # Trim bright outer card frame (left/right borders) before splitting lines
        if rgb.shape[1] > 40:
            rgb = rgb[:, 16:-16]
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        row_max = gray.max(axis=1)
        lines = []
        in_row, s = False, 0
        for y, val in enumerate(row_max):
            if val > 150 and not in_row:
                in_row, s = True, y
            elif val <= 150 and in_row:
                if y - s >= 6:
                    patch = rgb[max(0, s - 3):min(rgb.shape[0], y + 3), :]
                    patch = cv2.resize(patch, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                    lines.append(reader.line(patch))
                in_row = False
        if in_row and rgb.shape[0] - s >= 6:
            patch = rgb[max(0, s - 3):, :]
            patch = cv2.resize(patch, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            lines.append(reader.line(patch))
        print(f'  {os.path.basename(path)}: {" | ".join(lines)}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='./bin/ocr_models/chinese_cht_PP-OCRv3_rec_infer.onnx')
    parser.add_argument('--dict', default='./bin/ocr_models/ppocr_keys_v1.txt')
    parser.add_argument('--height', type=int, default=48)
    parser.add_argument('--norm', default='ppocr')
    parser.add_argument('--no-mask', action='store_true')
    args = parser.parse_args()

    t0 = time.time()
    reader = OnnxTester(args.model, dictionary=args.dict, height=args.height, norm=args.norm)
    print(f'Evaluating model={args.model} height={args.height} norm={args.norm} use_mask={not args.no_mask}')
    eval_cards(reader, use_mask=not args.no_mask)
    eval_events(reader)
    eval_fate_effects(reader)
    print(f'Elapsed: {time.time() - t0:.2f}s')


if __name__ == '__main__':
    main()
