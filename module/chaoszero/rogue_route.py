# -*- coding: utf-8 -*-
"""卡厄思肉鸽：路线读取与规划。

这里只做"看图 + 算分"，不碰设备，方便离线用截图反复验证。

路线图有两个视图：

* 3D 视图（默认）：左下角小地图面板 (20,455)-(490,700) 画着整条剩余路线，
  右侧平台立着本次可达节点的图标卡（青色 ? = 事件，粉色交叉剑 = 战斗，
  紫色骷髅 = 精英，橙色火焰 = 休息），点平台本体移动。
* 2D 预览（点小地图面板右上角的 ⊕）：整屏的菱形节点图，按颜色分类最稳。

所以规划用 2D 预览读数，执行时对照 3D 视图里立着的那张图标卡。
"""
import os

import cv2
import numpy as np

# 2D 预览里节点所在的整块区域，避开顶部血条和底部按钮
ROUTE_AREA = (0, 80, 1280, 700)

# 上一次读到的当前位置，用于诊断。
LAST_PIN_X = None

# 节点颜色（HSV 色相）到类型的映射，2026-11-14 用 map14_pin.png 实测 18/18 正确
KIND_BATTLE = 'battle'
KIND_EVENT = 'event'
KIND_REST = 'rest'
KIND_ELITE = 'elite'
# ❗航点（信标）和休息点**颜色完全一样**（都是橙色菱形），只有内部图标不同：
# 休息是火焰，航点是指南针。用户 2026-11-15 指出「这种不是休息点，是航点」。
# 只靠色相会把两者混成一个，规划就会把"存档点"当成"能回血的休息点"去绕。
KIND_BEACON = 'beacon'
# 航点/补给这类浅色节点：色相不在上面几段里（白针形图标），但 3D 地图上同样
# 立着一张卡，认不出类型时按这个走，免得"没有可点的节点卡"卡死
# （2026-11-14 21:1x 连报 6 次 No node card）。
KIND_UNKNOWN = 'unknown'
KIND_NAMES = {
    KIND_BATTLE: '戰鬥',
    KIND_EVENT: '事件',
    KIND_REST: '休息',
    KIND_ELITE: '精英',
    KIND_BEACON: '航点',
    KIND_UNKNOWN: '未知',
}
HUE_RANGES = {
    KIND_BATTLE: ((155, 179), (0, 8)),
    KIND_EVENT: ((85, 105),),
    KIND_REST: ((10, 30),),
    KIND_ELITE: ((120, 150),),
}
# 节点是横放的菱形，实测面积 1200~2600、宽 55~100、高 30~70、宽高比 1.3~2.4
NODE_AREA = (1200, 2600)
NODE_WIDTH = (55, 100)
NODE_HEIGHT = (30, 70)
NODE_RATIO = (1.3, 2.4)
NODE_SATURATION = 90
# 亮度阈值。试过降到 70 去捞"未点亮的暗列"（实测暗橙 max 97 / 暗紫 113），
# 确实能从 4 列读到 6 列，但会引入假节点（实测多出一个 x=758 的孤点，
# 把一整列拆成 tier 3/4）—— 假节点会让规划走错，比少读两列更糟。保持 90。
NODE_VALUE = 90
ROUTE_GLOW_OPENING = np.ones((9, 4), np.uint8)

# 同一层的 x 允许差这么多像素；不同层之间的 x 间距实测 164。
# ❗从 40 放到 70：偶发会读出一个**不在网格上**的假节点（实测 mu_route4.png 的
# `(1056,399)`，真列是 997 和 1161，它卡在中间差 59），40 会让它单独成一层、
# 把后面的列全挤位。164 的列距远大于 70，放大到 70 不会把相邻两列合并。
TIER_GAP = 70

# 连线只出现在"相邻行"或"跨一行的斜线"上：实测行距 ≈108，而真实连线的
# 高度差最大到 109（t1 y=474 → t2 y=583），跨两行的是 216，中间没有。
# 所以 125 是"上一行的节点能连到下一行哪些节点"的判据（见 link_tiers，兜底用）。
ROW_GAP = 108
LINK_DY = 125

# The line lies between the diamond tips, below the colored tile centers.
EDGE_LIGHT = 185
EDGE_TIP_X = 53
EDGE_TIP_Y = 8
EDGE_SAMPLES = np.linspace(.12, .88, 17)
EDGE_Y_OFFSETS = np.arange(-7, 8)
TIER_DISTANCE = (120, 190)
# 预览图的列间距实测固定 164 px，扫描时两屏位移只可能是它的整数倍
TIER_SPACING = 164
SHIFT_TOLERANCE = 28
SHIFT_ROW_TOLERANCE = 20
SHIFT_STEPS = 8

# 规划权重：分越高越优先。用户默认"均衡"，另外两档给"优先进攻""优先事件"
ROUTE_BALANCE = '均衡'
ROUTE_BATTLE = '优先进攻'
ROUTE_EVENT = '优先事件'
ROUTE_STYLES = (ROUTE_BALANCE, ROUTE_BATTLE, ROUTE_EVENT)

# 3D 视图里立在平台上的图标卡：竖着的一张窄卡
CARD_AREA = (600, 80, 1280, 660)
CARD_AREA_MIN = 2500
CARD_WIDTH = (36, 120)
CARD_HEIGHT = (66, 180)
CARD_RATIO = (1.2, 3.4)
# 认不出色相的卡（航点/补给）：浅白、高亮、四周暗一圈的立卡
# 浅白节点卡的亮度下限、饱和度上限，以及"四周暗一圈"的对比要求
CARD_PALE_VALUE = 150
CARD_SATURATION_MAX = 70
CARD_CONTRAST = 35
# 卡片插在平台外角，平台本体在卡的左下方
PLATFORM_OFFSET = (-130, 65)

# 2D 预览整张图比一屏宽，可以左右拖（用户 2026-11-14 20:1x 指出）。
# 拖动一屏约 700 px，这里按节点重合情况估实际位移；同一格在两次读到的坐标
# 差小于这个容差就当成同一个节点。
ROUTE_SCROLL_STEP = 600
ROUTE_DEDUPE = 55
NODE_DEDUPE = 40

# 休息点右上角会挂一个白色小招牌（有的休息点没有 = 没商店）。招牌和火焰图标离得开：
# 火焰的橙色 min 通道只有 ~114，招牌是白金色 min 通道 >170，所以用 min 通道阈值就能分开。
# 实测（2026-11-15，route_scr_05/09/23 预览帧）：招牌中心在节点中心 (+32,-36) 附近，
# 白块 16~19 x 16~34 px、面积 76~258；没有招牌的休息点在这个窗口里一个亮块都没有。
SHOP_WINDOW = (8, 60, 60, 14)  # 相对节点中心：x+8 ~ x+60，y-60 ~ y-14
# ❗170 太高：招牌的亮度**不统一**，实测 mu_route4.png 上同一个画面里
# R4 的招牌能被认出来（原本就是 170 档），而最右 R6 的招牌实测只有
# (162,159,128) / (157,155,124)，min 通道 118~128 —— 被 170 整块判死，
# 于是那个带商店的休息点掉成普通休息（60 分），规划根本不会往那儿走。
# 背景实测 min 只有 15~20，降到 110 不会误收。
SHOP_LIGHT = 110
SHOP_AREA = (50, 350)
SHOP_WIDTH = (10, 30)
SHOP_HEIGHT = (8, 45)
# 带商店的休息点额外加分。这个数决定"值不值得为商店绕路"：
#   15 → 25+15=40，和事件持平，规划**从不**特意走商店；
#   35 → 60，比事件高，但只要别的分支累计分更高就还是不过去；
#   90 → 115，**压过任何组合**，DP 会不惜绕路先经过商店。
# 用户 2026-11-15 明确要求「优先走有休息点的路线」（拿商店删卡），所以取 90。
# 如果哪天不想要这个偏置，把它降回 15 即可，`score()` 的其余逻辑不用动。
SHOP_SCORE = 90

BASE_SCORE = {
    # ❗`KIND_REST` 25 → 60：用户 2026-11-15 明确要求「**有休息点就走休息**」。
    # 25 的时候它低于战斗(30)和事件(40)，实测 `mu_route3.png` 上右下角就摆着一个
    # 休息点，规划却绕去走同排的战斗。60 高于事件，休息点会稳定优先。
    # 只改「均衡」这一档：「优先进攻 / 优先事件」是用户主动选的偏向，不该被覆盖。
    # `KIND_BEACON`（航点/信标）给 10：它只提供存档、不给资源，比战斗(30)/事件(40)
    # 都低，但比"该躲的精英"(-38) 高。不加这一档会 KeyError —— 因为 `get(kind, 0)`
    # 有默认值，实际会算成 0，比精英还低，规划会刻意绕开存档点，那是错的。
    # ❗`KIND_UNKNOWN` 从 35/30/35 降到 **15/15/15**：它是"认不出颜色"的兜底
    # （航点/补给是浅白针形，但**认不出的精英卡也会掉进这里**）。
    # 35 比精英(12)还高，于是"3D 地图上认不出紫色"的精英会被当成好节点直接走 ——
    # 2026-11-16 用户报「实际走了精英，日志却全是 戰鬥」，这是最可能的成因。
    # 15 仍高于精英(12)，航点还能走得到，但不再压过战斗(30)/事件(40)。
    ROUTE_BALANCE: {KIND_BATTLE: 30, KIND_EVENT: 40, KIND_REST: 60, KIND_ELITE: 12,
                    KIND_BEACON: 10, KIND_UNKNOWN: 15},
    ROUTE_BATTLE: {KIND_BATTLE: 45, KIND_EVENT: 25, KIND_REST: 20, KIND_ELITE: 15,
                   KIND_BEACON: 10, KIND_UNKNOWN: 15},
    ROUTE_EVENT: {KIND_BATTLE: 20, KIND_EVENT: 50, KIND_REST: 25, KIND_ELITE: 10,
                  KIND_BEACON: 10, KIND_UNKNOWN: 15},
}


class RouteNode(object):
    """2D 预览里的一个节点。"""

    def __init__(self, x, y, kind):
        self.x = int(x)
        self.y = int(y)
        self.kind = kind
        self.tier = 0
        self.row = 0
        # 休息点有没有带商店（带商店才能删卡），2D 预览的招牌判出来
        self.shop = False
        # 同一颗节点在不同屏里可能被判成不同类型（紫精英的边缘会落进别的色相段），
        # 合并时按位置归并、按投票数定类型。
        self.votes = {}

    def __repr__(self):
        return 'RouteNode(%s, %s, %s%s)' % (self.x, self.y, self.kind,
                                            ', shop' if self.shop else '')


class RouteCard(object):
    """3D 地图上立着的节点图标卡，卡上的图形就是这一格的类型。"""

    def __init__(self, x, y, kind, width, height):
        self.x = int(x)
        self.y = int(y)
        self.kind = kind
        self.width = int(width)
        self.height = int(height)
        # 3D 立卡上暂时没测出商店招牌的位置，先保持 False（预览节点的 shop 是量过的）
        self.shop = False

    def platform_point(self):
        """卡片插在平台外角上，平台本体在卡的左下方，实测偏移 (-130, +65)。"""
        return self.x + PLATFORM_OFFSET[0], self.y + PLATFORM_OFFSET[1]

    def __repr__(self):
        return 'RouteCard(%s, %s, %s)' % (self.x, self.y, self.kind)


def _node_mask(hue, sat, val, ranges):
    mask = np.zeros(hue.shape, bool)
    for low, high in ranges:
        mask |= (hue >= low) & (hue <= high)
    mask &= (sat >= NODE_SATURATION) & (val >= NODE_VALUE)
    return mask


# 橙色菱形里靠**图标**区分休息点/航点：火焰 = 休息（能回血、可能带商店），
# 指南针 = 航点（信标，只是存档点、没有收益）。两者颜色完全一样，色相判据分不开。
# 44x44 灰度模板，实测 6/6 全对（真图标 0.985~1.000，另一个 0.773~0.819），
# 取分数大的那个就行，不需要绝对阈值。
ICON_HALF = 22
ICON_PAD = 6
ICON_REST_FILE = './assets/chaoszero/chaoszero/ROGUE_ICON_REST.png'
ICON_BEACON_FILE = './assets/chaoszero/chaoszero/ROGUE_ICON_BEACON.png'
_ICON_CACHE = {}


def _icon_template(path):
    """读入并缓存图标灰度模板；缺失时返回 None。"""
    if path in _ICON_CACHE:
        return _ICON_CACHE[path]
    template = None
    if os.path.exists(path):
        image = cv2.imread(path)
        if image is not None:
            template = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _ICON_CACHE[path] = template
    return template


# 队伍当前所在的格子会插一颗**蓝色水滴 pin**（实测 (185,222,223)：三通道都亮、
# 偏青；节点本体是橙色 (165,97,44)，商店招牌是金黄色 b 低，都不会误判）。
# ❗这一格**不能算进路线**：用户 2026-11-15 指出「最左边是已经走到了的位置，
# 不应该算在内，不然就会认为下一步走的是休息点，因为现在已经在休息点了」。
# 实测判据命中时 310~312 个像素，其余节点全 0，分离度很干净。
PIN_FILE = './assets/chaoszero/chaoszero/ROGUE_ROUTE_PIN.png'


def read_pin(image):
    """直接找图钉。开局脚下的灰格没有彩色节点可用于定位。"""
    template = _icon_template(PIN_FILE)
    if template is None:
        return None
    # 打开预览时，当前位置在左侧；避开右侧未来节点和顶部 HUD。
    r, g, b = image[92:638, :440, :3].astype(np.int16).transpose(2, 0, 1)
    mask = (r >= 120) & (g >= 185) & (b >= 185) & (g - r >= 17) & (b - r >= 17) & (abs(g - b) <= 45)
    result = cv2.matchTemplate(mask.astype(np.uint8), template, cv2.TM_CCORR_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(result)
    if score >= .88:
        return RouteNode(x + template.shape[1] // 2, y + 92 + template.shape[0] + 13, None)
    return None


def icon_kind(image, x, y):
    """橙色菱形的内部图标是火焰还是指南针。

    Args:
        image (np.ndarray): RGB 图像。
        x (int): 节点中心 x。
        y (int): 节点中心 y。

    Returns:
        str: KIND_REST 或 KIND_BEACON（模板缺失时一律按休息处理）。
    """
    rest = _icon_template(ICON_REST_FILE)
    beacon = _icon_template(ICON_BEACON_FILE)
    if rest is None or beacon is None:
        return KIND_REST
    grey = cv2.cvtColor(image[:, :, :3], cv2.COLOR_RGB2GRAY)
    half = ICON_HALF + ICON_PAD
    x = int(x)          # `read_nodes` 传进来的是 numpy 标量，slice 不认
    y = int(y)
    patch = grey[max(0, y - half):y + half, max(0, x - half):x + half]
    if patch.shape[0] < rest.shape[0] or patch.shape[1] < rest.shape[1]:
        return KIND_REST
    score_rest = cv2.matchTemplate(patch, rest, cv2.TM_CCOEFF_NORMED).max()
    score_beacon = cv2.matchTemplate(patch, beacon, cv2.TM_CCOEFF_NORMED).max()
    return KIND_REST if score_rest >= score_beacon else KIND_BEACON


def has_shop(image, x, y):
    """节点右上角有没有那个白色小商店招牌。

    Args:
        image (np.ndarray): RGB 图像。
        x (int): 节点中心的 x。
        y (int): 节点中心的 y。

    Returns:
        bool: 有招牌 = 这个休息点带商店（能删卡）。
    """
    left, right, top, bottom = SHOP_WINDOW
    x1 = max(0, int(x - left))
    y1 = max(0, int(y - top))
    x2 = int(x + right)
    y2 = max(y1 + 1, int(y - bottom))
    if y2 <= y1 or x2 <= x1:
        return False
    patch = np.asarray(image[y1:y2, x1:x2, :3], dtype=np.int32)
    mask = (patch.min(axis=2) > SHOP_LIGHT).astype('uint8')
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for index in range(1, count):
        area = int(stats[index][4])
        width = int(stats[index][2])
        height = int(stats[index][3])
        if not SHOP_AREA[0] <= area <= SHOP_AREA[1]:
            continue
        if not SHOP_WIDTH[0] <= width <= SHOP_WIDTH[1]:
            continue
        if not SHOP_HEIGHT[0] <= height <= SHOP_HEIGHT[1]:
            continue
        return True
    return False


def _trim_top_right_badge(labels, index, stats_row, x1, y1):
    """Strip a top-right purple enhancement badge if it merges with a diamond component."""
    lx, ty, width, height, area = [int(v) for v in stats_row[:5]]
    if not (NODE_WIDTH[0] <= width <= 115 and area >= NODE_AREA[0]):
        return area, width, height, None, None
    sub = (labels[ty:ty + height, lx:lx + width] == index)
    left_ys = np.where(sub[:, :width // 2].any(axis=1))[0]
    if not len(left_ys) or int(left_ys[0]) <= 5:
        return area, width, height, None, None
    y_top, y_bot = int(left_ys[0]), int(left_ys[-1])
    true_h = y_bot - y_top + 1
    cleaned = sub.copy()
    cleaned[:y_top, :] = False
    cleaned[y_top:y_top + int(true_h * 0.45), int(width * 0.62):] = False
    ys, xs = np.where(cleaned)
    if not len(xs):
        return area, width, height, None, None
    return (
        int(len(xs)),
        int(xs.max() - xs.min() + 1),
        int(ys.max() - ys.min() + 1),
        float(lx + xs.mean() + x1),
        float(ty + ys.mean() + y1),
    )


def read_nodes(image):
    """从 2D 预览的截图里读出所有节点，按填充顺序返回 RouteNode 列表。

    Args:
        image (np.ndarray): RGB 图像，device.image 的格式。

    Returns:
        list[RouteNode]: 已填好 tier（列序号）和 row（行序号）的节点。
    """
    global LAST_PIN_X
    pin = read_pin(image)
    LAST_PIN_X = pin.x if pin is not None else None
    if pin is None:
        return []
    x1, y1, x2, y2 = ROUTE_AREA
    patch = image[y1:y2, x1:x2, :3]
    hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV).astype(np.int32)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    raw = []
    for kind, ranges in HUE_RANGES.items():
        mask = _node_mask(hue, sat, val, ranges).astype(np.uint8)
        if kind == KIND_EVENT:
            # The cyan current-column highlight can join an event diamond to the background.
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, ROUTE_GLOW_OPENING)
        count, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        for index in range(1, count):
            area, width, height, cx, cy = _trim_top_right_badge(
                labels, index, stats[index], x1, y1
            )
            if not NODE_AREA[0] <= area <= NODE_AREA[1]:
                continue
            if not NODE_WIDTH[0] <= width <= NODE_WIDTH[1]:
                continue
            if not NODE_HEIGHT[0] <= height <= NODE_HEIGHT[1]:
                continue
            if not NODE_RATIO[0] <= width / float(height) <= NODE_RATIO[1]:
                continue
            if cx is None:
                cx = cents[index][0] + x1
                cy = cents[index][1] + y1
            raw.append((area, cx, cy, kind))

    # 同一颗菱形会被好几个色相段各抓到一个块（紫精英的边缘能同时落进橙色和
    # 青色段），位置重合但类型不同 —— 按块面积从大到小只留最大的一块，
    # 否则一列会被读成 5~6 个节点（2026-11-14 20:2x 读到 62 个，实际只有一半）。
    raw.sort(key=lambda item: -item[0])
    nodes = []
    for area, x, y, kind in raw:
        duplicate = False
        for other in nodes:
            if abs(other.x - x) <= NODE_DEDUPE and abs(other.y - y) <= NODE_DEDUPE:
                duplicate = True
                break
        if duplicate:
            continue
        node = RouteNode(x, y, kind)
        if kind == KIND_REST:
            # 橙色菱形还得分火焰(休息)和指南针(航点)，颜色一样、只能看图标。
            node.kind = icon_kind(image, x, y)
            if node.kind == KIND_REST:
                node.shop = has_shop(image, x, y)
        nodes.append(node)

    nodes = [node for node in nodes if node.x > LAST_PIN_X + TIER_GAP]
    nodes.sort(key=lambda node: (node.x, node.y))
    _fill_grid(nodes)
    # 丢掉不在列网格上的假节点，再重排一次（列号可能变）。
    nodes = drop_outliers(nodes)
    _fill_grid(nodes)
    # Start the graph only from diamonds connected to the current pin.
    white = image[:, :, :3].min(axis=2) > EDGE_LIGHT
    reachable = [node for node in nodes if node.tier == 0 and _along_line(white, pin, node)]
    if not reachable:
        return []
    return reachable + [node for node in nodes if node.tier != 0]


def _fill_grid(nodes):
    """按 x 归类成列（tier），列内按 y 排成行（row）。"""
    tiers = []
    for node in nodes:
        if tiers and node.x - tiers[-1][-1] <= TIER_GAP:
            tiers[-1].append(node.x)
        else:
            tiers.append([node.x])
    edges = [int(round(sum(tier) / float(len(tier)))) for tier in tiers]

    for node in nodes:
        node.tier = min(range(len(edges)), key=lambda index: abs(edges[index] - node.x))
    for index in range(len(edges)):
        column = sorted([node for node in nodes if node.tier == index], key=lambda node: node.y)
        for row, node in enumerate(column):
            node.row = row


def fill_grid(nodes):
    """把拼好的整张图按 x 重新分列（tier），列内按 y 排行（row）。"""
    _fill_grid(nodes)


def drop_outliers(nodes, tol=45):
    """丢掉"不在列网格上"的假节点。

    列距实测 164，同一列的 x 抖动只有 ±10。偶尔会读出一个卡在中间的东西
    （实测 mu_route4.png 的 `(1056, 399)`，真列是 997 / 1161），它会被归进最近的
    列、但 x 仍然偏 59px —— `read_edges` 拿这个假坐标去采样，边就会算错。

    判据：同列里 x 与**中位数**差超过 tol 的丢掉。单节点列不过滤（没有参照）。

    Args:
        nodes (list[RouteNode]): 已 fill_grid 的节点。
        tol (int): 允许偏离列中位数的像素数。

    Returns:
        list[RouteNode]: 过滤后的节点（顺序不变）。
    """
    by_tier = {}
    for node in nodes:
        by_tier.setdefault(node.tier, []).append(node)

    keep = []
    for tier in sorted(by_tier):
        column = by_tier[tier]
        if len(column) < 2:
            keep.extend(column)
            continue
        xs = sorted(node.x for node in column)
        middle = xs[len(xs) // 2]
        for node in column:
            if abs(node.x - middle) <= tol:
                keep.append(node)
    keep.sort(key=lambda node: (node.x, node.y))
    return keep


def estimate_shift(previous, current, low=150, high=1600):
    """相邻两屏之间地图被拖动了多少像素（正数 = 内容往左移了这么多）。

    预览图是按固定间距排的网格，所以位移只能是网格间距（164 px）的整数倍。
    只在这些候选里挑"两屏重合节点最多"的那个，命中数达不到两屏较小一方的
    一半就当没重合（返回 None）。

    以前取"所有同类型、同一行的 old.x - new.x 中位数"，一屏 7 个节点时会把
    164 和 328 混在一起，估出一个不存在的位移，拼图越拼越多
    （2026-11-14 21:51 一轮读出 35 个节点、其中 17 个"休息"全是假的）。

    Args:
        previous (list[RouteNode]): 上一屏的节点。
        current (list[RouteNode]): 这一屏的节点。
        low (int): 合理位移下限。
        high (int): 合理位移上限。

    Returns:
        int: 位移；估不出来返回 None。
    """
    if not previous or not current:
        return None
    best_shift = None
    best_hits = 0
    for step in range(1, SHIFT_STEPS + 1):
        shift = TIER_SPACING * step
        if shift < low or shift > high:
            continue
        hits = 0
        for old in previous:
            for new in current:
                if abs(old.x - shift - new.x) > SHIFT_TOLERANCE:
                    continue
                if abs(old.y - new.y) > SHIFT_ROW_TOLERANCE:
                    continue
                hits += 1
                break
        if hits > best_hits:
            best_shift, best_hits = shift, hits
    # ❗门槛原来是"较小一方的一半"，太苛刻：`read_nodes` 在同一屏上会抖
    # （2026-11-15 16:50 实测同一屏读出 22 / 30 / 18 个），一半经常够不着，
    # 于是 `estimate_shift` 返回 None → 调用方直接 `break`，整张图只读到一屏。
    # 放到三分之一，仍然要求"明显有多颗对上"，但不会被识别抖动打回 None。
    least = max(2, min(len(previous), len(current)) // 3)
    if best_hits >= least:
        return best_shift

    # 兜底：拖动是手指滑 700px，内容移动量是**任意像素**（不是 164 的整数倍），
    # 上面那套"只在 164 倍数里挑"永远对不上 —— 2026-11-15 16:54 实测一屏 18 个
    # 却累积到 162 个，就是每屏 offset 都错。这里按「同类型、同一行的 x 差」投票，
    # 取票数最多的那个位移（按 4px 分桶）。同类型 + 同行两道过滤足够挡住错配。
    votes = {}
    for old in previous:
        for new in current:
            if old.kind != new.kind:
                continue
            if abs(old.y - new.y) > SHIFT_ROW_TOLERANCE:
                continue
            dx = old.x - new.x
            if not low <= dx <= high:
                continue
            bucket = int(round(dx / 4.0)) * 4
            votes[bucket] = votes.get(bucket, 0) + 1
    if votes:
        bucket, hits = max(votes.items(), key=lambda item: item[1])
        if hits >= max(2, min(len(previous), len(current)) // 4):
            return bucket
    return None


def same_screen(previous, current, gap=25, least=2):
    """两屏读到的节点几乎重合，说明地图没有被拖动。

    Args:
        previous (list[RouteNode]): 上一屏的节点。
        current (list[RouteNode]): 这一屏的节点。
        gap (int): 判定重合的容差。
        least (int): 至少这么多对重合才算同一屏。

    Returns:
        bool: 是否等于同一屏。
    """
    hits = 0
    for old in previous:
        for new in current:
            if abs(old.x - new.x) <= gap and abs(old.y - new.y) <= gap:
                hits += 1
                break
    return hits >= least


def merge_nodes(nodes, current, offset=0, gap=ROUTE_DEDUPE):
    """把这一屏读到的节点并进全局表，位置重合的并成同一颗（类型按投票定）。

    Args:
        nodes (list[RouteNode]): 全局表，就地追加。
        current (list[RouteNode]): 这一屏的节点（屏幕坐标）。
        offset (int): 这一屏相对整张图最左端的水平偏移。
        gap (int): 判定"同一个节点"的容差。

    Returns:
        tuple: (新加进去的节点数, mapping) —— mapping[k] 是 current[k] 在全局 nodes
            里的下标。连线用它来记录连通关系，避免依赖坐标（拖动位移有误差）。
    """
    added = 0
    mapping = []
    for node in current:
        x = node.x + offset
        found = None
        position = -1
        for index, other in enumerate(nodes):
            if abs(other.x - x) <= gap and abs(other.y - node.y) <= gap:
                found = other
                position = index
                break
        if found is None:
            created = RouteNode(x, node.y, node.kind)
            created.votes = {node.kind: 1}
            created.shop = node.shop
            nodes.append(created)
            mapping.append(len(nodes) - 1)
            added += 1
            continue
        mapping.append(position)
        # 位置相同就是同一颗节点，类型按投票多的算（同一颗节点被不同屏读成
        # 不同类型时，只看最后一次会来回跳）。招牌只要有一屏看见就算有。
        found.votes[node.kind] = found.votes.get(node.kind, 0) + 1
        found.kind = max(found.votes.items(), key=lambda item: item[1])[0]
        if node.shop:
            found.shop = True
    return added, mapping


def _stands_out(image, x, y, width, height):
    """立卡是浮在暗背景上的：卡内亮、卡外一圈暗，才算一张卡。

    Args:
        image (np.ndarray): RGB 全屏帧。
        x (int): 卡中心 x。
        y (int): 卡中心 y。
        width (int): 卡宽。
        height (int): 卡高。

    Returns:
        bool: 卡内平均亮度比卡外一圈高出 CARD_CONTRAST 以上。
    """
    left = max(0, int(x - width / 2) - 10)
    right = int(x + width / 2) + 10
    top = max(0, int(y - height / 2) - 10)
    bottom = int(y + height / 2) + 10
    patch = image[top:bottom, left:right, :3].astype(np.int32)
    if patch.shape[0] < height or patch.shape[1] < width:
        return False
    values = patch.mean(axis=2)
    inner = values[10:10 + height, 10:10 + width]
    outer = np.concatenate([
        values[:10, :].ravel(), values[-10:, :].ravel(),
        values[:, :10].ravel(), values[:, -10:].ravel(),
    ])
    return inner.mean() - outer.mean() >= CARD_CONTRAST


def read_cards(image):
    """读出 3D 地图上立着的图标卡，也就是本次可以走的几个节点。

    Args:
        image (np.ndarray): RGB 图像。

    Returns:
        list[RouteCard]: 按 x 排序。空列表说明当前不是 3D 地图的可选节点状态。
    """
    x1, y1, x2, y2 = CARD_AREA
    patch = image[y1:y2, x1:x2, :3]
    hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV).astype(np.int32)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    raw = []
    for kind, ranges in HUE_RANGES.items():
        mask = _node_mask(hue, sat, val, ranges).astype(np.uint8)
        if kind == KIND_ELITE:
            # Separate the purple flag from the nearby enemy and platform glow.
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, ROUTE_GLOW_OPENING)
        count, _, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        for index in range(1, count):
            area = int(stats[index][4])
            width = int(stats[index][2])
            height = int(stats[index][3])
            if area < CARD_AREA_MIN:
                continue
            if not CARD_WIDTH[0] <= width <= CARD_WIDTH[1]:
                continue
            if not CARD_HEIGHT[0] <= height <= CARD_HEIGHT[1]:
                continue
            if not CARD_RATIO[0] <= height / float(width) <= CARD_RATIO[1]:
                continue
            raw.append((area, cents[index][0] + x1, cents[index][1] + y1, kind, width, height))

    # 一张卡也可能被两个色相段同时抓到，位置重合时留最大的那块。
    raw.sort(key=lambda item: -item[0])
    cards = []
    for area, x, y, kind, width, height in raw:
        duplicate = False
        for other in cards:
            if abs(other.x - x) <= NODE_DEDUPE and abs(other.y - y) <= NODE_DEDUPE:
                duplicate = True
                break
        if duplicate:
            continue
        cards.append(RouteCard(x, y, kind, width, height))

    # 认不出颜色的卡（航点/补给那种浅白针形图标）也要走，否则地图上一张卡都读不到，
    # 主循环只会一直"没有可点的节点卡"（2026-11-14 21:1x 实测）。
    # 只收"浅白+高亮+四周暗一圈"的立卡：不加这两个条件时，剧情/装备页的亮场景块
    # 也会被认成卡（drive_002、stall2 实测各有 1~2 个误报）。
    plain = ((val >= CARD_PALE_VALUE) & (sat <= CARD_SATURATION_MAX)).astype('uint8')
    count, _, stats, cents = cv2.connectedComponentsWithStats(plain, 8)
    for index in range(1, count):
        area = int(stats[index][4])
        width = int(stats[index][2])
        height = int(stats[index][3])
        if area < CARD_AREA_MIN:
            continue
        if not CARD_WIDTH[0] <= width <= CARD_WIDTH[1]:
            continue
        if not CARD_HEIGHT[0] <= height <= CARD_HEIGHT[1]:
            continue
        if not CARD_RATIO[0] <= height / float(width) <= CARD_RATIO[1]:
            continue
        if area < width * height * 0.5:
            continue
        x = cents[index][0] + x1
        y = cents[index][1] + y1
        duplicate = False
        for other in cards:
            if abs(other.x - x) <= NODE_DEDUPE and abs(other.y - y) <= NODE_DEDUPE:
                duplicate = True
                break
        if duplicate:
            continue
        if not _stands_out(image, x, y, width, height):
            continue
        cards.append(RouteCard(x, y, KIND_UNKNOWN, width, height))

    cards.sort(key=lambda card: card.x)
    return cards


def card_hue(image, card, half=18):
    """Return the dominant hue (0-179) inside a card, for logging/diagnosis.

    排查「明明该避开精英却走了」时，光看 `kind` 不够 —— 要确认卡片本身的色相
    到底是 130(紫) 还是 170(红)。2026-11-16 用户实机走了精英，日志只说 `戰鬥`。

    Args:
        image (np.ndarray): RGB 帧。
        card (RouteCard): `read_cards` 的结果。
        half (int): 采样半宽/半高。

    Returns:
        int: 主色相，取不到返回 -1。
    """
    patch = image[max(0, card.y - half):card.y + half,
                  max(0, card.x - half):card.x + half, :3]
    if not patch.size:
        return -1
    hsv = cv2.cvtColor(patch, cv2.COLOR_RGB2HSV)
    hue = hsv[:, :, 0]
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    mask = (sat > 90) & (val > 90)
    if not mask.any():
        return -1
    histogram = np.bincount(hue[mask].ravel(), minlength=180)
    return int(np.argmax(histogram))


def best_card(cards, style, state=None, weights=None):
    """在可达的几张卡里挑一张最该走的，挑不到返回 None。

    ❗`weights` 是这次重写的关键：以前这里只看单张卡的类型分数，开局用 2D 地图
    读出来的 `plan()` 结果**根本没参与选路**（只拿去打日志了）。现在把"这一层该
    优先走哪类节点"作为第一关键字传进来，分数只用于同类型内比较。

    Args:
        cards (list[RouteCard]): read_cards 的结果。
        style (str): ROUTE_* 之一。
        state (dict): 见 score()。
        weights (list[str] | None): 本层类型的优先顺序（plan() 那一层按分数排好的
            kind 列表）。给了就按它挑；没给就退回纯按 score。

    Returns:
        RouteCard: 优先级最高的一张；同优先级取分数高的，再同分取最左边。
    """
    state = state or {}
    order = {}
    for index, kind in enumerate(weights or ()):
        order.setdefault(kind, index)
    fallback = len(order) + 1

    best = None
    best_key = None
    for card in cards:
        value = score(card.kind, style, state, getattr(card, 'shop', False))
        key = (order.get(card.kind, fallback), -value)
        if best_key is None or key < best_key:
            best = card
            best_key = key
    return best


def planned_card(cards, entry):
    """Map the planned branch to 3D only when the visible choices agree."""
    ordered = sorted(cards, key=lambda card: card.y)
    if [card.kind for card in ordered] == entry['choices']:
        return ordered[entry['choice_index']]
    return None


def has_edge(image, start, end, samples=40):
    """相邻两层两个节点之间是不是画了连线（虚线，取中间段连亮判定）。

    Args:
        image (np.ndarray): RGB 图像。
        start (RouteNode): 左层节点。
        end (RouteNode): 右层节点。

    Returns:
        bool: 判定有连线。
    """
    x1, y1 = start.x, start.y
    x2, y2 = end.x, end.y
    lights = []
    for step in range(1, samples):
        ratio = step / float(samples)
        x = int(round(x1 + (x2 - x1) * ratio))
        y = int(round(y1 + (y2 - y1) * ratio))
        window = image[max(0, y - 4):y + 5, max(0, x - 4):x + 5, :3].astype(np.int32)
        lights.append(int(window.min(axis=2).max()))
    middle = lights[int(len(lights) * 0.2):int(len(lights) * 0.8)]
    streak = 0
    for light in middle:
        streak = streak + 1 if light >= 200 else 0
        if streak >= 3:
            return True
    return False


def score(kind, style, state, shop=False):
    """给一个节点的类型打分。state 里的状态可以缺省，缺省就是"状态正常"。

    Args:
        kind (str): KIND_* 之一。
        style (str): ROUTE_* 之一。
        state (dict): hp(0~1)、stress(0~50)、junk(要不要删卡)、need_spark(目标卡灵光不对)、
            credits(信用点)、avoid_elite(bool)、meditate(bool)。
        shop (bool): 这个休息点带商店（能删卡、能买东西）。

    Returns:
        int: 分数。
    """
    style = style if style in BASE_SCORE else ROUTE_BALANCE
    value = BASE_SCORE[style].get(kind, 0)

    hp = state.get('hp', 1.0)
    stress = state.get('stress', 0)
    if kind == KIND_REST:
        if hp < 0.4:
            value += 40
        elif hp < 0.7:
            value += 15
        if stress >= 30:
            value += 25
        elif stress >= 20:
            value += 10
        if state.get('need_spark') and state.get('meditate', True):
            # 冥想可以重掷某一张卡的灵光，卡组差一张的时候最值钱
            value += 25
        if state.get('junk'):
            # 有的休息点带商店，能删卡
            value += 10
        if shop:
            # 带商店的休息点才删得掉牌，用户 2026-11-15：商店和休息不冲突
            value += SHOP_SCORE
    if kind in (KIND_BATTLE, KIND_EVENT):
        if hp < 0.35:
            value -= 25
        if stress >= 35:
            value -= 15
        if state.get('need_spark'):
            # 战斗和事件都能灵光一闪，缺灵光的时候优先去
            value += 15
        if state.get('junk') and kind == KIND_EVENT:
            value += 10
    if kind == KIND_EVENT and state.get('credits', 0) >= 50:
        value += 5
    if kind == KIND_ELITE:
        if state.get('avoid_elite', True):
            value -= 50
        elif hp >= 0.8:
            value += 10
    return value


def read_edges(image, nodes):
    """Return connected node index pairs for one 2D preview."""
    white = image[:, :, :3].min(axis=2) > EDGE_LIGHT
    by_tier = {}
    for index, node in enumerate(nodes):
        by_tier.setdefault(node.tier, []).append((index, node))
    return [(i, j) for i, left in enumerate(nodes)
            for j, right in by_tier.get(left.tier + 1, ())
            if _along_line(white, left, right)]


def _along_line(mask, left, right):
    dx = right.x - left.x
    if not TIER_DISTANCE[0] <= dx <= TIER_DISTANCE[1]:
        return False
    xs = np.rint(left.x + EDGE_TIP_X + (dx - 2 * EDGE_TIP_X) * EDGE_SAMPLES).astype(int)
    ys = np.rint(left.y + EDGE_TIP_Y + (right.y - left.y) * EDGE_SAMPLES).astype(int)
    rows = np.clip(ys[:, None] + EDGE_Y_OFFSETS, 0, mask.shape[0] - 1)
    return np.count_nonzero(mask[rows, xs[:, None]].any(axis=1)) >= 9


def _nearest(nodes, x, y, tol=40):
    """找离 (x, y) 最近的节点；超出 tol 返回 None。拼图后坐标会带 offset，
    所以匹配要留容差。"""
    best = None
    for node in nodes:
        dist = abs(node.x - x) + abs(node.y - y)
        if dist <= tol and (best is None or dist < best[0]):
            best = (dist, node)
    return best[1] if best else None


def link_tiers(nodes):
    """相邻两层之间哪些节点是连通的（按连线的高度差估计）。

    ❗旧版 `plan()` 只按"这一层有哪些类型"排序，**完全不管连线** —— 于是会推荐
    一条根本走不通的路线（比如推荐第 3 层的事件，但那个事件和上一层的落脚点之间
    没有白线）。用户 2026-11-15 指出这一点：只有连线相通的才能走。

    精确检测连线做不到：连线从菱形**顶点**出发、而 `read_nodes` 的坐标本身有
    ±10px 误差（连通域中心受牌面图标影响），实测五种算法（沿直线采样、法线搜索、
    膨胀连通域、Hough 端点配对、顶点枚举）都分不干净 —— 真线占比 0.76~0.89、
    假线 0.26~0.45，区间重叠。

    但连线有个稳定的形状规律：**只连相邻行或跨一行的斜线**，高度差不超过
    一个行距（实测行距 ≈108，连线 |Δy| ≤ 110），跨两行以上的一概没有。
    用它做可达性，和肉眼看到的完全对得上。

    Args:
        nodes (list[RouteNode]): 已 fill_grid 的节点。

    Returns:
        dict: {(x, y): [下层可达节点, ...]}
    """
    by_tier = {}
    for node in nodes:
        by_tier.setdefault(node.tier, []).append(node)

    links = {}
    for tier in sorted(by_tier):
        upper = by_tier.get(tier + 1, [])
        for node in by_tier[tier]:
            links[(node.x, node.y)] = [
                other for other in upper if abs(other.y - node.y) <= LINK_DY]
    return links


def best_path(nodes, style=ROUTE_BALANCE, state=None, edges=None):
    """在连通图上挑一条总分最高的路径（每层一格，逐层向右）。

    Args:
        nodes (list[RouteNode]): read_nodes 的结果。
        style (str): ROUTE_* 之一。
        state (dict): 见 score()。
        edges (list[tuple] | None): read_edges 的结果，[(x1,y1,x2,y2), ...]。
            给了就用**真实连线**建图；没给（或为空）退回 `link_tiers` 的高度差近似。

    Returns:
        list[RouteNode]: 从最左一层走到**最末有效层**的完整路径；无节点或没有
            一条能走到底的连通路线时为空（由调用方退回本地选卡兜底）。
    """
    state = state or {}
    if not nodes:
        return []
    by_tier = {}
    for node in nodes:
        by_tier.setdefault(node.tier, []).append(node)
    tiers = sorted(by_tier)
    if not tiers:
        return []

    if edges:
        # edges 是**节点下标**对（read_edges 返回、merge_nodes 的 mapping 转换过来的）
        link_map = {}
        for pair in edges:
            if len(pair) != 2:
                continue
            i, j = pair
            if not (0 <= i < len(nodes) and 0 <= j < len(nodes)) or i == j:
                continue
            start, end = nodes[i], nodes[j]
            link_map.setdefault((start.x, start.y), []).append(end)
        links = link_map
    else:
        links = link_tiers(nodes)

    # DP：best[(x,y)] = (累计分, 路径)
    best = {}
    for node in by_tier[tiers[0]]:
        best[(node.x, node.y)] = (score(node.kind, style, state, node.shop), [node])

    for index in range(1, len(tiers)):
        lower = by_tier[tiers[index]]
        upper = by_tier[tiers[index - 1]]
        for node in lower:
            value = score(node.kind, style, state, node.shop)
            chosen = None
            for prev in upper:
                key = (prev.x, prev.y)
                if key not in best:
                    continue
                if node not in links.get(key, ()):
                    continue
                total, path = best[key]
                if chosen is None or total > chosen[0]:
                    chosen = (total, path + [node])
            if chosen is not None:
                best[(node.x, node.y)] = (chosen[0] + value, chosen[1])

    # 负分节点会让中途前缀的分数高于完整路线。
    complete = (item for item in best.values() if item[1][-1].tier == tiers[-1])
    return max(complete, key=lambda item: item[0], default=(0, []))[1]


def plan(nodes, style=ROUTE_BALANCE, state=None, edges=None):
    """沿连通路径给出每一层该走的那一格。

    和旧版的区别：旧版把每层的类型全列出来按分数排（完全不看连线，可能推荐
    走不到的格子）；现在先跑 `best_path()` 求一条**沿白线连通**的最优路径，
    每层保留目标及可走分支顺序，让执行端在点击前和实时立卡核对。

    Args:
        nodes (list[RouteNode]): read_nodes 的结果。
        style (str): ROUTE_* 之一。
        state (dict): 见 score()。

    Returns:
        list[list[dict]]: 每一层一个列表（现在只有 1 项），元素是
            {'kind', 'count', 'shop', 'score', 'choices', 'choice_index'}。
    """
    state = state or {}
    # ❗连线读不到（或少得离谱）时**不规划**，返回空表让执行端退回"按单卡分数挑"。
    # 退回 `link_tiers` 的高度差近似是危险的：它会把"上排战斗 → 事件"这种
    # **中间隔着精英、实际没有线**的组合判成连通（2026-11-15 用户截图实测），
    # 规划于是指一条走不通的路，执行时 3D 立卡里根本没有那个节点。
    # 宁可没有前瞻，也不要假路线。
    if not edges or len(edges) < max(2, len(nodes) // 4):
        return []
    result = []
    targets = {}
    for i, j in edges:
        if 0 <= i < len(nodes) and 0 <= j < len(nodes):
            targets.setdefault(nodes[i], set()).add(nodes[j])
    previous = None
    for node in best_path(nodes, style, state, edges):
        reachable = nodes if previous is None else targets[previous]
        choices = sorted((other for other in reachable if other.tier == node.tier),
                         key=lambda other: other.y)
        result.append([{'kind': node.kind, 'count': 1, 'shop': node.shop,
                        'score': score(node.kind, style, state, node.shop),
                        'choices': [other.kind for other in choices],
                        'choice_index': choices.index(node)}])
        previous = node
    return result


def describe(plan_result):
    """把 plan() 的结果写成人看得懂的一行行文本。"""
    lines = []
    for index, kinds in enumerate(plan_result):
        parts = []
        for item in kinds:
            name = KIND_NAMES[item['kind']] + ('+商店' if item.get('shop') else '')
            parts.append('%s x%s(%s)' % (name, item['count'], item['score']))
        lines.append('第%s层: %s' % (index + 1, ' > '.join(parts)))
    return lines
