# -*- coding: utf-8 -*-
"""
Event knowledge base for the 卡厄思 rogue.

The event pages of 卡厄思 are the only place where a run can gain 神之靈光一閃 / 重靈閃 /
複製 / 刪卡, so picking the option blindly (`RoguePick`, always the leftmost) throws away
most of the value of a run. The wiki (https://wiki.e7bot.top) publishes the whole encounter
graph; ``dev_tools/gen_chaoszero_rogue_db.py`` dumps it offline into
``rogue_events.json.gz`` and this module turns it into a decision.

Runtime flow: OCR the title line of every option card -> find the encounter whose option
set matches all of them -> score each matched option by its reward types -> return the
card to press. Anything uncertain returns ``None`` so the caller keeps `RoguePick`
(never guess: a wrong option can cost HP, pressure or add a curse card).
"""
import gzip
import json
import os
from difflib import SequenceMatcher

from module.logger import logger

from module.chaoszero.rogue_cards import normalize

DATA_FILE = os.path.join(os.path.dirname(__file__), 'rogue_events.json.gz')
# 单条 OCR 标题与库内选项名的相似度下限（繁体模型对 4 字标题常错 1 个字，约 0.75）
OPTION_MATCH = 0.55
# 反查事件时要求每一张卡都能对上，再取平均相似度最高的那个事件。
# ❗0.55 → 0.45：2026-11-15 实机 9 页里，`詢問在做什麼` 被 OCR 成 `詢間在做仕麽`
# （6 字错 3 字）只有 **0.50**，就这一条把整页判成"没有候选事件"；
# 而同页另外两张卡是 1.00 / 0.80，人工核对正确答案确实是 `uk_904_s01_02a`。
# 降到 0.45 能收下这种"错一半但仍是同一句话"的情况。
ENCOUNTER_MATCH = 0.45
# 两名候选分数差小于这个值就当作分不出来，退回 RoguePick
OPTION_MARGIN = 0.0
# 失败分支按这个权重计入（掷骰事件失败会扣东西，但成功收益通常更值）
FAIL_WEIGHT = 0.4

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
        logger.info('Event library loaded, %s encounters' % len(self.records))

    def identify(self, texts, packs=None):
        """
        Find the encounter whose options match every on-screen title.

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
            options = record.get('options') or []
            if len(options) < len(texts):
                continue
            total = 0.0
            usable = True
            for text in texts:
                score = max([ratio(text, normalize(option.get('flavor') or ''))
                             for option in options] or [0.0])
                if score < ENCOUNTER_MATCH:
                    usable = False
                    break
                total += score
            if not usable:
                continue
            mean = total / len(texts)
            if mean > best[2]:
                best = (key, record.get('name'), mean)
        return best

    def candidates(self, texts, packs=None, limit=5):
        """
        Rank every encounter whose options can cover all on-screen titles.

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
            options = record.get('options') or []
            if len(options) < len(texts):
                continue
            total = 0.0
            usable = True
            for text in texts:
                score = max([ratio(text, normalize(option.get('flavor') or ''))
                             for option in options] or [0.0])
                if score < ENCOUNTER_MATCH:
                    usable = False
                    break
                total += score
            if not usable:
                continue
            found.append((total / len(texts), key, record.get('name'),
                          record.get('pack')))
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
        that the pack table is off — the answer stays "no decision", so the caller falls
        back to `RoguePick` instead of trusting a foreign event.

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
