# -*- coding: utf-8 -*-
"""
Append the inline `next_encounter` sub-events into the rogue event database.

Why this exists
---------------
`/encounters/list` returns 406 encounters, but 207 options jump to another
encounter (`next_encounter_id`), and **158 of those targets are not in the 406**
(they are `xx-1` style sub-events, e.g. `uk_402_s01_11a-1`). The list/detail API
never returns them as standalone records.

They *are* present, fully populated (including their own `options`), inside the
parent option's effect object as `next_encounter`. The upstream README claims
that object has no `options`; measurement says otherwise, so we can lift them
straight out of the dumped detail JSON.

Without this, the bot can identify the parent event but not the sub-event it
jumps into, so a user pick recorded for the sub-event could never be applied.

Usage:
    toolkit/python.exe -m dev_tools.gen_chaoszero_rogue_db_inline \
        --source .workbuddy/data/encounters.detail.json
"""
import argparse
import gzip
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(ROOT, 'module', 'chaoszero', 'rogue_events.json.gz')


def reward_list(rewards):
    """Flatten `reward0..4_reward` into the compact list the engine reads."""
    result = []
    for index in range(5):
        reward = rewards.get('reward%s_reward' % index) or {}
        reward_type = reward.get('reward_type')
        if not reward_type or reward_type == 'REWARD_TYPE_NONE':
            continue
        result.append({
            'type': reward_type,
            'desc': (reward.get('desc_option') or '').strip(),
            'amount': [reward.get('amount_min'), reward.get('amount_max')],
        })
    return result


def parse_option(option):
    """Keep only what the decision engine needs from one option."""
    conditions = []
    for condition in option.get('select_link_nb_conditions') or []:
        tooltip = (condition.get('encounter_option_tooltip') or '').strip()
        if tooltip:
            conditions.append(tooltip)
    return {
        'order': option.get('order'),
        'flavor': (option.get('simple_flavor_text') or '').strip(),
        'conditions': conditions,
        'success': reward_list(option.get('success_link_encounter_option_eff') or {}),
        'fail': reward_list(option.get('fail_link_encounter_option_eff') or {}),
    }


def parse_encounter(inner):
    """Turn one inline encounter object into a database record."""
    info = inner.get('chaos_collection_info') or {}
    chaos = info.get('chaos') or {}
    return {
        'name': inner.get('name') or '',
        'names': inner.get('names') or {},
        'pack': inner.get('link_encounter_pack_id') or '',
        'chaos': chaos.get('id') or '',
        'size': chaos.get('chaos_size') or '',
        'options': [parse_option(option) for option in (inner.get('options') or [])],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source',
                        default=os.path.join(ROOT, '.workbuddy', 'data',
                                             'encounters.detail.json'),
                        help='Dumped /encounters/{id} payloads, keyed by id.')
    options = parser.parse_args()

    if not os.path.exists(options.source):
        print('source %s is missing, nothing to do' % options.source)
        return 1
    source = json.load(io.open(options.source, encoding='utf-8'))
    print('source: %s encounters' % len(source))

    database = {}
    if os.path.exists(OUTPUT):
        with gzip.open(OUTPUT, 'rb') as handle:
            database = json.loads(handle.read().decode('utf-8'))
    print('database: %s encounters before' % len(database))

    added = 0
    skipped = 0
    seen = set()

    def absorb(inner, depth):
        """递归吸收内嵌事件：子事件里还可能再嵌一层（如 `09a-1-1`）。

        Args:
            inner (dict): 内嵌的 encounter 对象。
            depth (int): 还能往下走几层（防自环，数据里有指回自己的）。
        """
        nonlocal added, skipped
        inner_id = inner.get('id')
        if not inner_id or inner_id in seen:
            return
        seen.add(inner_id)
        if inner_id not in database:
            record = parse_encounter(inner)
            if record['name'] or record['options']:
                database[inner_id] = record
                added += 1
            else:
                skipped += 1
        else:
            skipped += 1
        if depth <= 0:
            return
        for option in (inner.get('options') or []):
            for tag in ('success_link_encounter_option_eff',
                        'fail_link_encounter_option_eff'):
                deeper = (option.get(tag) or {}).get('next_encounter') or {}
                if deeper.get('id'):
                    absorb(deeper, depth - 1)

    for encounter in source.values():
        for option in (encounter.get('options') or []):
            for tag in ('success_link_encounter_option_eff',
                        'fail_link_encounter_option_eff'):
                inner = (option.get(tag) or {}).get('next_encounter') or {}
                if inner.get('id'):
                    # 深度 3 够覆盖实测最深的 `xx-1-1`（三层）；`seen` 兜住自环
                    absorb(inner, 3)

    with gzip.open(OUTPUT, 'wb') as handle:
        handle.write(json.dumps(database, ensure_ascii=False).encode('utf-8'))
    print('database: %s encounters after (+%s new, %s skipped)'
          % (len(database), added, skipped))
    print('with options: %s' % sum(1 for record in database.values()
                                   if record.get('options')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
