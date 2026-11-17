"""Refresh the offline equipment/character index from E7BOT; stars are ignored."""

import gzip
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests

from dev_tools.gen_chaoszero_rogue_db import get


ROOT = Path('module/chaoszero')
TYPES = {'EQUIP_WEAPON': 0, 'EQUIP_ARMOR': 1, 'EQUIP_ACC': 2}
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
                      'unique': relic['rarity'] == 'RARITY_UNIQUE'})
        if relic['id'] in GAME_NAMES:
            items[-1]['aliases'] = [GAME_NAMES[relic['id']]]
    chars = [{'id': c['id'], 'name': c['name'], 'names': c.get('names', {}),
              'face': c.get('card_icon_name') or 'face/character/face_character_' + c['id']}
             for c in characters if c.get('char_type') == 'CHAR_COMBATANT']
    assert items and chars and len({i['id'] for i in items}) == len(items)
    return {'source': 'https://wiki.e7bot.top/#/czn/relics',
            'items': items, 'characters': chars}


def fetch_face(character):
    response = requests.get('https://wiki.e7bot.top/api/assets/file/czn/data/'
                            + character['face'] + '.webp', timeout=30)
    response.raise_for_status()
    import cv2
    blob = np.frombuffer(response.content, dtype=np.uint8)
    assert cv2.imdecode(blob, cv2.IMREAD_GRAYSCALE) is not None, character['id']
    return character['id'], blob


def main():
    data = records(get('/relics/list')['data'], get('/characters/list')['data'])
    with ThreadPoolExecutor(max_workers=6) as pool:
        faces = dict(pool.map(fetch_face, data['characters']))
    face_path = ROOT / 'rogue_equipment_faces.npz'
    with open(str(face_path) + '.tmp', 'wb') as stream:
        np.savez_compressed(stream, **faces)
    path = ROOT / 'rogue_relics.json.gz'
    with gzip.GzipFile(str(path) + '.tmp', 'wb', mtime=0) as stream:
        stream.write(json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8'))
    os.replace(str(face_path) + '.tmp', str(face_path))
    os.replace(str(path) + '.tmp', str(path))
    print('%s equipment records, %s character faces -> %s'
          % (len(data['items']), len(faces), path))


if __name__ == '__main__':
    main()
