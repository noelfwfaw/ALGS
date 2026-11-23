# -*- coding: utf-8 -*-
"""Extract Chaos Zero Traditional Chinese vocabulary and training corpus lines.

Reads all offline Chaos Zero game databases (`rogue_cards.json.gz`,
`rogue_relics.json.gz`, `rogue_events.json.gz`) and UI strings in
`module/chaoszero/*.py` to produce:
  - `dev_tools/ocr_train/work/vocab.txt`: closed Chaos Zero character set
  - `dev_tools/ocr_train/work/corpus.txt`: weighted single-line training strings
  - `dev_tools/ocr_train/work/backgrounds/`: real game background/card-art patches

Usage:
    toolkit\\python.exe -m dev_tools.ocr_train.build_corpus
"""

import glob
import gzip
import json
import os
import re

import cv2
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
WORK = os.path.join(os.path.dirname(__file__), 'work')

CARDS_FILE = os.path.join(ROOT, 'module', 'chaoszero', 'rogue_cards.json.gz')
RELICS_FILE = os.path.join(ROOT, 'module', 'chaoszero', 'rogue_relics.json.gz')
EVENTS_FILE = os.path.join(ROOT, 'module', 'chaoszero', 'rogue_events.json.gz')

BASE_ASCII = (
    '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
    ' %+-*/×÷=.,:;!?()[]{}<>【】「」『』《》〈〉、，。：；！？…—～·・'
)

GOD_NAMES = ('戴奧斯', '尼希隆', '維托', '賽克瑞德', '凱爾肯')
EXTRA_PHRASES = [
    '靈光一閃',
    '靈光一閃：戴奧斯',
    '靈光一閃：尼希隆',
    '靈光一閃：維托',
    '靈光一閃：賽克瑞德',
    '靈光一閃：凱爾肯',
    '請選擇欲獲得【靈光一閃】的戰鬥員。',
    '請選擇要複製卡牌的戰鬥員。',
    '請選擇1張欲移除的卡牌。',
    '請選擇1張再次靈光一閃卡牌。',
    '請選擇靈光一閃效果。',
    '請選擇裝備',
    '請選擇戰鬥員',
    '基本卡牌的打擊次數增加1次。',
    '此卡牌的傷害量增加30%',
    '此卡牌的護盾獲得量增加30%',
    '此卡牌的治癒量增加30%',
    '此卡牌費用減少1',
    '獲得AP1',
    '抽取1',
    '存檔資料收集完成',
    '探索結果',
    '免費',
    '取消',
    '移除',
    '確認',
    '離開',
    '跳過',
    '查看內容',
    '查看詳情',
    '記憶殘片',
    '記憶雕琢',
    '選擇刻印的記憶',
    '重新搜索',
    '航點',
    '裝備',
    '熱情', '啟迪', '開朗', '共情', '勤勞',
    '嫉妒', '專注', '支配', '缺乏', '擁有',
    '啟發', '領悟', '回憶', '烙印', '代價',
    '虐待', '堅韌', '貪婪', '戰慄', '導向',
    '愛戀', '應許', '盜取', '竊聽', '迴響',
]


def wrap_line(text, max_len=14):
    """Split a long card/event description into realistic short UI lines."""
    text = re.sub(r'\s+', ' ', (text or '').strip())
    if not text:
        return []
    parts = []
    for seg in re.split(r'[\n/]+', text):
        seg = seg.strip()
        if not seg:
            continue
        if len(seg) <= max_len:
            parts.append(seg)
            continue
        # Split on punctuation first, then fixed width slices for line-wrap robustness
        sub_segs = [s.strip() for s in re.split(r'(?<=[，。；：！？」】])', seg) if s.strip()]
        for sub in sub_segs:
            if len(sub) <= max_len:
                parts.append(sub)
            else:
                for i in range(0, len(sub), max_len):
                    chunk = sub[i:i + max_len]
                    if chunk:
                        parts.append(chunk)
                # Also add shifted splits so mid-word wraps occur in training
                for i in range(max_len // 2, len(sub), max_len):
                    chunk = sub[i:i + max_len]
                    if len(chunk) >= 3:
                        parts.append(chunk)
    return parts


def collect_corpus():
    cards = json.load(gzip.open(CARDS_FILE, 'rt', encoding='utf-8'))
    relics = json.load(gzip.open(RELICS_FILE, 'rt', encoding='utf-8'))
    events = json.load(gzip.open(EVENTS_FILE, 'rt', encoding='utf-8'))

    weighted_lines = []  # (line, weight)

    # 1. Cards: names (heavily weighted because small grid names fail often) & forms
    for cs in cards.values():
        for card in cs:
            name = (card.get('name') or '').strip()
            cost = card.get('cost')
            if name:
                weighted_lines.append((name, 6))
                if cost is not None and str(cost).isdigit():
                    weighted_lines.append((f'{cost} {name}', 3))
                    weighted_lines.append((f'{cost}{name}', 3))
            for form in card.get('forms', []):
                desc = (form.get('desc') or '').strip()
                if desc:
                    for line in wrap_line(desc, max_len=13):
                        weighted_lines.append((line, 2))
                    for line in wrap_line(desc, max_len=10):
                        weighted_lines.append((line, 1))

    # 2. Relics / equipment / characters
    for item in relics.get('items', []):
        name = (item.get('name') or '').strip()
        if name:
            weighted_lines.append((name, 5))
    for char in relics.get('characters', []):
        for key in ('name',):
            val = (char.get(key) or '').strip()
            if val:
                weighted_lines.append((val, 3))
        zht = ((char.get('names') or {}).get('zht') or '').strip()
        if zht:
            weighted_lines.append((zht, 3))

    # 3. Events: titles, options, conditions, outcomes
    for ev in events.values():
        ev_name = (ev.get('name') or '').strip()
        if ev_name:
            weighted_lines.append((ev_name, 2))
        for opt in ev.get('options', []):
            flavor = (opt.get('flavor') or '').strip()
            if flavor:
                for line in wrap_line(flavor, max_len=14):
                    weighted_lines.append((line, 3))
            for cond in opt.get('conditions', []):
                for line in wrap_line(cond, max_len=14):
                    weighted_lines.append((line, 2))
            for group in ('success', 'fail'):
                for entry in opt.get(group, []):
                    desc = (entry.get('desc') or '').strip()
                    if desc:
                        for line in wrap_line(desc, max_len=14):
                            weighted_lines.append((line, 1))

    # 4. Extra UI & god-flash & fate phrases + numeric counters
    for phrase in EXTRA_PHRASES:
        weighted_lines.append((phrase, 5))
        for line in wrap_line(phrase, max_len=12):
            weighted_lines.append((line, 3))

    for n in range(0, 100):
        weighted_lines.append((f'{n}%', 1))
    for n in range(50, 260, 5):
        weighted_lines.append((f'{n}pt', 2))
        weighted_lines.append((f'存檔資料儲存上限{n}pt', 3))
        weighted_lines.append((f'·存檔資料儲存上限{n}pt', 3))
    for god in GOD_NAMES:
        weighted_lines.append((f'靈光一閃：{god}', 8))
    for a in (0, 1, 2, 3, 4, 5, 10, 15, 20, 30, 50, 80, 100, 120, 240):
        for b in (1, 4, 5, 10, 15, 170, 240):
            weighted_lines.append((f'{a}/{b}', 1))

    # 5. Character set = union of all corpus chars + module/chaoszero/*.py CJK + BASE_ASCII
    chars = set(BASE_ASCII)
    for line, _ in weighted_lines:
        chars.update(line)
    for py_path in glob.glob(os.path.join(ROOT, 'module', 'chaoszero', '*.py')):
        text = open(py_path, encoding='utf-8').read()
        for block in re.findall(r'[\u4e00-\u9fff]+', text):
            chars.update(block)

    # Remove control characters and space (cnocr handles <space> separately or as ' ')
    chars.discard('\n')
    chars.discard('\r')
    chars.discard('\t')
    # Normalize spaces in lines
    cleaned = []
    for line, weight in weighted_lines:
        line = re.sub(r'\s+', ' ', line).strip()
        if line:
            cleaned.append((line, weight))

    # Ensure EVERY char in `chars` appears in at least one corpus line (for closed-set coverage)
    present = set(''.join(line for line, _ in cleaned))
    missing = sorted(c for c in chars if c not in present and c != ' ')
    if missing:
        for i in range(0, len(missing), 10):
            cleaned.append((''.join(missing[i:i + 10]), 3))

    return sorted(chars), cleaned


def extract_backgrounds():
    """Crop real dark UI & card illustration patches from existing rogue screenshots."""
    bg_dir = os.path.join(WORK, 'backgrounds')
    os.makedirs(bg_dir, exist_ok=True)
    sources = (
        glob.glob(os.path.join(ROOT, 'log', 'rogue_card_pages', 'flash', '*.png'))[:8]
        + glob.glob(os.path.join(ROOT, 'log', 'rogue_card_pages', 'god', '*.png'))[:6]
        + glob.glob(os.path.join(ROOT, 'log', 'rogue_card_pages', 'remove', '*.png'))[:4]
        + glob.glob(os.path.join(ROOT, 'log', 'rogue_event_pages', '*.png'))[:6]
    )
    count = 0
    for idx, path in enumerate(sources):
        img = cv2.imread(path)
        if img is None or img.shape[0] < 720 or img.shape[1] < 1280:
            continue
        # Sample card illustration patches and dark UI panel strips
        rois = [
            (200, 190, 440, 310),
            (515, 190, 755, 310),
            (830, 190, 1070, 310),
            (180, 560, 460, 620),
            (500, 560, 780, 620),
            (50, 200, 300, 320),
        ]
        for r_idx, (x1, y1, x2, y2) in enumerate(rois):
            patch = img[y1:y2, x1:x2]
            if patch.size:
                out = os.path.join(bg_dir, f'bg_{idx:02d}_{r_idx}.png')
                cv2.imwrite(out, patch)
                count += 1
    return count


def main():
    os.makedirs(WORK, exist_ok=True)
    chars, weighted_lines = collect_corpus()

    vocab_path = os.path.join(WORK, 'vocab.txt')
    with open(vocab_path, 'w', encoding='utf-8') as f:
        for ch in chars:
            f.write(('<space>' if ch == ' ' else ch) + '\n')

    corpus_path = os.path.join(WORK, 'corpus.tsv')
    with open(corpus_path, 'w', encoding='utf-8') as f:
        for line, weight in weighted_lines:
            f.write(f'{weight}\t{line}\n')

    bg_count = extract_backgrounds()
    print(f'vocab: {len(chars)} chars -> {vocab_path}')
    print(f'corpus: {len(weighted_lines)} entries -> {corpus_path}')
    print(f'backgrounds: {bg_count} real game patches -> {os.path.join(WORK, "backgrounds")}')


if __name__ == '__main__':
    main()

