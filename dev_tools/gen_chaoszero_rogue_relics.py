"""Refresh the offline equipment/character index from E7BOT; stars are ignored."""

import gzip
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests

from dev_tools.gen_chaoszero_rogue_cards import load_custom_characters
from dev_tools.gen_chaoszero_rogue_db import get


ROOT = Path('module/chaoszero')
TYPES = {'EQUIP_WEAPON': 0, 'EQUIP_ARMOR': 1, 'EQUIP_ACC': 2}
RARITIES = ('RARITY_COMMON', 'RARITY_RARE', 'RARITY_LEGEND', 'RARITY_UNIQUE')
# 实机旧截图为“禍之聖袍”，Wiki 当前误写成“禍之聖砲”；保留两个名称。
GAME_NAMES = {'eq_pub_041': '禍之聖袍'}


def records(relics, characters):
    items = []
    for relic in relics:
        if relic.get('relic_type') not in TYPES:
            continue
        assert relic.get('id') and relic.get('name'), 'Incomplete equipment record'
        items.append({'id': relic['id'], 'name': relic['name'],
                      'names': relic.get('names', {}),
                      'slot': TYPES[relic['relic_type']],
                      'rarity': RARITIES.index(relic['rarity']),
                      'icon': relic.get('icon_name', '').split('/')[-1],
                      'shop': 'delang' in (relic.get('reward_tag') or ()),
                      'unique': relic['rarity'] == 'RARITY_UNIQUE'})
        if relic['id'] in GAME_NAMES:
            items[-1]['aliases'] = [GAME_NAMES[relic['id']]]
    chars = [{'id': c['id'], 'name': c['name'], 'names': c.get('names', {}),
              'face': c.get('card_icon_name') or 'face/character/face_character_' + c['id']}
             for c in characters if c.get('char_type') == 'CHAR_COMBATANT']
    assert items and chars and len({i['id'] for i in items}) == len(items)
    return {'source': 'https://wiki.e7bot.top/#/czn/relics',
            'items': items, 'characters': chars}


def fetch_icon(path):
    response = requests.get('https://wiki.e7bot.top/api/assets/file/czn/data/'
                            + path + '.webp', timeout=30)
    response.raise_for_status()
    import cv2
    blob = np.frombuffer(response.content, dtype=np.uint8)
    assert cv2.imdecode(blob, cv2.IMREAD_UNCHANGED) is not None, path
    return blob


def custom_character_records():
    """Return `(records, face_blobs)` for manually curated characters."""
    import cv2

    chars = []
    faces = {}
    for entry in load_custom_characters():
        cid = str(entry.get('id') or '')
        name = entry.get('name') or ''
        face_file = entry.get('face_file') or ''
        if not cid or not name or not face_file or not os.path.exists(face_file):
            continue
        image = cv2.imread(face_file, cv2.IMREAD_UNCHANGED)
        assert image is not None, face_file
        ok, encoded = cv2.imencode('.png', image)
        assert ok, face_file
        chars.append({
            'id': cid,
            'name': name,
            'names': dict(entry.get('names') or {}),
            'face': entry.get('face') or ('face/character/' + cid),
        })
        faces[cid] = np.frombuffer(encoded.tobytes(), dtype=np.uint8)
    return chars, faces


def merge_custom_characters(chars):
    """Append custom characters when neither ID nor display name is already present."""
    known_ids = {str(c.get('id') or '') for c in chars}
    known_names = {c.get('name') for c in chars}
    extra_chars, extra_faces = custom_character_records()
    added_faces = {}
    for entry in extra_chars:
        if entry['id'] in known_ids or entry['name'] in known_names:
            continue
        chars.append(entry)
        added_faces[entry['id']] = extra_faces[entry['id']]
    return chars, added_faces


def main():
    data = records(get('/relics/list')['data'], get('/characters/list')['data'])
    upstream_chars = list(data['characters'])
    icons = sorted({item['icon'] for item in data['items']})
    with ThreadPoolExecutor(max_workers=6) as pool:
        faces = dict(zip((c['id'] for c in upstream_chars),
                         pool.map(fetch_icon, (c['face'] for c in upstream_chars))))
        art = dict(zip(icons, pool.map(fetch_icon, ('item/relics/' + icon for icon in icons))))
    merged_chars, custom_faces = merge_custom_characters(upstream_chars)
    data['characters'] = merged_chars
    faces.update(custom_faces)
    face_path = ROOT / 'rogue_equipment_faces.npz'
    with open(str(face_path) + '.tmp', 'wb') as stream:
        np.savez_compressed(stream, **faces)
    art_path = ROOT / 'rogue_equipment_icons.npz'
    with open(str(art_path) + '.tmp', 'wb') as stream:
        np.savez_compressed(stream, **art)
    path = ROOT / 'rogue_relics.json.gz'
    with gzip.GzipFile(str(path) + '.tmp', 'wb', mtime=0) as stream:
        stream.write(json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8'))
    os.replace(str(face_path) + '.tmp', str(face_path))
    os.replace(str(art_path) + '.tmp', str(art_path))
    os.replace(str(path) + '.tmp', str(path))
    print('%s equipment records, %s character faces -> %s'
          % (len(data['items']), len(faces), path))


if __name__ == '__main__':
    main()
