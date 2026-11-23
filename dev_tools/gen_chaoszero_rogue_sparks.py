# -*- coding: utf-8 -*-
"""chaoszero 神闪 / 灵光词条库生成器。

从 E7BOT wiki 拉取 `/api/czn/r-sparks/list`（含神闪与通用灵光词条），
整理后写成 gzip JSON 放到 `module/chaoszero/rogue_sparks.json.gz`。

用法：
    toolkit\\python.exe -m dev_tools.gen_chaoszero_rogue_sparks
"""
import gzip
import json
import os
import re
from collections import Counter

from dev_tools.gen_chaoszero_rogue_db import get

OUT = 'module/chaoszero/rogue_sparks.json.gz'
TAG = re.compile(r'<[^>]*>')
BR = re.compile(r'<br\s*/?>', re.IGNORECASE)

GOD_NAMES = {
    'NIHILUM': {'zht': '尼希隆', 'zhs': '尼希隆', 'en': 'Nihilum'},
    'DIALLOS': {'zht': '戴奧斯', 'zhs': '戴奥斯', 'en': 'Diallos'},
    'SECRED': {'zht': '賽克瑞德', 'zhs': '赛克瑞德', 'en': 'Secred'},
    'CIRCEN': {'zht': '凱爾肯', 'zhs': '凯尔肯', 'en': 'Circen'},
    'VITOR': {'zht': '維托', 'zhs': '维托', 'en': 'Vitor'},
    'CALIGO': {'zht': '@?#$', 'zhs': '@?#$', 'en': '@?#$'},
}


def plain(text):
    """Strip wiki HTML/color tags while turning `<br>` into `' / '`."""
    text = BR.sub(' / ', text or '')
    text = TAG.sub('', text)
    return text.replace('\n', ' ').strip()


def build_records(items):
    """Normalize and sort raw `/r-sparks/list` records."""
    records = []
    for item in items:
        god_type = item.get('god_type') or ''
        raw_desc = item.get('description') or ''
        god_info = GOD_NAMES.get(god_type)
        records.append({
            'id': item.get('id') or '',
            'god_type': god_type,
            'god_name': god_info['zht'] if god_info else '',
            'desc': plain(raw_desc),
            'raw_desc': raw_desc,
            'rarity': item.get('rarity') or '',
            'add_cost_value': item.get('add_cost_value', 0),
            'is_sortie': bool(item.get('is_sortie', False)),
            'target_card_category': list(item.get('target_card_category') or []),
            'target_card_cost_min': item.get('target_card_cost_min'),
            'target_card_cost_max': item.get('target_card_cost_max'),
            'target_card_include_talent': list(item.get('target_card_include_talent') or []),
            'target_card_exclude_talent': list(item.get('target_card_exclude_talent') or []),
            'target_link_base_class_define_id': list(item.get('target_link_base_class_define_id') or []),
        })
    records.sort(key=lambda r: (r['god_type'], r['id']))
    assert records and all(r['id'] for r in records), 'Incomplete spark record'
    assert len({r['id'] for r in records}) == len(records), 'Duplicate spark id'
    return records


def main():
    body = get('/r-sparks/list')
    items = body['data'] if isinstance(body, dict) and 'data' in body else body
    records = build_records(items)

    payload = {
        'source': 'https://wiki.e7bot.top/#/czn/sparks',
        'gods': GOD_NAMES,
        'items': records,
    }
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
    with gzip.GzipFile(OUT + '.tmp', 'wb', mtime=0) as handle:
        handle.write(data)
    os.replace(OUT + '.tmp', OUT)

    god_items = [r for r in records if r['god_type']]
    general_items = [r for r in records if not r['god_type']]
    god_counts = Counter(r['god_type'] for r in god_items)
    unique_god_descs = sorted({r['desc'] for r in god_items if r['desc']})

    print(f'total {len(records)} (god {len(god_items)}, general {len(general_items)}) -> {OUT} ({len(data)} bytes)')
    print('by god_type:', dict(sorted(god_counts.items())))
    print(f'unique god plain descs: {len(unique_god_descs)}')
    for gt in GOD_NAMES:
        samples = [r['desc'] for r in god_items if r['god_type'] == gt][:4]
        print(f'- {gt} ({GOD_NAMES[gt]["zht"]}): {samples}')


if __name__ == '__main__':
    main()
