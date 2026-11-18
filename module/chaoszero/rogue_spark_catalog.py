# -*- coding: utf-8 -*-
"""Lightweight Chaos Zero spark catalog and filter text helpers.

Kept free of PIL, OpenCV, and OCR imports so WebUI can load character cards
even when fake PIL stubs are active.
"""

import gzip
import json
import os
import re

DATA_FILE = os.path.join(os.path.dirname(__file__), 'rogue_cards.json.gz')
RELICS_FILE = os.path.join(os.path.dirname(__file__), 'rogue_relics.json.gz')
DECK_CARD_SUFFIXES = ('srt1', 'srt2', 'srt3', 'srt4', 'uni1', 'uni2', 'uni3', 'uni4', 'uni5')
_SPARK_CATALOG = None
_DECK_CATALOG = None


def normalize(text):
    """去掉数字、百分号、标点和空格，只留汉字。

    数字在卡面上是彩色的，掩膜取不到，所以两边都删掉再比。
    """
    text = re.sub(r'[0-9%×+]+', '', text or '')
    return re.sub(r'[^\u4e00-\u9fff]', '', text)


def spark_catalog():
    """Return cached `(characters, cards_by_character)` for sparkable cards."""
    global _SPARK_CATALOG
    if _SPARK_CATALOG is not None:
        return _SPARK_CATALOG
    with gzip.open(DATA_FILE, 'rt', encoding='utf-8') as handle:
        raw_cards = json.load(handle)
    with gzip.open(RELICS_FILE, 'rt', encoding='utf-8') as handle:
        raw_relics = json.load(handle)
    chars, by_char = [], {}
    for entry in raw_relics.get('characters', ()):
        cid = str(entry['id'])
        spark_cards = []
        for card in raw_cards.get(cid, ()):
            forms = [f for f in card.get('forms', ()) if '_rsp' in f.get('id', '')]
            if forms:
                spark_cards.append({
                    'id': card['id'],
                    'name': card['name'],
                    'forms': [{'index': i, 'desc': f.get('desc', '')} for i, f in enumerate(forms, 1)],
                })
        if spark_cards:
            names = dict(entry.get('names') or {})
            names.setdefault('zht', entry.get('name') or cid)
            chars.append({'id': cid, 'names': names})
            by_char[cid] = spark_cards
    _SPARK_CATALOG = (chars, by_char)
    return _SPARK_CATALOG


def character_name(entry, lang_code='zh-CN'):
    """Return localized display name for one character entry."""
    key = {'zh-CN': 'zhs', 'zh-TW': 'zht'}.get(lang_code, 'en')
    names = entry.get('names') or {}
    return names.get(key) or names.get('zht') or entry['id']


def parse_spark_filter(text):
    """Parse `RogueSparkFilter` text into `{card_name: value_str}`."""
    result = {}
    for raw in (text or '').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name, value = line.split('=', 1)
        name, value = name.strip(), value.strip()
        if name and value:
            result[name] = value
    return result


def update_spark_filter(text, card_name, choice):
    """Update or remove `card_name = choice` in `RogueSparkFilter` text."""
    kept, replaced = [], False
    target = normalize(card_name)
    choice = str(choice or '').strip()
    for raw in (text or '').splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith('#') and '=' in stripped:
            lhs = stripped.split('=', 1)[0].strip()
            if lhs == card_name or (target and normalize(lhs) == target):
                if choice and not replaced:
                    kept.append('%s = %s' % (card_name, choice))
                    replaced = True
                continue
        kept.append(raw)
    if choice and not replaced:
        kept.append('%s = %s' % (card_name, choice))
    return '\n'.join(kept)


def deck_catalog():
    """Return cached `{character_id: [card_entry, ...]}` for removable deck cards."""
    global _DECK_CATALOG
    if _DECK_CATALOG is not None:
        return _DECK_CATALOG
    with gzip.open(DATA_FILE, 'rt', encoding='utf-8') as handle:
        raw_cards = json.load(handle)
    allowed = set(DECK_CARD_SUFFIXES)
    order_map = {suffix: idx for idx, suffix in enumerate(DECK_CARD_SUFFIXES)}
    by_char = {}
    for cid, cards in raw_cards.items():
        grouped = {}
        ordered_names = []
        items = []
        for card in cards:
            suffix = str(card.get('id', '')).split('_')[-1]
            if suffix not in allowed:
                continue
            items.append((order_map[suffix], card, suffix))
        items.sort(key=lambda item: item[0])
        for _, card, suffix in items:
            name = card['name']
            has_rsp = any('_rsp' in f.get('id', '') for f in card.get('forms', ()))
            kind = 'spark' if has_rsp else ('basic' if suffix in ('srt1', 'srt2', 'srt3') else 'unique')
            if name not in grouped:
                grouped[name] = {
                    'id': card['id'],
                    'name': name,
                    'count': 1,
                    'kind': kind,
                }
                ordered_names.append(name)
            else:
                grouped[name]['count'] += 1
        by_char[str(cid)] = [grouped[name] for name in ordered_names]
    _DECK_CATALOG = by_char
    return _DECK_CATALOG


def parse_delete_filter(text):
    """Parse `RogueDeleteFilter` text into `[(card_name, count), ...]`."""
    rules = []
    seen = {}
    for raw in (text or '').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            name, count_text = line.split('=', 1)
            name = name.strip()
            try:
                count = int(count_text.strip())
            except ValueError:
                continue
        else:
            name, count = line, 1
        if not name or count <= 0:
            continue
        if name in seen:
            rules[seen[name]] = (name, count)
        else:
            seen[name] = len(rules)
            rules.append((name, count))
    return rules


def character_spark_cards(cid):
    """Return `{card_name, ...}` of sparkable cards belonging to character `cid`."""
    cid = str(cid or '').strip()
    if not cid:
        return set()
    _, by_char = spark_catalog()
    return {card['name'] for card in by_char.get(cid, ())}


def update_delete_filter(text, card_name, count):
    """Update or remove `card_name = count` in `RogueDeleteFilter` text."""
    try:
        count = max(0, int(count))
    except (TypeError, ValueError):
        count = 0
    return update_spark_filter(text, card_name, str(count) if count > 0 else '')


def prioritize_delete_rules(rules, slot_cids, preferred_slot=1):
    """Order delete rules so the preferred slot character's cards come first."""
    if not rules or not slot_cids:
        return list(rules)
    try:
        preferred = int(preferred_slot)
    except (TypeError, ValueError):
        preferred = 1
    if preferred not in (1, 2, 3):
        preferred = 1
    slot_order = [preferred] + [i for i in (1, 2, 3) if i != preferred]
    cid_rank = {}
    for rank, slot in enumerate(slot_order):
        if 1 <= slot <= len(slot_cids):
            cid = str(slot_cids[slot - 1] or '').strip()
            if cid and cid not in cid_rank:
                cid_rank[cid] = rank
    if not cid_rank:
        return list(rules)

    card_to_cid = {}
    norm_to_cid = {}
    for cid, cards in deck_catalog().items():
        for card in cards:
            cname = card['name']
            card_to_cid[cname] = cid
            nc = normalize(cname)
            if nc:
                norm_to_cid.setdefault(nc, cid)

    def _rule_rank(item):
        name = item[0]
        cid = card_to_cid.get(name) or norm_to_cid.get(normalize(name))
        return cid_rank.get(cid, len(slot_order))

    return [item for _, item in sorted(enumerate(rules), key=lambda pair: (_rule_rank(pair[1]), pair[0]))]
