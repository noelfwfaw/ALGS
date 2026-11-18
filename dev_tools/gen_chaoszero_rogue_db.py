# -*- coding: utf-8 -*-
"""
Generate the 卡厄思 rogue event knowledge base.

The wiki (https://wiki.e7bot.top) publishes the whole encounter graph, but its API
answers are AES encrypted and the site is a SPA, so nothing can be read at task
time on a phone-less PC. We dump it once, offline, here.

Output: ``module/chaoszero/rogue_events.json.gz``

    {
      "id": {
        "name": "黏液洞窟",                 # 事件标题（运行时用 OCR 标题查表）
        "names": {"en": ..., "zhs": ..., "zht": ...},
        "pack": "uk_904_s01",             # 事件包 = 地图
        "chaos": "chaos_03",              # 主神/尺寸分组（共通事件为空）
        "size": "CHAOS_M",
        "options": [
          {"order": 1, "flavor": "...", "select_type": "RANDOM",
           "appear_conditions": [...], "conditions": [...],
           "success": [{"type": ..., "desc": ..., "amount": [min, max]}],
           "fail": [...]}
        ]
      }
    }

Records retain the source metadata under `raw` alongside the decision fields.
Embedded outcome destinations are stored by id and expanded by the inline generator.

Usage:
    toolkit/python.exe -m dev_tools.gen_chaoszero_rogue_db
"""
import base64
import gzip
import io
import json
import os
import re
import time

import requests

API = 'https://wiki.e7bot.top/api/czn'
# The AES key and the framing are lifted from the site's own bundle
# (js/index-*.js): the payload is base64 of `iv(16 bytes) || ciphertext`, AES-CBC,
# PKCS7, and the key string is the one the client hardcodes.
KEY = b'2egkWEkLvR9idARLvjqfJdWKfR24HJgY'
HEADERS = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}
OUTPUT = 'module/chaoszero/rogue_events.json.gz'
OUTCOME_KEYS = ('success_link_encounter_option_eff', 'fail_link_encounter_option_eff')


def decrypt(payload):
    """
    Decrypt one API answer.

    Args:
        payload (str): The base64 `data` field of the answer.

    Returns:
        object: The decoded JSON body.
    """
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad

    raw = base64.b64decode(payload)
    cipher = AES.new(KEY, AES.MODE_CBC, raw[:16])
    plain = unpad(cipher.decrypt(raw[16:]), AES.block_size)
    return json.loads(plain.decode('utf-8'))


def get(path, retries=3):
    """
    Fetch and decrypt one endpoint.

    Args:
        path (str): Path below `/api/czn`.
        retries (int): Attempts before giving up.

    Returns:
        object: Decoded body.
    """
    for attempt in range(retries):
        try:
            response = requests.get(API + path, headers=HEADERS, timeout=30)
            response.raise_for_status()
            body = response.json()
            return decrypt(body['data']) if body.get('encrypted') else body['data']
        except Exception as error:
            if attempt == retries - 1:
                raise
            print('  retry %s after %s' % (path, error))
            time.sleep(2)


def reward_list(rewards):
    """
    Flatten the numbered reward slots in source order.

    Args:
        rewards (dict): Raw option reward container.

    Returns:
        list[dict]: Type / text / amount of every non-empty reward.
    """
    result = []
    slots = (key for key in rewards if re.fullmatch(r'reward[0-9]+_reward', key))
    for slot in sorted(slots, key=lambda key: int(key[6:-7])):
        reward = rewards[slot] or {}
        reward_type = reward.get('reward_type')
        if not reward_type or reward_type == 'REWARD_TYPE_NONE':
            continue
        result.append({
            'type': reward_type,
            'desc': (reward.get('desc_option') or '').strip(),
            'amount': [reward.get('amount_min'), reward.get('amount_max')],
        })
    return result


def raw_option(option):
    """Keep the source fields and refer to embedded encounters by id."""
    raw = dict(option)
    for key in OUTCOME_KEYS:
        effect = option.get(key)
        child = (effect or {}).get('next_encounter')
        if isinstance(child, dict) and child.get('id'):
            raw[key] = dict(effect, next_encounter=child['id'])
    return raw


def parse_option(option):
    """
    Keep the decision fields and original metadata for one option.

    Args:
        option (dict): Raw option.

    Returns:
        dict: Order / flavour / conditions / success / fail.
    """
    conditions = []
    for condition in option.get('select_link_nb_conditions') or []:
        tooltip = (condition.get('encounter_option_tooltip') or '').strip()
        if tooltip:
            conditions.append(tooltip)
    return {
        'id': option.get('id') or '',
        'order': option.get('order'),
        'flavor': (option.get('simple_flavor_text') or '').strip(),
        'select_type': option.get('select_type') or '',
        'option_type': option.get('option_type') or '',
        'appear_conditions': option.get('appear_link_encounter_trigger_id') or [],
        'select_conditions': option.get('select_link_encounter_trigger_id') or [],
        'condition_ids': option.get('select_link_nb_condition_id') or [],
        'conditions': conditions,
        'success': reward_list(option.get(OUTCOME_KEYS[0]) or {}),
        'fail': reward_list(option.get(OUTCOME_KEYS[1]) or {}),
        'raw': raw_option(option),
    }


def parse_encounter(inner):
    """Keep visibility counts and classification alongside the option graph."""
    chaos = ((inner.get('chaos_collection_info') or {}).get('chaos') or {})
    options = [parse_option(option) for option in inner.get('options') or []]
    for option in options:
        conditions = option['appear_conditions']
        option['exclusive_with'] = []
        if len(conditions) == 1 and re.fullmatch(r'!?[\w@.\-]+', conditions[0]):
            condition = conditions[0]
            opposite = condition[1:] if condition.startswith('!') else '!' + condition
            option['exclusive_with'] = [other['id'] for other in options
                                        if other['appear_conditions'] == [opposite]]
    return {
        'name': inner.get('name') or '',
        'names': inner.get('names') or {},
        'pack': inner.get('link_encounter_pack_id') or '',
        'chaos': chaos.get('id') or '',
        'size': chaos.get('chaos_size') or '',
        'option_count': inner.get('option_count'),
        'option_count_max': inner.get('option_count_max'),
        'options': options,
        'raw': {key: value for key, value in inner.items() if key != 'options'},
    }


def main():
    """
    Dump every encounter with its options.
    """
    print('fetch encounter list')
    encounters = get('/encounters/list')
    rows = encounters.get('data') if isinstance(encounters, dict) else encounters
    if isinstance(rows, str):
        rows = json.loads(rows)
    print('  %s encounters' % len(rows))

    # Fetch metadata missing from older flattened caches.
    old = {}
    if os.path.exists(OUTPUT):
        with gzip.open(OUTPUT, 'rb') as handle:
            old = json.loads(handle.read().decode('utf-8'))
        print('  reuse %s cached encounters' % len(old))

    database = {}
    for index, row in enumerate(rows):
        encounter_id = row.get('id')
        if not encounter_id:
            continue
        cached = old.get(encounter_id) or {}
        if (cached.get('options') and cached.get('name') and 'option_count_max' in cached
                and 'raw' in cached
                and all('appear_conditions' in option and 'select_type' in option and 'raw' in option
                        for option in cached['options'])):
            record = dict(cached)
        else:
            detail = get('/encounters/%s' % encounter_id)
            body = detail.get('data') if isinstance(detail, dict) else detail
            if isinstance(body, str):
                body = json.loads(body)
            record = parse_encounter(body)
        chaos = ((row.get('chaos_collection_info') or {}).get('chaos') or {})
        record.update({
            # 事件包 = 地图（`uk_904_s01` 就是霧之城市那 38 个事件）；
            # 共通包（神秘 / 事件區域 / 四位神的传令兵）= 每张图都会出现的那 12 个。
            'pack': row.get('link_encounter_pack_id') or '',
            'chaos': chaos.get('id') or '',
            'size': chaos.get('chaos_size') or '',
        })
        database[encounter_id] = record
        if index % 50 == 0:
            print('  %s/%s' % (index, len(rows)))

    with io.open(OUTPUT, 'wb') as file:
        with gzip.GzipFile(fileobj=file, mode='wb', mtime=0) as handle:
            handle.write(json.dumps(database, ensure_ascii=False,
                                    sort_keys=True).encode('utf-8'))
    print('wrote %s encounters to %s' % (len(database), OUTPUT))


if __name__ == '__main__':
    main()
