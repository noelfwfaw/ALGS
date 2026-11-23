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
SPARKS_FILE = os.path.join(os.path.dirname(__file__), 'rogue_sparks.json.gz')
DECK_CARD_SUFFIXES = ('srt1', 'srt2', 'srt3', 'srt4', 'uni1', 'uni2', 'uni3', 'uni4', 'uni5')
NEUTRAL_FORM_VALUE = '6'
NEUTRAL_FORM_ALIASES = {'6', '中立', '中立閃', '中立闪', '普通', 'neutral'}
GOD_SPARK_DEFAULT_SCORE = 20
GOD_SPARK_PRIORITY = {
    # 默认顺位：獲得AP1 > 此卡牌費用減少1 > 常態弱點攻擊 > 賦予目標脆弱 > 抽取1
    '獲得AP1': 120,
    '此卡牌費用減少1': 115,
    '常態弱點攻擊': 110,
    '賦予目標脆弱3': 105,
    '賦予目標脆弱2': 104,
    '抽取1': 100,
    # 次级经济 / 抽牌 / 检索 / 连击
    '接下來觸發的自身卡牌費用減少2': 92,
    '調節：下一回合AP2': 90,
    '基本卡牌費用減少1': 85,
    '使用自我意識技能時，費用減少1': 84,
    '本回合自我意識技能費用減少1': 84,
    '恢復時，持續1回合至觸發前費用減少1': 84,
    '擊殺：抽取3': 82,
    '抽取至手牌達到4張為止': 80,
    '每次回合開始時，若為首次觸發的卡牌，則抽取2': 78,
    '將棄牌堆中的2張消滅卡牌移動至手牌': 76,
    '抽取1張自身的卡牌': 75,
    '依費用抽取': 72,
    '破壞：額外打擊1次': 72,
    '洗牌時，從抽牌堆移動至手牌': 70,
    '壓力增加5，打擊次數2倍': 70,
    '若手牌中有狀態異常或詛咒，打擊次數變為2倍': 68,
    # 增伤 / 暴击 / 自启动 / 词缀
    '必定暴擊': 64,
    '暴擊傷害+100%': 62,
    'BOSS戰鬥中，傷害量增加200%': 60,
    '基本傷害量增加100% / 賦予此卡牌終極': 56,
    '賦予此卡牌開戰': 55,
    '賦予此卡牌開幕': 55,
    '戰鬥開始時啟動': 55,
    '回合開始時，手牌中的此卡牌啟動': 55,
    '受擊時，手牌中的此卡牌啟動': 55,
    '賦予此卡牌主導，並啟動手牌中隨機的主導卡牌': 55,
    '此卡牌的傷害量增加30%': 50,
    '依敵人的數量，傷害量增加50%': 50,
    '若有護盾，傷害量增加50%': 48,
    '連續：傷害量增加50%': 48,
    '對未行動的目標傷害量增加50%': 48,
    '賦予此卡牌保留': 46,
    '所有戰鬥員夾擊100%': 46,
    '隨機友軍賦予目標100%的夾擊': 44,
    '士氣1、決心1': 42,
    '感應：持續1回合士氣3': 42,
    # 辅助 / 护盾 / 治疗 / 减益 / 负面代价
    '此卡牌的護盾量增加30%': 38,
    '此卡牌的治癒量增加30%': 38,
    '此卡牌的韌性傷害增加100%': 38,
    '閃避1，免疫1': 36,
    '賦予目標痛苦6': 34,
    '賦予目標痛苦4': 32,
    '費用增加1，傷害量增加100%': 25,
    # 低优先级：費用變更為0 整体价值低
    '費用變更為0': 15,
    '靈感：費用變更為0': 14,
    '若HP為全滿狀態，費用變更為0': 12,
    '手牌有8張以上時， / 費用變更為0': 12,
}
_SPARK_CATALOG = None
_DECK_CATALOG = None
_GOD_SPARK_ITEMS = None


def parse_form_choice(value):
    """Normalize a RogueSparkFilter choice to `'1'..'5'`, `'6'` (neutral), or `''`."""
    text = (value or '').strip()
    if text.lower() in NEUTRAL_FORM_ALIASES:
        return NEUTRAL_FORM_VALUE
    return text if text in ('1', '2', '3', '4', '5') else ''


def spark_cost_matches(item, cost, is_normal=False):
    """Check whether a spark affix's cost constraint allows the given card cost."""
    if cost is None:
        return True
    cmin = item.get('target_card_cost_min', -1)
    cmax = item.get('target_card_cost_max', 99)
    if is_normal:
        item_id = item.get('id', '')
        if cmin == 0 and cmax == 99 and re.match(r'^c\d+0$', item_id):
            return cost == 0
        if cmin == -1 and cmax == 99 and re.match(r'^c\d+5$', item_id):
            return cost < 0
    if cmin == 99 and cmax == 99:
        return cost < 0 or cost == 99
    if cmin != -1 and cost < cmin:
        return False
    if cmax != 99 and cost > cmax:
        return False
    return True


def spark_item_matches(item, category=None, cost=None, job=None, talents=None,
                       god_type=None, is_normal=False):
    """Check whether one spark item applies to the given god/card classification."""
    if god_type and item.get('god_type') != god_type:
        return False
    cats = item.get('target_card_category') or []
    if category and cats and category not in cats:
        return False
    if not spark_cost_matches(item, cost, is_normal=is_normal):
        return False
    jobs = item.get('target_link_base_class_define_id') or []
    if job and jobs and job not in jobs:
        return False
    if talents is not None:
        tset = set(talents)
        inc = item.get('target_card_include_talent') or []
        exc = item.get('target_card_exclude_talent') or []
        if inc and not any(t in tset for t in inc):
            return False
        if exc and any(t in tset for t in exc):
            return False
    return True


def is_rogue_god_spark(item):
    """Return whether a spark entry is a rogue card god-spark (`add_r_spark_*`)."""
    return bool(item.get('god_type')) and str(item.get('id') or '').startswith('add_')


def _god_spark_items():
    global _GOD_SPARK_ITEMS
    if _GOD_SPARK_ITEMS is not None:
        return _GOD_SPARK_ITEMS
    if not os.path.exists(SPARKS_FILE):
        _GOD_SPARK_ITEMS = []
        return _GOD_SPARK_ITEMS
    with gzip.open(SPARKS_FILE, 'rt', encoding='utf-8') as handle:
        data = json.load(handle)
    _GOD_SPARK_ITEMS = [item for item in data.get('items', ()) if is_rogue_god_spark(item)]
    return _GOD_SPARK_ITEMS


def god_spark_option_entries(card, form_choice=''):
    """Return valid rogue god-spark entries for one card.

    Base god sparks (`is_sortie=False`) are sorted ahead of sortie god sparks
    (`is_sortie=True`), ordered within each group by `GOD_SPARK_PRIORITY`.
    """
    if not card:
        return []
    choice = parse_form_choice(form_choice)
    form_specs = card.get('form_specs') or ()
    if choice in ('1', '2', '3', '4', '5') and int(choice) - 1 < len(form_specs):
        specs = [form_specs[int(choice) - 1]]
    elif choice == NEUTRAL_FORM_VALUE:
        specs = [card]
    else:
        specs = [card] + list(form_specs)

    by_desc = {}
    for spec in specs:
        cat = spec.get('category') or None
        cost = spec.get('cost')
        talents = spec.get('talent') if 'talent' in spec else None
        for item in _god_spark_items():
            desc = item.get('desc', '')
            if not desc:
                continue
            if spark_item_matches(item, category=cat, cost=cost, talents=talents, is_normal=False):
                info = by_desc.setdefault(desc, {'all_sortie': True, 'god_names': set()})
                if not item.get('is_sortie'):
                    info['all_sortie'] = False
                god_name = item.get('god_name') or ''
                if god_name:
                    info['god_names'].add(god_name)

    entries = [
        {
            'desc': desc,
            'is_sortie': info['all_sortie'],
            'god_name': next(iter(info['god_names'])) if len(info['god_names']) == 1 else '',
        }
        for desc, info in by_desc.items()
    ]
    entries.sort(
        key=lambda e: (
            1 if e['is_sortie'] else 0,
            -GOD_SPARK_PRIORITY.get(e['desc'], GOD_SPARK_DEFAULT_SCORE),
            e['desc'],
        )
    )
    return entries


def god_spark_options(card, form_choice=''):
    """Return valid god-spark descriptions for one card, ordered by default priority."""
    return [entry['desc'] for entry in god_spark_option_entries(card, form_choice)]


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
                    'base_desc': card.get('base_desc', ''),
                    'category': card.get('category', ''),
                    'cost': card.get('cost'),
                    'talent': list(card.get('talent') or ()),
                    'forms': [{'index': i, 'desc': f.get('desc', '')} for i, f in enumerate(forms, 1)],
                    'form_specs': [
                        {
                            'category': f.get('category', ''),
                            'cost': f.get('cost'),
                            'talent': list(f.get('talent') or ()),
                        }
                        for f in forms
                    ],
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


def parse_god_spark_filter(text):
    """Parse `RogueGodSparkFilter` text into `{card_name: [affix, ...]}`."""
    rules = {}
    for name, raw_val in parse_spark_filter(text).items():
        sep = '>' if '>' in raw_val else r'[,，;；]'
        seen = []
        for part in re.split(sep, raw_val):
            item = part.strip()
            if item and item not in seen:
                seen.append(item)
        if seen:
            rules[name] = seen
    return rules


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


def update_god_spark_filter(text, card_name, affixes):
    """Update or remove `card_name = affix1 > affix2` in `RogueGodSparkFilter` text."""
    cleaned = []
    for item in affixes or ():
        val = str(item or '').strip()
        if val and val not in cleaned:
            cleaned.append(val)
    return update_spark_filter(text, card_name, ' > '.join(cleaned))


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
