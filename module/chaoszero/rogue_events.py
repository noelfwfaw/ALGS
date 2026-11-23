# -*- coding: utf-8 -*-
"""
Event knowledge base for the 卡厄思 rogue.

The event pages of 卡厄思 are the only place where a run can gain 神之靈光一閃 / 重靈閃 /
複製 / 刪卡, so picking the option blindly (`RoguePick`, always the leftmost) throws away
most of the value of a run. The wiki (https://wiki.e7bot.top) publishes the whole encounter
graph; ``dev_tools/gen_chaoszero_rogue_db.py`` dumps it offline into
``rogue_events.json.gz`` and this module turns it into a decision.

The database keeps all possible branches, their appearance conditions and source types;
they are not necessarily visible together. Runtime matches the visible titles to an event
and an explicitly configured choice. Unavailable or uncertain choices stop for user review.
"""
import gzip
import json
import os
from difflib import SequenceMatcher

from filelock import FileLock, Timeout

from deploy.atomic import atomic_read_bytes, atomic_write
from module.chaoszero.rogue_spark_catalog import normalize
from module.logger import logger

DATA_FILE = os.path.join(os.path.dirname(__file__), 'rogue_events.json.gz')
SELECTOR_DATA_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'dev_tools', 'rogue_events', 'events.json')
)
EVENT_SEEN_FILE = './config/rogue/rogue_event_seen.json'
_CATALOG_CACHE = {}
# These terminal pages have identical option conditions and outcomes in the raw data.
SHARED_CHOICE_GROUPS = (
    ('uk_300_s02_03b', 'uk_300_s02_03a-1', 'uk_300_s02_03c-1'),
    ('uk_sys_s02_01a', 'uk_sys_s02_01b', 'uk_sys_s02_01c', 'uk_sys_s02_01d'),
    ('uk_302_s02_07a-1', 'uk_302_s02_07a-3', 'uk_302_s02_07a-4'),
    ('uk_904_s01_07a-1', 'uk_904_s01_07b-1', 'uk_904_s01_07c-1'),
    ('uk_904_s01_07d-1', 'uk_904_s01_07e-2'),
)
SHARED_CHOICES = {event_id: group for group in SHARED_CHOICE_GROUPS for event_id in group}


def _shared_choice_signature(record):
    if not record.get('raw') or not record.get('options'):
        return None
    source_ids = {'id', 'chaos_collection_info', 'link_encounter_set_id'}
    source = {key: value for key, value in record['raw'].items() if key not in source_ids}
    outcomes = ('success_link_encounter_option_eff', 'fail_link_encounter_option_eff')
    option_ids = {'id', 'link_encounter_id'} | {key + '_id' for key in outcomes}
    options = []
    for option in record['options']:
        if not option.get('raw'):
            return None
        raw = {key: value for key, value in option['raw'].items() if key not in option_ids}
        for key in outcomes:
            if key not in raw:
                return None
            effect = raw[key]
            if effect:
                if effect.get('next_encounter') or effect.get('next_encounter_id'):
                    return None
                raw[key] = {k: v for k, v in effect.items() if k not in ('id', 'link_encounter_option_id')}
        parsed = {key: value for key, value in option.items() if key not in ('id', 'raw')}
        options.append((parsed, raw))
    return record['pack'], record['name'], source, options


# 单条 OCR 标题与库内选项名的相似度下限（繁体模型对 4 字标题常错 1 个字，约 0.75）
OPTION_MATCH = 0.55
# 反查事件时要求每一张卡都能对上，再取平均相似度最高的那个事件。
# ❗0.55 → 0.45：2026-11-15 实机 9 页里，`詢問在做什麼` 被 OCR 成 `詢間在做仕麽`
# （6 字错 3 字）只有 **0.50**，就这一条把整页判成"没有候选事件"；
# 而同页另外两张卡是 1.00 / 0.80，人工核对正确答案确实是 `uk_904_s01_02a`。
# 降到 0.45 能收下这种"错一半但仍是同一句话"的情况。
ENCOUNTER_MATCH = 0.45
# 两名候选分数差小于这个值就不做决策，由调用方停机。
OPTION_MARGIN = 0.0
# 失败分支按这个权重计入（掷骰事件失败会扣东西，但成功收益通常更值）
FAIL_WEIGHT = 0.4

PRIORITY_TIER_NAMES = {
    1: '指定复制',
    2: '随机复制',
    3: '指定神闪',
    4: '随机神闪',
    5: '指定灵闪',
    6: '随机灵闪',
    7: '卡牌删除',
    8: '获得装备',
    9: '提高HP上限',
    10: '获得信用点',
    11: '降低压力',
    12: '恢复HP',
    13: '卡牌转换',
}
NO_PRIORITY_TIER = 99
GOD_SPARK_WORDS = ('神之', '賦予', '賦子', '赋予', '戴奧斯', '維托', '尼希隆', '賽克瑞德', '凱爾肯')
RANDOM_WORDS = ('隨機', '随机')
_REWARD_TYPE_TIER = {
    'CARD_COPY_HAVE_SELECT': 1,
    'CARD_COPY_HAVE_SELECT_TABOO': 1,
    'CARD_COPY_SELECT_3_1': 2,
    'CARD_COPY_CHAR_SELECT_3_1': 2,
    'ADD_R_SPARK_GOD_SELECT': 3,
    'ADD_R_SPARK_GOD_RANDOM': 4,
    'R_SPARK_SELECT': 5,
    'COMBATANT_SPARK_SELECT': 5,
    'R_SPARK_RANDOM': 6,
    'COMBATANT_SPARK_RANDOM': 6,
    'CARD_REMOVE_HAVE_SELECT': 7,
    'CARD_REMOVE_HAVE_RANDOM': 7,
    'EQUIPMENT_ID': 8,
    'EQUIPMENT_RANDOM': 8,
    'EQUIPMENT_PRE_RANDOM': 8,
    'REINFORCE_EQUIPMENT_ID': 8,
    'REINFORCE_EQUIPMENT_PRE_RANDOM': 8,
    'REINFORCE_EQUIPMENT_HAVE_SELECT': 8,
    'CARD_TRANSFORM_HAVE_SELECT_ID': 13,
    'CARD_TRANSFORM_HAVE_PRE_SELECT': 13,
    'CARD_TRANSFORM_HAVE_SELECT': 13,
}
_COPY_WORDS = ('複製', '复制')
_SPARK_WORDS = ('靈光', '一閃', '灵光', '一闪')
_REMOVE_WORDS = ('移除', '刪除', '删除')
_EQUIP_WORDS = ('裝備', '装备')
_CREDIT_WORDS = ('信用點', '信用点')
_STRESS_WORDS = ('壓力', '压力')
_HEAL_WORDS = ('恢復', '恢複', '恢复')
_TRANSFORM_WORDS = ('轉換', '转换')


def _is_equip_removal(text):
    """Return whether normalized `text` describes removing an equipment rather than a card."""
    for word in _REMOVE_WORDS:
        start = 0
        while True:
            idx = text.find(word, start)
            if idx < 0:
                break
            window = text[idx:idx + 8]
            if any(eq in window for eq in _EQUIP_WORDS) and '卡牌' not in window:
                return True
            start = idx + len(word)
    return False


def _single_keyword_priority_tier(text):
    """Classify one normalized text block into priority tiers 1..13, or NO_PRIORITY_TIER."""
    text = normalize(text or '')
    if not text:
        return NO_PRIORITY_TIER
    best = NO_PRIORITY_TIER
    if any(word in text for word in _COPY_WORDS):
        best = min(best, 2 if any(word in text for word in ('隨機', '随机', '其中')) else 1)
    if any(word in text for word in _SPARK_WORDS):
        is_god = any(word in text for word in GOD_SPARK_WORDS)
        is_rand = any(word in text for word in RANDOM_WORDS)
        if is_god and is_rand:
            best = min(best, 4)
        elif is_god:
            best = min(best, 3)
        elif is_rand:
            best = min(best, 6)
        else:
            best = min(best, 5)
    has_remove = any(word in text for word in _REMOVE_WORDS)
    has_equip = any(word in text for word in _EQUIP_WORDS)
    equip_removal = has_remove and has_equip and _is_equip_removal(text)
    if has_remove and '危險因子' not in text and not equip_removal:
        if not (has_equip and '卡牌' not in text and '獲得' not in text and '获得' not in text):
            best = min(best, 7)
    if has_equip and not equip_removal:
        if not (has_remove and '獲得' not in text and '获得' not in text and '強化' not in text and '强化' not in text):
            best = min(best, 8)
    if '最大' in text:
        after = text[text.find('最大'):]
        if ('增加' in after or '提高' in after) and not any(
                bad in after for bad in ('最大減少', '最大店減少', '最大减少')):
            best = min(best, 9)
    for word in _CREDIT_WORDS:
        idx = text.find(word)
        if idx >= 0:
            after = text[idx:idx + 12]
            before = text[max(0, idx - 6):idx]
            if (('增加' in after or '獲得' in before or '获得' in before)
                    and not any(bad in after for bad in ('減少', '减少'))
                    and not any(bad in before for bad in ('消耗', '失去'))):
                best = min(best, 10)
            break
    for word in _STRESS_WORDS:
        idx = text.find(word)
        if idx >= 0:
            after = text[idx:idx + 10]
            if any(good in after for good in ('減少', '减少', '降低')):
                best = min(best, 11)
            break
    if any(word in text for word in _HEAL_WORDS):
        best = min(best, 12)
    if any(word in text for word in _TRANSFORM_WORDS):
        best = min(best, 13)
    return best


def keyword_priority_tier(text):
    """
    Classify Chinese effect/body text into the 13-tier priority table.

    Multi-line OCR text may separate multiple effects by newline, so both individual
    lines and the joined normalized string are evaluated and the best tier is returned.
    """
    if not text:
        return NO_PRIORITY_TIER
    if not isinstance(text, str):
        return NO_PRIORITY_TIER
    best = _single_keyword_priority_tier(text)
    if '\n' in text:
        for line in text.splitlines():
            best = min(best, _single_keyword_priority_tier(line))
    return best


def reward_priority_tier(reward):
    """Classify one structured DB reward entry into priority tiers 1..13, or NO_PRIORITY_TIER."""
    if not isinstance(reward, dict):
        return NO_PRIORITY_TIER
    name = reward.get('type')
    if name in _REWARD_TYPE_TIER:
        return _REWARD_TYPE_TIER[name]
    amount = reward.get('amount') or (None, None)
    value = amount[1] if len(amount) > 1 and amount[1] is not None else (amount[0] if amount else None)
    if name == 'MAX_HP_PCT':
        return 9 if value is not None and value > 0 else NO_PRIORITY_TIER
    if name == 'CREDIT_VALUE':
        return 10 if value is not None and value > 0 else NO_PRIORITY_TIER
    if name == 'STRESS_VALUE':
        return 11 if value is not None and value < 0 else NO_PRIORITY_TIER
    if name == 'HP_PCT':
        return 12 if value is not None and value > 0 else NO_PRIORITY_TIER
    return keyword_priority_tier(reward.get('desc') or '')

# 每张图都会出现的共通事件包：神秘(3) + 事件區域(1) + 四位神的传令兵(1+5+1+1) = 12 个事件，
# 就是网站事件页里「其他 (12)」那一栏（用户 2026-11-15 确认）。
COMMON_PACKS = (
    'uk_000_s01',
    'uk_evt_s01',
    'uk_sys_s01',
    'uk_sys_s02',
    'uk_sys_s03',
    'uk_sys_s04',
)

# 事件包 = 地图。只遍历当前地图的事件，能大幅降低 OCR 标题撞到别张图同名事件的概率
# （2026-11-15 用户要求；霧之城市 = uk_904_s01 共 38 个事件，与网站数字一致）。
# ⚠ 審判之沼 / 降臨的混沌 / 雙星之影 / 藍壺 没有包名可查（packs/list 里是 8xx 的旧 id），
# 是按 chaos 尺寸 + 事件内容对上的，所以 `pick()` 认不出时还会退回全库再试一次。
PACK_WORLD = {
    '藍壺': ('uk_300_s02',),
    '雙星之影': ('uk_302_s02',),
    '霧之城市': ('uk_904_s01',),
    '審判之沼': ('uk_905_s02',),
    '降臨的混沌': ('uk_900_s02',),
    '第0研究所': ('uk_400_s01', 'uk_e01_s01'),
    '燃燒的生命': ('uk_401_s01',),
    '虛像劇場': ('uk_402_s01',),
    '萬花筒孵化場': ('uk_403_s01',),
    '天上防護牆': ('uk_404_s01',),
    '賽季卡厄思': ('uk_404_s01',),
    '赛季卡厄思': ('uk_404_s01',),
}


def packs_for_world(world):
    """
    Event packs that can show up on one map.

    Args:
        world (str): World name as configured (`RogueWorld`), e.g. 霧之城市.

    Returns:
        tuple[str]: Pack ids, or None when the world is unknown (do not scope).
    """
    own = PACK_WORLD.get(world or '')
    if not own:
        return None
    return COMMON_PACKS + tuple(own)


WORLD_GROUPS = (
    ('藍壺', ('uk_300_s02',)),
    ('雙星之影', ('uk_302_s02',)),
    ('霧之城市', ('uk_904_s01',)),
    ('審判之沼', ('uk_905_s02',)),
    ('降臨的混沌', ('uk_900_s02',)),
    ('第0研究所', ('uk_400_s01', 'uk_e01_s01')),
    ('燃燒的生命', ('uk_401_s01',)),
    ('虛像劇場', ('uk_402_s01',)),
    ('萬花筒孵化場', ('uk_403_s01',)),
    ('天上防護牆', ('uk_404_s01',)),
    ('其他', COMMON_PACKS),
)


def event_catalog(selector_file=None):
    """Return `(groups, root_ids, parent_map)` built from the selector's root events."""
    if selector_file is None:
        selector_file = SELECTOR_DATA_FILE
    key = os.path.abspath(selector_file)
    if key in _CATALOG_CACHE:
        return _CATALOG_CACHE[key]
    if not os.path.exists(key):
        return [], set(), {}
    try:
        with open(key, encoding='utf-8-sig') as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        logger.warning('Failed to read event catalog %s: %s' % (key, error))
        return [], set(), {}

    pack_events = {}
    root_ids = set()
    parent_map = {}
    packs = data.get('packs') or []
    for pack in packs:
        pack_id = pack.get('id')
        if not pack_id:
            continue
        entries = pack_events.setdefault(pack_id, [])
        for event in pack.get('events') or []:
            root_id = event.get('id')
            if not root_id:
                continue
            root_ids.add(root_id)
            entries.append((root_id, event.get('name') or root_id))

    for pack in packs:
        for event in pack.get('events') or []:
            root_id = event.get('id')
            if not root_id:
                continue
            stack = [event]
            visited = {root_id}
            while stack:
                node = stack.pop()
                for option in node.get('options') or []:
                    nxt = option.get('nextDetail') or (
                        option.get('next') if isinstance(option.get('next'), dict) else None
                    )
                    if not nxt:
                        continue
                    child_id = nxt.get('id')
                    if child_id and child_id not in visited:
                        visited.add(child_id)
                        if child_id not in root_ids:
                            parent_map.setdefault(child_id, root_id)
                        stack.append(nxt)

    assigned = set()
    groups = []
    for world, pack_ids in WORLD_GROUPS:
        events = []
        for pack_id in pack_ids:
            assigned.add(pack_id)
            events.extend(pack_events.get(pack_id, ()))
        if events:
            groups.append((world, events))
    leftover = [item for pack_id, items in pack_events.items() if pack_id not in assigned for item in items]
    if leftover:
        for index, (world, events) in enumerate(groups):
            if world == '其他':
                groups[index] = (world, events + leftover)
                break
        else:
            groups.append(('其他', leftover))

    result = (groups, root_ids, parent_map)
    _CATALOG_CACHE[key] = result
    return result


def resolve_root_event(event_id, selector_file=None):
    """Map a confirmed encounter (including sub-events) back to its root event ID."""
    if not event_id:
        return None
    if selector_file is None:
        selector_file = SELECTOR_DATA_FILE
    _, root_ids, parent_map = event_catalog(selector_file)
    if event_id in root_ids:
        return event_id
    return parent_map.get(event_id, event_id)


def load_seen_events(path=None):
    """Load the set of recorded root event IDs from disk."""
    if path is None:
        path = EVENT_SEEN_FILE
    try:
        content = atomic_read_bytes(path)
    except OSError as error:
        logger.warning('Failed to read %s: %s' % (path, error))
        return set()
    if not content:
        return set()
    try:
        payload = json.loads(content.decode('utf-8-sig'))
    except ValueError as error:
        logger.warning('Invalid event recorder file %s: %s' % (path, error))
        return set()
    items = payload.get('seen') if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return set()
    return {str(item) for item in items if item}


def record_seen_event(event_id, path=None, selector_file=None):
    """Persist one confirmed event ID without duplicates; returns True if newly added."""
    if path is None:
        path = EVENT_SEEN_FILE
    if selector_file is None:
        selector_file = SELECTOR_DATA_FILE
    root_id = resolve_root_event(event_id, selector_file=selector_file)
    if not root_id:
        return False
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with FileLock(f'{path}.lock', timeout=2):
            seen = load_seen_events(path)
            if root_id in seen:
                return False
            seen.add(root_id)
            atomic_write(path, json.dumps({'version': 1, 'seen': sorted(seen)}, ensure_ascii=False, indent=1))
        return True
    except (OSError, Timeout) as error:
        logger.warning('Failed to update %s: %s' % (path, error))
        return False


def clear_seen_events(path=None):
    """Reset the recorded event kinds back to empty."""
    if path is None:
        path = EVENT_SEEN_FILE
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with FileLock(f'{path}.lock', timeout=2):
            atomic_write(path, json.dumps({'version': 1, 'seen': []}, ensure_ascii=False, indent=1))
        return True
    except (OSError, Timeout) as error:
        logger.warning('Failed to clear %s: %s' % (path, error))
        return False


def summarize_seen_events(seen=None, path=None, selector_file=None):
    """Return per-world seen counts and per-event flags in selector order."""
    if path is None:
        path = EVENT_SEEN_FILE
    if selector_file is None:
        selector_file = SELECTOR_DATA_FILE
    if seen is None:
        seen = load_seen_events(path)
    seen_roots = {resolve_root_event(eid, selector_file=selector_file) for eid in seen}
    groups, _, _ = event_catalog(selector_file)
    summary = []
    for world, events in groups:
        entries = [(ev_id, ev_name, ev_id in seen_roots) for ev_id, ev_name in events]
        summary.append({
            'world': world,
            'seen': sum(1 for _, _, matched in entries if matched),
            'total': len(entries),
            'events': entries,
        })
    return summary

# 奖励类型的基础分：卡组质量 > 卡牌数量 > 资源 > 装备。
# 神闪 > 重灵閃/變形 > 複製 > 角色靈閃 > 靈閃 > 刪卡 > 抽卡 > 资源。
TYPE_SCORE = {
    'ADD_R_SPARK_GOD_SELECT': 100,
    'ADD_R_SPARK_GOD_RANDOM': 80,
    'CARD_TRANSFORM_HAVE_SELECT_ID': 70,
    'CARD_TRANSFORM_HAVE_PRE_SELECT': 65,
    'CARD_TRANSFORM_HAVE_SELECT': 60,
    'CARD_COPY_HAVE_SELECT': 62,
    'CARD_COPY_SELECT_3_1': 55,
    'CARD_COPY_CHAR_SELECT_3_1': 55,
    'CARD_COPY_HAVE_SELECT_TABOO': 50,
    'COMBATANT_SPARK_SELECT': 50,
    'COMBATANT_SPARK_RANDOM': 40,
    'R_SPARK_SELECT': 42,
    'R_SPARK_RANDOM': 30,
    'CARD_REMOVE_HAVE_SELECT': 45,
    'CARD_REMOVE_HAVE_RANDOM': 25,
    'CARD_SELECT_1_3': 22,
    'CARD_SELECT_1_N': 22,
    'CARD_ID': 18,
    'CARD_RANDOM': 18,
    'CARD_RANDOM_DESIRE': 15,
    'CARD_PRE_RANDOM': 10,
    'FATE_ID': 15,
    'MAX_HP_PCT': 12,
    'EQUIPMENT_ID': 8,
    'EQUIPMENT_RANDOM': 8,
    'EQUIPMENT_PRE_RANDOM': 6,
    'REINFORCE_EQUIPMENT_HAVE_SELECT': 8,
    'REINFORCE_EQUIPMENT_ID': 6,
    'REINFORCE_EQUIPMENT_PRE_RANDOM': 4,
    'CREDIT_VALUE_PCT': -10,
    'EQUIPMENT_REMOVE_HAVE_ID': -10,
    'STRESS_VALUE_RAND_1': -12,
    'CARD_ID_CURSE': -60,
}

# 这些类型靠 amount 的正负决定好坏（desc 里 增加/減少 与 amount 符号一致）。
# 元组 = (amount 为正时的分, amount 为负时的分)：壓力是"增加"才坏，所以符号相反。
SIGN_SCORE = {
    'HP_PCT': (10, -30),
    'MAX_HP_PCT': (12, -20),
    'STRESS_VALUE': (-25, 15),
    'CREDIT_VALUE': (8, -6),
}


def ratio(text, other):
    """
    Similarity of two normalized strings.

    Args:
        text (str): Normalized text.
        other (str): Normalized text.

    Returns:
        float: 0~1.
    """
    if not text or not other:
        return 0.0
    return SequenceMatcher(None, text, other).ratio()


class EventLibrary:
    """
    The encounter table plus the option scorer.

    Usage::

        library = EventLibrary()
        index, option, score, raw = library.pick(['搜索屁體', '攝取'])
    """

    def __init__(self, file=DATA_FILE):
        self.file = file
        self.records = {}
        self.parent_edges = {}
        self._load()

    def _load(self):
        """
        Read the gzipped dump once.
        """
        if not os.path.exists(self.file):
            logger.warning('Event database %s is missing' % self.file)
            return
        with gzip.open(self.file, 'rt', encoding='utf-8') as file:
            self.records = json.load(file)
        self.parent_edges = {}
        for parent_id, record in self.records.items():
            for option in record.get('options', []):
                raw = option.get('raw') or {}
                for field in ('success_link_encounter_option_eff', 'fail_link_encounter_option_eff'):
                    nxt = (raw.get(field) or {}).get('next_encounter')
                    if isinstance(nxt, str) and nxt != parent_id and nxt in self.records:
                        self.parent_edges.setdefault(nxt, []).append((parent_id, option))
        logger.info('Event library loaded, %s encounters' % len(self.records))

    def shared_choice_ids(self, event_id):
        group = SHARED_CHOICES.get(event_id, (event_id,))
        if len(group) == 1:
            return group
        signature = _shared_choice_signature(self.records.get(group[0], {}))
        if signature and all(_shared_choice_signature(self.records.get(key, {})) == signature for key in group[1:]):
            return group
        return (event_id,)

    @staticmethod
    def _assign_options_with_score(texts, options):
        """Return `(mean_ratio, assignment)` mapping each card to `(opt_idx, ratio)`."""
        if len(options) < len(texts) or not texts:
            return 0.0, ()
        norm_options = [normalize(option.get('flavor') or '') for option in options]
        rows = []
        for text in texts:
            matches = [(idx, ratio(text, title)) for idx, title in enumerate(norm_options)]
            matches = [(idx, sc) for idx, sc in matches if sc >= ENCOUNTER_MATCH]
            if not matches:
                return 0.0, ()
            matches.sort(key=lambda item: -item[1])
            rows.append(matches)
        best = 0.0
        best_assign = ()
        used = set()
        current = [None] * len(rows)

        def search(pos, total):
            nonlocal best, best_assign
            if pos == len(rows):
                mean = total / len(rows)
                if mean > best:
                    best = mean
                    best_assign = tuple(current)
                return
            rem_max = sum(rows[k][0][1] for k in range(pos, len(rows)))
            if (total + rem_max) / len(rows) <= best:
                return
            for idx, sc in rows[pos]:
                if idx not in used:
                    used.add(idx)
                    current[pos] = (idx, sc)
                    search(pos + 1, total + sc)
                    used.remove(idx)

        search(0, 0.0)
        return best, best_assign

    @staticmethod
    def _encounter_match_score(texts, options):
        """Return max mean similarity assigning each screen card to a distinct option, or 0.0."""
        mean, _ = EventLibrary._assign_options_with_score(texts, options)
        return mean

    def assign_options(self, texts, options):
        """Assign each visible card title in `texts` to a matching option dict or None."""
        if not texts or not options:
            return [None] * len(texts or ())
        _, assignment = self._assign_options_with_score(texts, options)
        if assignment:
            return [options[idx] for idx, _ in assignment]
        norm_options = [normalize(option.get('flavor') or '') for option in options]
        used = set()
        result = []
        for text in texts:
            best = None
            best_sc = 0.0
            for idx, (option, title) in enumerate(zip(options, norm_options)):
                sc = ratio(text, title)
                if sc >= ENCOUNTER_MATCH and (sc > best_sc or (sc == best_sc and best in used and idx not in used)):
                    if idx not in used or best is None:
                        best = idx
                        best_sc = sc
            if best is None:
                result.append(None)
            else:
                used.add(best)
                result.append(options[best])
        return result

    def option_priority_tier(self, option, depth=0, seen=None):
        """Return best priority tier 1..13 for `option` from rewards and linked followups."""
        if not option or option.get('order') == 9999 or 'ATTACK' in (
                option.get('select_type'), option.get('option_type')):
            return NO_PRIORITY_TIER
        best = NO_PRIORITY_TIER
        for reward in option.get('success') or ():
            best = min(best, reward_priority_tier(reward))
        if depth < 2:
            raw = option.get('raw') or {}
            nxt_id = (raw.get('success_link_encounter_option_eff') or {}).get('next_encounter')
            visited = set() if seen is None else seen
            if isinstance(nxt_id, str) and nxt_id not in visited and nxt_id in self.records:
                next_seen = visited | {nxt_id}
                for child in self.records[nxt_id].get('options') or ():
                    best = min(best, self.option_priority_tier(child, depth=depth + 1, seen=next_seen))
        return best

    def fallback_pick(self, texts, packs=None, body_texts=None):
        """
        Choose an option card by the 13-tier keyword/reward priority when rules fail.

        Combines per-card OCR body text (`body_texts`) with matched DB option rewards
        and linked followups. Returns a decision dict or None when no card matches
        any of the 13 priority tiers.
        """
        if not texts:
            return None
        ranked = self.candidates(texts, packs, limit=None) if self.records else []
        if not ranked and packs and self.records:
            ranked = self.candidates(texts, None, limit=None)
        top_candidates = []
        if ranked:
            top_mean = ranked[0][0]
            top_candidates = [item for item in ranked if item[0] >= top_mean - 0.05][:3]
        assignments = [
            (enc_id, name, self.assign_options(texts, self.records[enc_id].get('options') or ()))
            for _, enc_id, name, _ in top_candidates
        ]

        picks = []
        for index, text in enumerate(texts):
            body = body_texts[index] if body_texts and index < len(body_texts) else ''
            ocr_tier = keyword_priority_tier(body)
            db_tier = NO_PRIORITY_TIER
            best_opt = None
            best_enc = None
            best_name = None
            best_score = float('-inf')

            matched_any_candidate = False
            for enc_id, name, opts in assignments:
                opt = opts[index]
                if opt is None:
                    continue
                matched_any_candidate = True
                tier = self.option_priority_tier(opt)
                sc = self.score(opt)
                if (tier, -sc) < (db_tier, -best_score):
                    db_tier = tier
                    best_opt = opt
                    best_enc = enc_id
                    best_name = name
                    best_score = sc

            if not matched_any_candidate and self.records:
                opt, sc = self.match(text, None, packs)
                if opt and sc >= 0.70:
                    tier = self.option_priority_tier(opt)
                    if tier < NO_PRIORITY_TIER:
                        db_tier = tier
                        best_opt = opt
                        best_score = self.score(opt)

            tier = min(ocr_tier, db_tier)
            if tier < NO_PRIORITY_TIER:
                if best_score == float('-inf'):
                    best_score = 0.0
                picks.append((
                    tier, -best_score, index, best_enc, best_name, best_opt, text, body
                ))

        if not picks:
            return None
        picks.sort(key=lambda item: (item[0], item[1], item[2]))
        tier, _, index, enc_id, name, opt, text, body = picks[0]
        target = normalize(opt.get('flavor') or '') if opt else (text or normalize(body.replace('\n', '')))
        return {
            'source': 'keyword_fallback',
            'id': enc_id,
            'name': name,
            'round': 1,
            'order': opt.get('order') if opt else None,
            'target': target,
            'position': index + 1,
            'text': text,
            'tier': tier,
            'tier_name': PRIORITY_TIER_NAMES[tier],
            'body': body,
        }

    def identify(self, texts, packs=None):
        """
        Find the encounter whose distinct options match every on-screen title.

        Args:
            texts (list[str]): Normalized option titles, one per card.
            packs (tuple[str]): Only look at these event packs (= this map), or None for all.

        Returns:
            tuple: (encounter id, encounter name, mean ratio) or (None, None, 0.0).
        """
        best = (None, None, 0.0)
        for key, record in self.records.items():
            if packs and record.get('pack') not in packs:
                continue
            mean = self._encounter_match_score(texts, record.get('options') or [])
            if mean > best[2]:
                best = (key, record.get('name'), mean)
        return best

    def candidates(self, texts, packs=None, limit=5):
        """
        Rank every encounter whose distinct options can cover all on-screen titles.

        和 `identify()` 的区别：那个只返回最高分的一个；这里返回**排好序的候选列表**，
        用来判断"是不是唯一"以及"正确答案排第几"（2026-11-15 用户要求统计识别正确率）。

        Args:
            texts (list[str]): Normalized option titles, one per card.
            packs (tuple[str]): Only look at these event packs, or None for all.
            limit (int): How many to return.

        Returns:
            list[tuple]: [(mean ratio, encounter id, name, pack), ...], best first.
        """
        if not self.records or not texts:
            return []
        found = []
        for key, record in self.records.items():
            if packs and record.get('pack') not in packs:
                continue
            mean = self._encounter_match_score(texts, record.get('options') or [])
            if mean > 0.0:
                found.append((mean, key, record.get('name'), record.get('pack')))
        found.sort(key=lambda item: -item[0])
        return found[:limit]

    def match(self, text, record=None, packs=None):
        """
        Match one on-screen title to an option.

        Args:
            text (str): Normalized title.
            record (dict): Encounter record to search in, or None to search everything.
            packs (tuple[str]): When `record` is None, only search these event packs.

        Returns:
            tuple: (option dict, ratio) or (None, 0.0).
        """
        if record:
            pool = record.get('options') or []
        else:
            pool = []
            for item in self.records.values():
                if packs and item.get('pack') not in packs:
                    continue
                pool.extend(item.get('options') or [])
        best = (None, 0.0)
        for option in pool:
            score = ratio(text, normalize(option.get('flavor') or ''))
            if score > best[1]:
                best = (option, score)
        if best[1] < OPTION_MATCH:
            return None, best[1]
        return best

    def score(self, option):
        """
        Score one option's rewards.

        Args:
            option (dict): Option record with `success` and `fail` reward lists.

        Returns:
            float: Positive is good for the save, negative is a cost.
        """
        total = 0.0
        for reward in option.get('success') or []:
            total += self.reward_score(reward)
        for reward in option.get('fail') or []:
            penalty = self.reward_score(reward)
            if penalty < 0:
                total += penalty * FAIL_WEIGHT
        return total

    @staticmethod
    def reward_score(reward):
        """
        Score one reward entry.

        Args:
            reward (dict): {type, desc, amount}.

        Returns:
            float: Score.
        """
        name = reward.get('type')
        amount = reward.get('amount') or [None, None]
        value = amount[1] if amount[1] is not None else amount[0]
        if name in SIGN_SCORE:
            if value is None:
                return 0.0
            good, bad = SIGN_SCORE[name]
            return good if value >= 0 else bad
        return float(TYPE_SCORE.get(name, 0))

    def pick(self, texts, packs=None):
        """
        Choose which option card to press.

        Only the event packs of the current map (`packs`) are searched: the site splits
        the events per map (霧之城市 keeps its 38 in `uk_904_s01`), and matching against
        all 406 invites a wrong answer from a map that is not even on screen
        (2026-11-15, user rule: 打这个图就只遍历这图的事件). When the map's events all
        miss, the option titles are still compared against every map, but only to warn
        that the pack table is off — the answer stays "no decision". The live configured
        event handler stops for review instead of selecting a foreign event or position.

        Args:
            texts (list[str]): Normalized option titles, one per card, in screen order.
            packs (tuple[str]): Packs of the current map, or None to search everything.

        Returns:
            tuple: (index, option, score, ratio) or None when nothing is certain.
        """
        if not self.records or not texts:
            return None
        result = self._pick(texts, packs)
        if result is None and packs:
            key, name, found = self.identify(texts, None)
            record = self.records.get(key) if key else None
            if record:
                logger.warning(
                    'The options look like %s (%s, pack %s, %.2f) which is not a pack of this '
                    'map, keep RoguePick' % (name, key, record.get('pack'), found))
            else:
                logger.info('No event in the scope of this map, keep RoguePick')
        return result

    def _pick(self, texts, packs):
        """
        One pass of `pick()`.

        Args:
            texts (list[str]): Normalized option titles.
            packs (tuple[str]): Packs to search, or None for everything.

        Returns:
            tuple: (index, option, score, ratio) or None.
        """
        key, name, found = self.identify(texts, packs)
        record = self.records.get(key) if key else None
        if record:
            logger.info('Event %s (%s) matched %.2f' % (key, name, found))
        else:
            logger.info('Event not identified, match options one by one')

        candidates = []
        for index, text in enumerate(texts):
            option, score = self.match(text, record, packs)
            if not option:
                logger.info('Option %s `%s` not matched (%.2f)' % (index + 1, text, score))
                continue
            value = self.score(option)
            candidates.append((index, option, value, score))
            logger.info('Option %s `%s` -> %s, score %.1f (%.2f)'
                        % (index + 1, text, option.get('flavor'), value, score))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[2], item[0]))
        index, option, value, score = candidates[0]
        if value <= 0:
            # 全是代价（掉血 / 加压 / 塞诅咒卡 / 花信用点数）就交给 RoguePick，
            # 别为了"有数据"去主动挑一个坏选项。
            logger.info('No option scores positive (best %.1f), keep RoguePick' % value)
            return None
        if len(candidates) > 1 and value - candidates[1][2] < OPTION_MARGIN:
            # 分数相同就取最左（sort 已按 index 升序，平手时最左自然排第一）
            logger.info('Two options score the same, keep the left one')
        return index, option, value, score
