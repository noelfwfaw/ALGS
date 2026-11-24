"""卡厄思：灵光三选一的「认卡 + 挑形态」。

灵光三选一的三张永远是**同一张卡**的不同形态（用户 2026-11-14 确认），
所以先把三列描述合起来认出是哪张卡，再在这张卡的 5 条形态描述里按关键词挑。

实测（2026-11-15，cnocr 1.2.2）：
- `extract_letters` 返回的是「黑字白底」，白色字必须把 threshold 拉到 250 才分得开；
- 框架的 `Ocr.ocr()` 只喂单行模型，整块多行描述会读成残片，所以要自己按行切；
- 数字是彩色字（绿/橙），掩膜只取近白 → 数值全丢，关键词只能写中文效果词。

所以这里的三步是：切行 → 逐行 OCR → 候选缩到「某张卡的 5 条形态」。
"""

import gzip
import json
import os
import re
from difflib import SequenceMatcher

import cv2
import numpy as np

from module.base.utils import extract_letters
from module.chaoszero.rogue_spark_catalog import (
    DATA_FILE,
    GOD_SPARK_DEFAULT_SCORE,
    GOD_SPARK_PRIORITY,
    NEUTRAL_FORM_ALIASES,
    RELICS_FILE,
    SPARKS_FILE,
    card_character_map,
    character_name,
    character_spark_cards,
    deck_catalog,
    is_rogue_god_spark,
    normalize,
    parse_delete_filter,
    parse_god_spark_filter,
    parse_spark_filter,
    prioritize_delete_rules,
    spark_catalog,
    spark_cost_matches,
    spark_item_matches,
    update_delete_filter,
    update_god_spark_filter,
    update_spark_filter,
)
from module.logger import logger
from module.ocr.ocr import Ocr

# 灵光三选一的三列（x0, x1）与描述块的 y 范围，1280x720
COLUMNS = ((180, 460), (495, 780), (810, 1105))
DESC_AREA = (390, 590)

# 白字掩膜：threshold 越大越只挑近白像素，250 能把白字和立绘分开
TEXT_THRESHOLD = 250
LETTER_LIMIT = 80

# 行切分：墨量 ≥ ROW_MIN_INK 才算有字，连续空白 ≥ ROW_GAP 断行
ROW_MIN_INK = 8
ROW_GAP = 3
ROW_MIN_HEIGHT = 9

# 认卡余量：第一名与第二名差不到这么多就不认，交给 RoguePick
CARD_MARGIN = 0.04

# 挑列的最低相似度：低于这个值就都不要，退回 RoguePick
COLUMN_MIN_SCORE = 0.35

# 认卡下限：至少总字数 >= 4 且最高相似度 >= 0.35，拦住 ['','', '點'] 等渐入过渡帧
CARD_MIN_SCORE = 0.35
CARD_MIN_CHARS = 4

# 亮底白字（神闪高光）局部对比度兜底切行参数
CONTRAST_FALLBACK_MIN_CHARS = 8
CONTRAST_TOPHAT_THRESHOLD = 40
CONTRAST_GRAY_MIN = 135
ROW_SPLIT_MAX_HEIGHT = 28

# 神闪额外词条匹配阈值
GOD_SPARK_MATCH = 0.78

# 第六种灵闪：中立闪（原卡 + 随机中立词条，0-based 序号 5，对应配置值 6 / 中立）
NEUTRAL_FORM_INDEX = 5
NEUTRAL_BASE_MIN_SCORE = 0.45
NEUTRAL_RSP_MARGIN = 0.03

# 底部神闪横幅文本到 rogue_sparks.json.gz 中 god_type 的映射
GOD_BANNER_TYPES = (
    ('尼希隆', 'NIHILUM'), ('尼希', 'NIHILUM'),
    ('戴奧斯', 'DIALLOS'), ('戴奥', 'DIALLOS'), ('戴奧', 'DIALLOS'),
    ('賽克瑞德', 'SECRED'), ('賽克', 'SECRED'), ('赛克', 'SECRED'),
    ('凱爾肯', 'CIRCEN'), ('凱爾', 'CIRCEN'), ('凯尔', 'CIRCEN'),
    ('維托', 'VITOR'), ('维托', 'VITOR'),
    ('@?#$', 'CALIGO'), ('@', 'CALIGO'), ('#', 'CALIGO'),
)


def parse_god_type(banner_text):
    """Map bottom god banner OCR text like `靈光一閃：維托` to canonical god_type."""
    text = banner_text or ''
    for alias, god_type in GOD_BANNER_TYPES:
        if alias in text:
            return god_type
    return None


def letters_mask(rgb):
    """白字掩膜，返回 0/255 的 2D 图。"""
    scaled = extract_letters(rgb, letter=(255, 255, 255), threshold=TEXT_THRESHOLD)
    return np.where(scaled < LETTER_LIMIT, 255, 0).astype(np.uint8)


def name_score(text, name):
    """卡名相似度：共享字数（宽容少字/多字）+ 序列相似度，各占一半。

    冥想选卡页、删卡网格上的名字是 24px 白字压在立绘上，实测 OCR 会错 1~2 个字
    （`決心墜飾`→`清心樂飾`、`科沃斯基爵士`→`科季斯基爵士十方`），所以单看
    序列相似度会漏；这里把"名字里的字有几个出现在 OCR 结果里"也算进来。
    """
    text = normalize(text)
    name = normalize(name)
    if not text or not name:
        return 0.0
    hit = sum(1 for char in name if char in text)
    return 0.5 * float(hit) / len(name) + 0.5 * SequenceMatcher(None, text, name).ratio()


def split_rows(mask):
    """按水平投影切行，返回 [(y0, y1)]。"""
    rows = (mask > 0).astype(np.uint8).sum(axis=1)
    lines = []
    start = None
    blank = 0
    for y, ink in enumerate(rows):
        if ink >= ROW_MIN_INK:
            if start is None:
                start = y
            blank = 0
        elif start is not None:
            blank += 1
            if blank >= ROW_GAP:
                end = y - blank
                if end - start >= ROW_MIN_HEIGHT:
                    lines.append((start, end + 1))
                start = None
                blank = 0
    if start is not None and len(rows) - start >= ROW_MIN_HEIGHT:
        lines.append((start, len(rows)))
    return lines


def normalize_spark(text):
    """神闪词条归一化：保留数字、AP、%+ 与汉字，便于匹配额外词条。"""
    return re.sub(r'[^0-9A-Za-z%+\u4e00-\u9fff]', '', (text or '').upper())


def split_rows_contrast(crop, scale=1.0):
    """局部对比度切行：对亮光卡面（近白阈 250 失效时）用顶帽提取白字再切行。"""
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY) if crop.ndim == 3 else crop
    k = max(5, int(round(9 * scale)) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    bg = cv2.morphologyEx(gray, cv2.MORPH_OPEN, kernel)
    th = cv2.subtract(gray, bg)
    mask = ((th > CONTRAST_TOPHAT_THRESHOLD) & (gray > CONTRAST_GRAY_MIN)).astype(np.uint8) * 255
    rows = split_rows(mask)
    if not rows:
        return rows
    max_h = int(round(ROW_SPLIT_MAX_HEIGHT * scale))
    proj = (mask > 0).astype(np.uint8).sum(axis=1)
    out = []
    for y0, y1 in rows:
        if y1 - y0 > max_h and y1 - y0 > 12:
            inner = proj[y0 + 6:y1 - 6]
            if inner.size:
                cut = y0 + 6 + int(np.argmin(inner))
                halves = [(a, b) for a, b in ((y0, cut), (cut, y1)) if b - a >= ROW_MIN_HEIGHT]
                if halves:
                    out.extend(halves)
                    continue
        out.append((y0, y1))
    return out


class GodSparkLibrary:
    """`rogue_sparks.json.gz` 的神閃與中立閃詞條庫（支持按神祇 / 類型 / 費用 / 職業 / 詞條過濾）。"""

    def __init__(self, file=SPARKS_FILE):
        self.file = file
        self.god_items = []
        self.normal_items = []
        self.sparks = []
        self.normal_sparks = []
        self._pool_cache = {}
        self._load()

    @staticmethod
    def _dedup_items(items):
        seen = set()
        out = []
        for item in items:
            desc = item.get('desc', '')
            if not desc or desc in seen:
                continue
            ns = normalize_spark(desc)
            if not ns:
                continue
            seen.add(desc)
            out.append((desc, ns))
        return out

    def _load(self):
        if not os.path.exists(self.file):
            logger.warning('Spark library not found, %s' % self.file)
            return
        with gzip.open(self.file, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        for item in data.get('items', []):
            if is_rogue_god_spark(item):
                self.god_items.append(item)
            elif not item.get('god_type'):
                self.normal_items.append(item)
        self.sparks = self._dedup_items(self.god_items)
        self.normal_sparks = self._dedup_items(self.normal_items)
        logger.info('Spark library loaded, %s god / %s normal affixes'
                    % (len(self.sparks), len(self.normal_sparks)))

    def god_pool(self, god_type=None, category=None, cost=None, talents=None, specs=None):
        """Return deduplicated god-spark `(desc, ns)` entries filtered by god/card metadata."""
        if specs:
            seen = set()
            out = []
            for spec in specs:
                pool = self.god_pool(
                    god_type=god_type,
                    category=spec.get('category') or None,
                    cost=spec.get('cost'),
                    talents=spec.get('talent') if 'talent' in spec else None,
                )
                for pair in pool:
                    if pair[0] not in seen:
                        seen.add(pair[0])
                        out.append(pair)
            return out
        if god_type is None and category is None and cost is None and talents is None:
            return self.sparks
        key = ('god', god_type, category, cost, tuple(sorted(set(talents))) if talents is not None else None)
        if key not in self._pool_cache:
            items = [
                item for item in self.god_items
                if spark_item_matches(
                    item, category=category, cost=cost, talents=talents,
                    god_type=god_type, is_normal=False,
                )
            ]
            self._pool_cache[key] = self._dedup_items(items)
        return self._pool_cache[key]

    def normal_pool(self, category=None, cost=None, job=None, talents=None):
        """Return deduplicated neutral-spark `(desc, ns)` entries filtered by card metadata."""
        if category is None and cost is None and job is None and talents is None:
            return self.normal_sparks
        key = ('norm', category, cost, job, tuple(sorted(set(talents))) if talents is not None else None)
        if key not in self._pool_cache:
            items = [
                item for item in self.normal_items
                if spark_item_matches(
                    item, category=category, cost=cost, job=job,
                    talents=talents, is_normal=True,
                )
            ]
            self._pool_cache[key] = self._dedup_items(items)
        return self._pool_cache[key]

    def priority(self, desc):
        """Return the configured priority score for a god-spark description."""
        if not desc:
            return 0
        return GOD_SPARK_PRIORITY.get(desc, GOD_SPARK_DEFAULT_SCORE)

    @staticmethod
    def matches_preferred(desc, preferred):
        """Return 0-based index of the first matching entry in `preferred`, or None."""
        if not desc or not preferred:
            return None
        ns_desc = normalize_spark(desc)
        for idx, pref in enumerate(preferred):
            pref = str(pref or '').strip()
            if not pref:
                continue
            if desc == pref:
                return idx
            ns_pref = normalize_spark(pref)
            if ns_pref and (ns_desc == ns_pref or (len(ns_pref) >= 3 and ns_pref in ns_desc)):
                return idx
        return None

    def preference_score(self, desc, preferred=None):
        """Score a matched god spark using ordered card preferences, then default priority."""
        if not desc:
            return 0
        base = self.priority(desc)
        if preferred:
            idx = self.matches_preferred(desc, preferred)
            if idx is not None:
                return max(1000, 10000 - idx * 100) + base
        return base

    @staticmethod
    def _fuzzy_tail(col_ns, ns, base_ns):
        tail_off = max(0, len(col_ns) - len(ns) - 10)
        tail = col_ns[tail_off:]
        best_r = 0.0
        best_span = (0, 0)
        for win in (len(ns) - 1, len(ns), len(ns) + 1):
            if win < 4 or win > len(tail):
                continue
            for i in range(len(tail) - win + 1):
                sub = tail[i:i + win]
                if base_ns and (
                    sub in base_ns
                    or (len(sub) >= 5 and (sub[1:] in base_ns or sub[:-1] in base_ns))
                ):
                    continue
                ratio = SequenceMatcher(None, sub, ns).ratio()
                if ratio > best_r:
                    best_r = ratio
                    best_span = (tail_off + i, tail_off + i + win)
        return best_r, best_span[0], best_span[1]

    def _match_pool(self, pool, raw_text, base_raw=''):
        col_ns = normalize_spark(raw_text)
        base_ns = normalize_spark(base_raw)
        if not col_ns:
            return None, 0.0, col_ns
        best = None
        for desc, ns in pool:
            if len(ns) < 3:
                continue
            if base_ns and ns in base_ns and col_ns.count(ns) <= base_ns.count(ns):
                continue
            pos = col_ns.rfind(ns)
            if pos != -1:
                cand = (1.0, len(ns), desc, pos, pos + len(ns))
                if best is None or (cand[0], cand[1]) > (best[0], best[1]):
                    best = cand
                continue
            if len(ns) < 4:
                continue
            best_r, start, end = self._fuzzy_tail(col_ns, ns, base_ns)
            if best_r >= GOD_SPARK_MATCH:
                cand = (best_r, len(ns), desc, start, end)
                if best is None or (cand[0], cand[1]) > (best[0], best[1]):
                    best = cand
        if not best:
            return None, 0.0, col_ns
        stripped = col_ns[:best[3]] + col_ns[best[4]:]
        return best[2], best[0], stripped

    def match_with_strip(self, raw_text, base_raw='', god_type=None, category=None,
                         cost=None, talents=None, specs=None):
        """Match a god spark and return `(desc, ratio, priority, stripped_ns)`."""
        pool = self.god_pool(god_type=god_type, category=category, cost=cost,
                             talents=talents, specs=specs)
        desc, ratio, stripped = self._match_pool(pool, raw_text, base_raw=base_raw)
        if not desc:
            return None, 0.0, 0, stripped
        return desc, ratio, self.priority(desc), stripped

    def match(self, raw_text, base_raw='', god_type=None, category=None,
              cost=None, talents=None, specs=None):
        """Match an OCR block against god-spark affixes not already in base_raw."""
        desc, ratio, prio, _ = self.match_with_strip(
            raw_text, base_raw=base_raw, god_type=god_type,
            category=category, cost=cost, talents=talents, specs=specs,
        )
        return desc, ratio, prio

    def match_normal(self, raw_text, base_raw='', category=None, cost=None,
                     job=None, talents=None):
        """Match a neutral-spark affix and return `(desc, ratio, stripped_ns)`."""
        pool = self.normal_pool(category=category, cost=cost, job=job, talents=talents)
        return self._match_pool(pool, raw_text, base_raw=base_raw)


class CardLibrary:
    """`rogue_cards.json.gz` 的形态索引。"""

    def __init__(self, file=DATA_FILE):
        self.file = file
        self.cards = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.file):
            logger.warning('Card library not found, %s' % self.file)
            return
        with gzip.open(self.file, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        for character, cards in data.items():
            for card in cards:
                forms = [normalize(form.get('desc', '')) for form in card.get('forms', [])]
                forms = [form for form in forms if form]
                if not forms:
                    continue
                key = (character, card['name'])
                base_desc = card.get('base_desc', '')
                self.cards[key] = {
                    'forms': forms,
                    'raw': [form.get('desc', '') for form in card.get('forms', [])],
                    'base_desc': base_desc,
                    'base_norm': normalize(base_desc),
                    'job': card.get('job', ''),
                    'category': card.get('category', ''),
                    'cost': card.get('cost'),
                    'talent': list(card.get('talent') or ()),
                    'form_specs': [
                        {
                            'category': f.get('category', ''),
                            'cost': f.get('cost'),
                            'talent': list(f.get('talent') or ()),
                        }
                        for f in card.get('forms', [])
                    ],
                }
        logger.info('Card library loaded, %s cards' % len(self.cards))

    def identify(self, texts):
        """三列 OCR 文本 → (卡名, 得分, 余量) 或 (None, 0, 0)。"""
        texts = [text for text in texts if text]
        if not texts or sum(len(text) for text in texts) < CARD_MIN_CHARS:
            return None, 0.0, 0.0
        scored = []
        for key, card in self.cards.items():
            total = 0.0
            for text in texts:
                total += max(SequenceMatcher(None, text, form).ratio()
                             for form in card['forms'])
            scored.append((total / len(texts), key[1]))
        scored.sort(reverse=True)
        if len(scored) < 2:
            if not scored or scored[0][0] < CARD_MIN_SCORE:
                return (None, scored[0][0], 0.0) if scored else (None, 0.0, 0.0)
            return scored[0][1], scored[0][0], 1.0
        # ❗**余量只算"不同卡名"之间的差**。
        # 灵光三选一的三列是**同一张卡的不同形态**，描述高度相似，所以同一张卡的
        # 多个形态经常一起排在前面 —— 旧算法拿 `scored[0] - scored[1]`，前两名
        # 是同一张卡的两个形态，差只有 0.0x，于是把正确结果判成"认不出"
        # （2026-11-16 离线复盘：神闪 20 页只有 50% 认出来，失败样本里
        #  `score` 有 0.51/0.52/0.57，卡得住的恰恰是 margin）。
        top_name = scored[0][1]
        runner = next((item for item in scored[1:] if item[1] != top_name), None)
        margin = scored[0][0] - (runner[0] if runner else 1.0)
        if scored[0][0] < CARD_MIN_SCORE or margin < CARD_MARGIN:
            return None, scored[0][0], margin
        return top_name, scored[0][0], margin

    def card_meta(self, name):
        """按卡名取完整卡牌元数据记录（含原卡描述、职业、费用与词条标签）。"""
        for (_character, card_name), card in self.cards.items():
            if card_name == name:
                return card
        return None

    def forms(self, name):
        """按卡名取形态列表（同名卡在不同角色身上时取第一个）。"""
        card = self.card_meta(name)
        return (card['forms'], card['raw']) if card else ([], [])

    def pick(self, name, keywords):
        """在卡的几种形态里挑最匹配关键词的那个，返回 (序号, 命中数, 描述)。"""
        forms, raw = self.forms(name)
        if not forms or not keywords:
            return None
        best = None
        for index, form in enumerate(forms):
            hits = sum(1 for word in keywords if word and word in form)
            score = (hits, -len(form))
            if best is None or score > best[0]:
                best = (score, index)
        if best is None or best[0][0] == 0:
            return None
        index = best[1]
        return index, best[0][0], raw[index] if index < len(raw) else forms[index]

    def form_value(self, name, index):
        """形态强弱代用值：描述里「百分比 × 倍数」的总和，`350%×2` 记 700。

        形态之间比强弱没有客观答案，数值是最接近的代理。用户 2026-11-15 让
        脚本自己决定关键词，所以没用配置关键词时就用它挑「这三列里数值最大的」。
        """
        meta = self.card_meta(name)
        if not meta:
            return 0.0
        if index == NEUTRAL_FORM_INDEX:
            text = meta.get('base_desc', '')
        elif index < len(meta['raw']):
            text = meta['raw'][index]
        else:
            return 0.0
        score = 0.0
        for value, times in re.findall(r'(\d+(?:\.\d+)?)\s*%(?:\s*[×xX*]\s*(\d+))?', text):
            score += float(value) * float(times or 1)
        for value in re.findall(r'(\d+)\s*[張张]', text):
            score += float(value)
        return score

    def default_form(self, name):
        """整库里数值最大的那个形态（只用于日志，实际从三列里挑）。"""
        forms, raw = self.forms(name)
        if not forms:
            return None
        best = None
        for index in range(len(forms)):
            score = self.form_value(name, index)
            if best is None or score > best[0]:
                best = (score, index)
        return best[1] if best else None

    def read_columns(self, texts, name):
        """每一列各自最像这张卡的哪个形态，返回 [(列序号, 相似度, 形态序号)]。

        三列只显示 5 个形态里的 3 个，所以不能拿目标形态去「找最像的列」——
        目标形态可能根本没出现（实测喘氣默认形态就没出现）。必须先认清每一列。
        """
        forms, raw = self.forms(name)
        if not forms:
            return []
        found = []
        for column, text in enumerate(texts):
            if not text:
                continue
            best = None
            for index, form in enumerate(forms):
                ratio = SequenceMatcher(None, text, form).ratio()
                if best is None or ratio > best[0]:
                    best = (ratio, index)
            if best[0] >= COLUMN_MIN_SCORE:
                found.append((column, best[0], best[1]))
        return found

    def analyze_columns(self, texts, raw_texts, name, spark_library, god=False, god_type=None):
        """两阶段分类辨析三列：先剥离神闪词条，再区分第 6 种中立闪与 rsp1~rsp5。

        Returns:
            tuple: `(columns, info)`，其中 `columns` 为 `[(col, ratio, form_idx)]`
            （中立闪对应 `NEUTRAL_FORM_INDEX = 5`），`info` 为按列索引的明细字典。
        """
        meta = self.card_meta(name)
        if not meta or not meta['forms']:
            return [], {}
        forms, raw_forms = meta['forms'], meta['raw']
        base_desc = meta.get('base_desc', '')
        base_norm = meta.get('base_norm', '')
        god_specs = (
            ([meta] + meta.get('form_specs', []))
            if (meta.get('category') or meta.get('form_specs')) else None
        )
        columns = []
        info = {}
        for col, text in enumerate(texts):
            raw = raw_texts[col] if col < len(raw_texts) else text
            if not text and not raw:
                continue
            if god:
                best_form_r, best_form_i = max(
                    (SequenceMatcher(None, text, f).ratio(), i) for i, f in enumerate(forms)
                )
                base_rough_r = SequenceMatcher(None, text, base_norm).ratio() if base_norm else 0.0
                if best_form_r >= base_rough_r and best_form_i < len(raw_forms):
                    cand_base = raw_forms[best_form_i]
                else:
                    cand_base = base_desc
                g_desc, g_r, g_prio, after_god = spark_library.match_with_strip(
                    raw, cand_base, god_type=god_type, specs=god_specs,
                )
            else:
                g_desc, g_r, g_prio, after_god = None, 0.0, 0, normalize_spark(raw)

            n_desc, n_r, after_norm = None, 0.0, after_god
            if base_norm:
                n_desc, n_r, after_norm = spark_library.match_normal(
                    after_god,
                    base_desc,
                    category=meta.get('category') or None,
                    cost=meta.get('cost'),
                    job=meta.get('job') or None,
                    talents=meta.get('talent') if 'talent' in meta else None,
                )

            rem_norm_g = normalize(after_god) or text
            best_rsp_r, best_rsp_i = max(
                (SequenceMatcher(None, rem_norm_g, form).ratio(), i) for i, form in enumerate(forms)
            )
            base_r = (
                SequenceMatcher(None, normalize(after_norm), base_norm).ratio()
                if (n_desc and base_norm) else 0.0
            )
            is_neutral = bool(
                n_desc
                and base_r >= NEUTRAL_BASE_MIN_SCORE
                and base_r > best_rsp_r + NEUTRAL_RSP_MARGIN
            )
            if is_neutral:
                columns.append((col, base_r, NEUTRAL_FORM_INDEX))
            elif best_rsp_r >= COLUMN_MIN_SCORE:
                columns.append((col, best_rsp_r, best_rsp_i))
            info[col] = {
                'god_desc': g_desc,
                'god_ratio': g_r,
                'god_prio': g_prio,
                'neutral_desc': n_desc if is_neutral else None,
                'neutral_ratio': n_r if is_neutral else 0.0,
            }
        return columns, info

    def pick_column(self, texts, keywords=None, name=None, form_index=None,
                    god_scores=None, columns=None, god_first=False):
        """先认清三列各是哪个形态，再按编号/关键词/神闪/数值挑一列。

        Args:
            texts (list): 三列 OCR 文本。
            keywords (list): 想要的效果词（`forms[index]` 里包含就算命中）。
            name (str): 卡名。
            form_index (int | None): 想要**第几种灵闪**（0 起，对应 `rspN`，5 对应中立闪）。
                用户 2026-11-16：游戏里点开卡详情能看到「①②③④⑤」编号，
                和库里的 `rsp1`~`rsp5` 一一对应，所以可以直接按编号指定。
                常规模式下 **给了这个就只认这一种形态**；三列里没有它就返回 None
                （说明这次没闪出来，调用方回退到随机选）。
            god_scores (Sequence[int | float] | None): 各列神闪额外词条优先度，
                用于在同形态或未配置卡牌间优先挑选高价值神闪（如 獲得AP1/減費）。
            columns (list | None): 预先辨析得到的列形态列表。
            god_first (bool): 为 True 且存在可识别神闪词条时，直接按神闪优先级挑列，
                再用目标形态/数值/相似度打破平局。

        Returns:
            tuple | None: (列序号, 得分, 形态序号, 描述)。
        """
        if columns is None:
            columns = self.read_columns(texts, name)
        if not columns:
            return None
        forms, raw = self.forms(name)
        meta = self.card_meta(name) or {}
        base_norm = meta.get('base_norm', '')

        def form_text(idx):
            if idx == NEUTRAL_FORM_INDEX:
                return base_norm
            return forms[idx] if idx < len(forms) else ''

        def spark_score(col):
            return god_scores[col] if god_scores and col < len(god_scores) else 0

        def form_hit(idx):
            if form_index is not None:
                return 1 if idx == form_index else 0
            if keywords:
                text = form_text(idx)
                return 1 if any(word and word in text for word in keywords) else 0
            return 0

        has_god = bool(god_scores and any(spark_score(col) > 0 for col, _, _ in columns))
        best_key = None
        chosen = None
        if god_first and has_god:
            for column, ratio, index in columns:
                key = (spark_score(column), form_hit(index), self.form_value(name, index), ratio)
                if best_key is None or key > best_key:
                    best_key = key
                    chosen = (column, ratio, index)
        elif form_index is not None or keywords:
            for column, ratio, index in columns:
                if not form_hit(index):
                    continue
                key = (spark_score(column), ratio)
                if best_key is None or key > best_key:
                    best_key = key
                    chosen = (column, ratio, index)
            if chosen is None:
                return None
        else:
            for column, ratio, index in columns:
                value = self.form_value(name, index)
                key = (spark_score(column), value, ratio) if has_god else (value, ratio)
                if best_key is None or key > best_key:
                    best_key = key
                    chosen = (column, ratio, index)
        index = chosen[2]
        if index == NEUTRAL_FORM_INDEX:
            chosen_raw = meta.get('base_desc') or '中立閃'
        else:
            chosen_raw = raw[index] if index < len(raw) else forms[index]
        return chosen[0], chosen[1], index, chosen_raw


class CardReader:
    """按列读卡面描述（切行 + 单行 OCR）。

    优先用繁体 ONNX 模型（`rogue_ocr.ChtOcr`，PP-OCRv3 cht）：传统字识别准、
    认卡得分从 0.59~0.63 提到 0.62~0.81，余量翻 2~3 倍。模型或 onnxruntime
    缺失时自动退回 cnocr 1.2.2 的逐行识别。
    """

    def __init__(self):
        self.ocr = None
        self.cht = None
        self.cht_checked = False
        self.last_raw = []

    def _get_ocr(self, area):
        if self.ocr is None:
            self.ocr = Ocr(area, lang='cnocr', letter=(255, 255, 255), threshold=128, name='ROGUE_CARD')
            self.ocr.SHOW_LOG = False
        return self.ocr

    def _get_cht(self):
        if not self.cht_checked:
            self.cht_checked = True
            try:
                from module.chaoszero.rogue_ocr import get_cht_ocr

                reader = get_cht_ocr()
                if reader.available():
                    self.cht = reader
                    logger.info('Card reader uses the traditional ONNX model')
                else:
                    logger.info('Traditional OCR model not available, fall back to cnocr')
            except Exception as error:
                logger.info('Traditional OCR unavailable (%s), fall back to cnocr' % error)
        return self.cht

    def _read_crop_lines(self, crop, area, scale=1.0, raw=False):
        mask = letters_mask(crop)
        pad = max(4, int(round(4 * scale)))
        min_h = max(10, int(round(10 * scale)))
        cht = self._get_cht()
        if cht:
            def run_rows(rows):
                lines = []
                for y0, y1 in rows:
                    ya, yb = max(0, y0 - pad), min(crop.shape[0], y1 + pad)
                    if yb - ya >= min_h:
                        lines.append(crop[ya:yb, :])
                return ' '.join(cht.lines(lines)) if lines else ''

            primary = run_rows(split_rows(mask))
            if len(normalize(primary)) < CONTRAST_FALLBACK_MIN_CHARS:
                alt = run_rows(split_rows_contrast(crop, scale=scale))
                if len(normalize(alt)) > len(normalize(primary)):
                    primary = alt
            return primary if raw else normalize(primary)
        rows = split_rows(mask)
        if not rows:
            return ''
        crops = []
        for y0, y1 in rows:
            line = mask[max(0, y0 - pad):y1 + pad, :]
            if line.shape[0] >= min_h:
                crops.append(line.astype(np.uint8))
        if not crops:
            return ''
        ocr = self._get_ocr(area)
        result = ocr.cnocr.atomic_ocr_for_single_lines(crops)
        joined = ' '.join(''.join(chars) for chars in result)
        return joined if raw else normalize(joined)

    def read(self, image, column, scale=1.0, raw=False):
        """image: RGB ndarray；column: (x0, x1)。返回归一化后的文本。

        Args:
            scale (float): 提字前把描述区放大几倍。1.0 = 原尺寸。
            raw (bool): 为 True 时保留数字与英文符号（供神闪额外词条匹配）。
        """
        x0, x1 = column
        area = (x0 + 12, DESC_AREA[0], x1 - 12, DESC_AREA[1])
        crop = image[area[1]:area[3], area[0]:area[2]]
        if crop is None or not crop.size:
            return ''
        if scale and scale != 1.0:
            crop = cv2.resize(crop, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_CUBIC)
        return self._read_crop_lines(crop, area, scale=scale, raw=raw)

    def read_all(self, image, columns=COLUMNS, scale=1.0):
        raws = [self.read(image, column, scale=scale, raw=True) for column in columns]
        self.last_raw = raws
        return [normalize(text) for text in raws]

    def read_block(self, image, area, scale=1, raw=False):
        """读一块**多行**文字（不限于卡牌描述区）。

        和 `read()` 同一套逻辑（提字掩膜 → 按行切 → 逐行 OCR → 拼起来），
        只是区域由调用方给。命运（塔罗）三选一的效果说明用得上
        （2026-11-16 用户：光收标题不够，效果也要收，否则判断不了哪个好）。

        Args:
            image (np.ndarray): RGB 帧。
            area (tuple): (x1, y1, x2, y2)。
            scale (float): 提字前放大倍数。
            raw (bool): 为 True 时保留数字与英文符号（供神闪词条匹配）。

        Returns:
            str: 整段文本（默认归一化为纯汉字，读不出为空串）。
        """
        crop = image[area[1]:area[3], area[0]:area[2]]
        if crop is None or not crop.size:
            return ''
        # 命运卡的效果字只有 ~14px，原尺寸 OCR 基本是乱码（实测
        # 「精英區域的裝備獎勵中…」被读成「龍戰獎的日」）。先放大 2 倍再提字。
        if scale and scale != 1:
            crop = cv2.resize(crop, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_CUBIC)
        return self._read_crop_lines(crop, area, scale=scale, raw=raw)

    def read_name(self, image, area, scale=1.0, raw=False):
        """读卡名条这类白字小字（冥想选卡、删卡网格）。返回归一化文本。

        Args:
            raw (bool): 装备名含英文和数字时保留 OCR 原文。
            scale (float): 提字前放大几倍。删卡网格的卡名只有 ~20px，
                原尺寸 OCR 只能读出前两个字（`劍之雨`→`劍市`、
                `一縷光芒`→`建立`），放大后再读明显好。
        """
        crop = image[area[1]:area[3], area[0]:area[2]]
        if crop is None or not crop.size:
            return ''
        if scale and scale != 1.0:
            crop = cv2.resize(crop, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        cht = self._get_cht()
        if cht:
            text = cht.line(gray)
        else:
            ocr = self._get_ocr(area)
            result = ocr.cnocr.atomic_ocr_for_single_lines([gray.astype(np.uint8)])
            text = ''.join(''.join(chars) for chars in result)
        return text if raw else normalize(text)
