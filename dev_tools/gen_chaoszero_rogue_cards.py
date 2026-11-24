# -*- coding: utf-8 -*-
"""chaoszero 肉鸽卡牌库生成器。

从 E7BOT wiki 拉一遍卡牌表（接口是 AES-CBC 加密的，key 在网页 bundle 里），
抽出每个角色自己的卡：基础卡、紫卡、以及可灵闪卡的 5 种灵闪形态，写成 gzip JSON
放到 `module/chaoszero/rogue_cards.json.gz`，运行时只读本地文件。

用法：
    toolkit\\python.exe -m dev_tools.gen_chaoszero_rogue_cards
"""
import base64
import gzip
import io
import json
import os
import re
import sys

import requests

URL = 'https://wiki.e7bot.top/api/czn/cards/list'
KEY = b'2egkWEkLvR9idARLvjqfJdWKfR24HJgY'
OUT = 'module/chaoszero/rogue_cards.json.gz'
CUSTOM_FILE = os.path.join(os.path.dirname(__file__), 'chaoszero_custom_characters.json')

FORM_SUFFIX = re.compile(r'_(rsp\d+|mut\d*|lbk|pot)$')
TAG = re.compile(r'<[^>]*>')


def decrypt(payload):
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    raw = base64.b64decode(payload)
    iv, body = raw[:16], raw[16:]
    plain = unpad(AES.new(KEY, AES.MODE_CBC, iv).decrypt(body), AES.block_size)
    return json.loads(plain.decode('utf-8'))


def fetch():
    response = requests.get(URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
    response.raise_for_status()
    body = response.json()
    data = body.get('data')
    if body.get('encrypted') and isinstance(data, str):
        return decrypt(data)
    if isinstance(data, str):
        return json.loads(data)
    return data


def plain(text):
    text = TAG.sub('', text or '')
    return text.replace('<br>', ' / ').replace('\n', ' ').strip()


def talent_ids(card):
    """Extract non-empty talent IDs from a wiki card record."""
    return [t['id'] for t in (card.get('talent') or []) if isinstance(t, dict) and t.get('id')]


def load_custom_characters(path=CUSTOM_FILE):
    """Load manually curated characters not yet listed on the upstream wiki."""
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as handle:
        data = json.load(handle)
    return list(data.get('characters') or ())


def merge_custom_cards(library, path=CUSTOM_FILE):
    """Append custom character card decks into `library` when absent from upstream."""
    existing_names = {
        card.get('name')
        for cards in library.values()
        for card in cards
    }
    for entry in load_custom_characters(path):
        cid = str(entry.get('id') or '')
        cards = list(entry.get('cards') or ())
        if not cid or not cards or cid in library:
            continue
        if any(c.get('name') in existing_names for c in cards):
            continue
        library[cid] = cards
    return library


def main():
    body = fetch()
    cards = body['data'] if isinstance(body, dict) else body
    print('cards %s' % len(cards))

    index = {}
    for card in cards:
        index[card.get('id')] = card

    library = {}
    for card in cards:
        cid = card.get('id') or ''
        if FORM_SUFFIX.search(cid):
            continue
        base = card.get('base_combatant') or {}
        character = str(base.get('id') or '')
        if not character:
            continue
        forms = []
        for form_id in card.get('r_spark_cards') or []:
            form = form_id if isinstance(form_id, dict) else index.get(form_id)
            if not form:
                continue
            forms.append({
                'id': form.get('id'),
                'name': plain(form.get('name')),
                'desc': plain(form.get('desc_display')),
                'cost': form.get('cost'),
                'category': form.get('card_category') or '',
                'talent': talent_ids(form),
            })
        record = {
            'id': cid,
            'name': plain(card.get('name')),
            'base_desc': plain(card.get('desc_display')),
            'job': base.get('job') or '',
            'cost': card.get('cost'),
            'category': card.get('card_category') or '',
            'talent': talent_ids(card),
            'sort': card.get('sort'),
            'rarity': card.get('rarity'),
            'spine': card.get('spine_model'),
            'forms': forms,
        }
        library.setdefault(character, []).append(record)

    for character in library:
        library[character].sort(key=lambda item: (item.get('sort') or '', item.get('id') or ''))

    merge_custom_cards(library)

    data = json.dumps(library, ensure_ascii=False, sort_keys=True).encode('utf-8')
    with gzip.GzipFile(OUT + '.tmp', 'wb', mtime=0) as f:
        f.write(data)
    os.replace(OUT + '.tmp', OUT)

    characters = len(library)
    card_count = sum(len(v) for v in library.values())
    form_count = sum(len(c['forms']) for v in library.values() for c in v)
    print('characters %s cards %s forms %s -> %s (%s bytes)'
          % (characters, card_count, form_count, OUT, len(data)))

    sample = library[sorted(library)[0]]
    for card in sample[:6]:
        print('- %s %s cost=%s forms=%s'
              % (card['id'], card['name'], card['cost'],
                 [f['name'] for f in card['forms']]))


if __name__ == '__main__':
    main()
