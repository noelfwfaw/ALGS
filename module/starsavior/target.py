# -*- coding: utf-8 -*-
"""刷初始目标：名字归一、达标判定。

目标本身**只来自 GUI**（`Starsavior2.Target` / `TargetCount`，见 `argument.yaml`），
这里不再读写 `config/state` 里的 json —— 一份配置只有一个来源，省得两边打架。

`count` = 需要**几只**（1 只 = 本体 0 星，4 只 = 满星），与
`scan_rescuers()` 返回的 `count = 1 + dups` 对齐。
"""
MIN_COUNT = 1
MAX_COUNT = 4

# 达标条件（`Starsavior2.TargetMode`）。
TARGET_MODE_ANY = 'any'   # 任意一个角色凑够它自己的数量就停（默认，刷初始最常用）
TARGET_MODE_ALL = 'all'   # 挂上的每一只都要凑够各自的数量
TARGET_MODES = (TARGET_MODE_ANY, TARGET_MODE_ALL)

# 繁→简（搬自半成品 log/ss_explore/library.py，两边保持一份口径）。
# 卡池名单是简体，账号里读出来的可能是繁体。
_SEED_ALIAS = (
    "亞亚 團团 麗丽 絲丝 爾尔 萊莱 諾诺 賽赛 夢梦 魘魇 軍军 隊队 會会 協协 貝贝 "
    "蘭兰 綺绮 緹缇 蘿萝 愛爱 貴贵 貓猫 陽阳 無无 藍蓝 綻绽 執执 繆缪 濟济 學学 "
    "寶宝 龍龙 鳳凤 鳥鸟 魚鱼 馬马 齊齐 齒齿 歲岁 萬万 與与 為为 產产 業业 "
    "樂乐 點点 戰战 擊击 靈灵 體体 實实 現现 華华 東东 車车 長长 門门 開开 關关"
)

# OCR 常见整名误读：繁简转换解决不了异体字。
# 账本里真实出现过「亚瑟拉@航行者救援团」，而卡池名单是「亚瑟菈」；
# PIPELINE.md 又把「瑟莱丝」写成了「瑟茉丝」。
NAME_ALIAS = {
    '亚瑟拉': '亚瑟菈',
    '瑟茉丝': '瑟莱丝',
}
TROUPE_ALIAS = {}


def _char_map():
    out = {}
    for pair in _SEED_ALIAS.split():
        if len(pair) == 2:
            out[pair[0]] = pair[1]
    return out


def norm(text):
    """比对用 key：去空格 + 统一间隔号 + 繁转简。"""
    text = (text or '').replace('・', '·').replace('。', '').strip()
    text = ''.join(text.split())
    cmap = _char_map()
    return ''.join(cmap.get(ch, ch) for ch in text)


def split_label(label):
    """'亚瑟菈@星光华尔兹' -> ('亚瑟菈', '星光华尔兹')。"""
    name, _, troupe = (label or '').partition('@')
    return name.strip(), troupe.strip()


def norm_label(label):
    """返回 (norm(名字), norm(团))；团为空表示只按名字判。"""
    name, troupe = split_label(label)
    name = NAME_ALIAS.get(name, name)
    troupe = TROUPE_ALIAS.get(troupe, troupe)
    return norm(name), norm(troupe)


def valid_target(label, count):
    """GUI 传进来的一条目标合不合法（写入账本前兜一层）。"""
    if not isinstance(label, str) or '@' not in label:
        return False
    if not isinstance(count, int) or isinstance(count, bool):
        return False
    return MIN_COUNT <= count <= MAX_COUNT


def check_targets(accounts, targets, mode=TARGET_MODE_ANY):
    """这一轮刷到的 SSR 是否达标。

    accounts: `scan_rescuers()` 的返回，每项 {label, dups, count}。
    targets: [{'label': '名字@团', 'count': 要几只}]，GUI 最多挂 7 只。
    mode: `any` = 任意一个角色凑够它自己的数量就达标；`all` = 每一只都要凑够各自的数量。
    returns: (ok, detail)，detail 每项 {label, need, got, hit}。

    ❗`any` 是刷初始的常规用法（挂 7 只候选 = 把这 7 只的概率加起来）；
      `all` 是"指定组合"，比如 4 只光奶 + 1 只别的，缺一只就重置重来。
    ❗同名异角色必须靠「团」区分：亚瑟菈@星光华尔兹（光奶）和
      亚瑟菈@航行者救援团是两个角色，只比名字会把后者误判成达标。
    """
    detail = []
    for target in targets:
        want_name, want_troupe = norm_label(target['label'])
        need = int(target.get('count', 1))
        got = 0
        for acc in accounts:
            have_name, have_troupe = norm_label(acc.get('label'))
            if have_name != want_name:
                continue
            if want_troupe and have_troupe != want_troupe:
                continue
            got += acc.get('count') or 1
        detail.append({
            'label': target['label'],
            'need': need,
            'got': got,
            'hit': got >= need,
        })

    # 一个 SSR 都没读到、或者一个目标都没挂 → 不达标（调用处本就不该走到这里）。
    if not accounts or not detail:
        return False, detail
    hits = [row['hit'] for row in detail]
    ok = all(hits) if mode == TARGET_MODE_ALL else any(hits)
    return ok, detail
