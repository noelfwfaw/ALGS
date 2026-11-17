# -*- coding: utf-8 -*-
"""
Refresh event classifications, including inline `next_encounter` sub-events.

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

from dev_tools.gen_chaoszero_rogue_db import parse_encounter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(ROOT, 'module', 'chaoszero', 'rogue_events.json.gz')


def classify_selector(node, records):
    """Add source classifications to the existing selector without changing picks."""
    source = records.get(node.get('id'))
    if source:
        options = node.get('options') or []
        raw_options = source.get('options') or []
        if not options and raw_options:
            return  # The selector stops expanding recursive links at its depth limit.
        if len(options) != len(raw_options) or any(
                option.get('order') != raw.get('order')
                for option, raw in zip(options, raw_options)):
            raise ValueError('Selector options differ from source: %s' % node.get('id'))
        node['option_count'] = source.get('option_count')
        node['option_count_max'] = source.get('option_count_max')
        for option, parsed in zip(options, parse_encounter(source)['options']):
            for key in ('id', 'select_type', 'option_type', 'appear_conditions',
                        'select_conditions', 'condition_ids', 'conditions', 'exclusive_with'):
                option[key] = parsed[key]
            if parsed['option_type'] == 'ATTACK':
                option['text'] = '攻击'
    for option in node.get('options') or []:
        for key in ('nextDetail', 'next'):
            if isinstance(option.get(key), dict):
                classify_selector(option[key], records)


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
    with io.open(options.source, encoding='utf-8') as handle:
        source = json.load(handle)
    print('source: %s encounters' % len(source))

    database = {}
    if os.path.exists(OUTPUT):
        with gzip.open(OUTPUT, 'rb') as handle:
            database = json.loads(handle.read().decode('utf-8'))
    print('database: %s encounters before' % len(database))

    added = 0
    refreshed = 0
    skipped = 0
    seen = set()
    records = {}

    def absorb(inner, depth):
        """递归吸收内嵌事件：子事件里还可能再嵌一层（如 `09a-1-1`）。

        Args:
            inner (dict): 内嵌的 encounter 对象。
            depth (int): 还能往下走几层（防自环，数据里有指回自己的）。
        """
        nonlocal added, refreshed, skipped
        if inner.get('options') is None:
            return  # References without a populated option list must not erase full records.
        inner_id = inner.get('id')
        if not inner_id or inner_id in seen:
            return
        seen.add(inner_id)
        records[inner_id] = inner
        if inner_id not in database:
            record = parse_encounter(inner)
            if record['name'] or record['options']:
                database[inner_id] = record
                added += 1
            else:
                skipped += 1
        elif 'options' in inner:
            # Existing pack/name fixes survive; only option metadata is refreshed.
            parsed = parse_encounter(inner)
            database[inner_id].update({key: parsed[key] for key in
                                       ('options', 'option_count', 'option_count_max')})
            refreshed += 1
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
        absorb(encounter, 4)

    selector_dir = os.path.join(ROOT, 'dev_tools', 'rogue_events')
    selector_file = os.path.join(selector_dir, 'events.json')
    selector = None
    if os.path.exists(selector_file):
        with io.open(selector_file, encoding='utf-8') as handle:
            selector = json.load(handle)
        for pack in selector.get('packs') or []:
            for event in pack.get('events') or []:
                classify_selector(event, records)

    with gzip.open(OUTPUT, 'wb') as handle:
        handle.write(json.dumps(database, ensure_ascii=False).encode('utf-8'))
    print('database: %s encounters after (+%s new, %s refreshed, %s skipped)'
          % (len(database), added, refreshed, skipped))
    print('with options: %s' % sum(1 for record in database.values()
                                   if record.get('options')))
    if selector is not None:
        with io.open(selector_file, 'w', encoding='utf-8') as handle:
            json.dump(selector, handle, ensure_ascii=False, indent=1)
        with io.open(os.path.join(selector_dir, 'events.js'), 'w', encoding='utf-8') as handle:
            handle.write('window.EVENTS_DATA = ' + json.dumps(selector, ensure_ascii=False) + ';\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
