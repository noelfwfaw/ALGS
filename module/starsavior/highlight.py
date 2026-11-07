"""引导高亮框：找"一圈亮边"，**不看框里是什么**。

为什么只能这样找
----------------
引导框里可能是敌人（还在动）、技能卡、按钮。把整块框成模板，就等于要求
"框里的内容也不许变"，必然失败。2026-11-06 真机实测：

    `E_14_1`（白框 + **静态**技能卡）   匹配 1.000
    `E_15_1`（白圈 + **会动**的敌人）   匹配 0.000

差别就在内容动不动，不是阈值的问题。

所以这里只认"一圈亮边"这个几何特征：

    亮像素 → 连通域 → 空心 + 接近正方 + 够大 → 取中心

和框里是什么完全无关，一屏一屏换内容也不影响。代价是要排除误判 ——
半成品 `log/ss_explore/driver.py` 当时踩过三个：右上角的 SKIP / ⏸、
左上角的"距离目标"小本子、底部技能栏。这里做成 `DEFAULT_EXCLUDE`。

纯像素运算，不碰设备，可以拿离线截图直接验：
    `python dev_tools/probe_starsavior_highlight.py`
"""
import cv2
import numpy as np

# 亮边阈值。
# ❗不能取 200：白圈是**半透明白 + 外发光**，只有最亮的核心过 200，
# 二值化后断成几段弧，闭运算连不成一个环 —— 真机 `live_q.png` 那张
# （战斗教学的白圈）就是这么漏掉的，175 个轮廓里根本没有它。
# 160 能把整条环连起来；背景里的白块靠下面几条判据挡。
WHITE = 160

# 外接矩形面积范围。比这小的都是 UI 装饰（图标高光、按钮描边）；
# 太大的是角色立绘的外框（列表页那个 332x485 的），引导框不会那么大。
MIN_AREA = 5000
MAX_AREA = 120000

# 轮廓周长 / 外接矩形周长 的上限。
# 真框是贴着外接矩形走的那一条线：圆环 0.78、方框 1.0。
# 爆炸特效的白色粒子被闭运算连起来时，轮廓是锯齿状的，比值会到 1.5 以上
# （实测 live_b3 那个 237x241 的假框）。
MAX_EDGE_RATIO = 1.25

# 外接矩形长宽比范围。圆/圆角方框接近 1，但套菜单项的那种是扁的
# （「管理」那个 112x54 = 2.07），所以上限放到 2.4。
RATIO = (0.55, 2.4)

# 框内部（往里缩 10 像素）的亮度上限。
# 空心框里是游戏画面（暗），白色实心块里也是亮的 —— 这条把实心块挡掉。
INNER_MAX_LUMA = 175

# 外接矩形里"亮像素"的占比上限。
# 框是一条细线：圆环约 0.2、方框约 0.13；实心亮块（角色立绘、爆炸特效、
# 白色面板）都在 0.5 以上。没有这一条，普通战斗/列表画面会被误判成"找到框"
# （实测 live_b3 / live_now2 / live_q 三张全中）。
MAX_FILL = 0.38

# 亮像素占比的下限。太稀疏的是零散高光，不是一条连续的线。
MIN_FILL = 0.10

# 白色弹窗面板的判据：画面中央那块里，亮度超过 PANEL_WHITE 的像素占比
# 高于 PANEL_RATIO 就认为"有弹窗"，不找框。
# 实测：输入昵称弹窗 0.793 / 战斗里的真白圈 0.015 / 剧情视频 0.014，
# 差 50 倍，阈值随便放中间都行。
PANEL_WHITE = 200
PANEL_RATIO = 0.30

# 默认不要找的区域（原图坐标）。
DEFAULT_EXCLUDE = (
    (1120, 0, 1280, 90),      # 右上角 SKIP / ⏸ / 菜单
    (0, 0, 330, 130),         # 左上角「距离目标」小本子
    (0, 692, 1280, 720),      # 最底那条状态栏。别往上扩：技能卡的引导框就在 614~704，
                              # 扩到 590 会把 E_14_1 自己也排掉（实测踩过）
)


def _gray(image):
    """统一成 8UC1 灰度（PIL 图和 ndarray 都收）。"""
    if hasattr(image, 'convert'):
        image = image.convert('RGB')
    a = np.ascontiguousarray(np.asarray(image, dtype=np.uint8))
    if a.ndim == 3:
        a = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    return a


def _center(box):
    x, y, w, h = box
    return x + w // 2, y + h // 2


def _inside(point, area):
    return area[0] <= point[0] <= area[2] and area[1] <= point[1] <= area[3]


def _ring(gray, cx, cy, radius, width=7):
    """圆环区域的掩码（用来量"圈上够不够亮"）。"""
    yy, xx = np.ogrid[:gray.shape[0], :gray.shape[1]]
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    return (d2 >= (radius - width) ** 2) & (d2 <= radius ** 2)


def _find_circle(gray, exclude):
    """用霍夫圆找白圈，返回中心或 None。

    ❗**不能靠"闭运算 + 轮廓"**：白圈是半透明白，二值化后断成几段弧。
    核给小了连不成环（真机 live_q.png 里连轮廓都不存在），
    核给大了又把环填成实心块（85x148、亮占比 0.53，被实心判据拒掉）。
    霍夫圆只看梯度方向，断续的圆照样能拟合出来 —— 和 `rescuer.rows()` 找头像同一个道理。
    """
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    found = cv2.HoughCircles(
        blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=140,
        param1=120, param2=30, minRadius=55, maxRadius=170,
    )
    if found is None:
        return None
    for cx, cy, radius in np.round(found[0]).astype(int):
        cx, cy, radius = int(cx), int(cy), int(radius)
        if any(_inside((cx, cy), area) for area in exclude):
            continue
        # 圈上必须真的亮：别的圆（头像、UI 环、爆炸）也会被霍夫捡到，
        # 但它们的边不是白色发光线。
        if float(gray[_ring(gray, cx, cy, radius)].mean()) < 150:
            continue
        return cx, cy
    return None


def _is_panel(gray):
    """画面上有没有白色弹窗面板（Dialog）。

    ❗弹窗上的「框」不是引导框。游戏弹窗是**白底 + 深色输入框**，
    在轮廓法眼里和「白圈套敌人」长得一模一样 —— 实测「输入昵称」弹窗的
    那个输入框被判成高亮框，`press` 就一直在点输入框（点四次以上），
    昵称永远打不进去，引导卡死在那一屏（真机 2026-11-06 20:16）。

    判据只量画面中央那块的白占比，实测差得很开：
        输入昵称弹窗   0.793
        战斗里的真白圈 0.015
        剧情视频       0.014
    所以 0.30 一刀切，不用调。
    """
    h, w = gray.shape
    patch = gray[int(h * 0.30):int(h * 0.55), int(w * 0.25):int(w * 0.75)]
    if patch.size == 0:
        return False
    return float((patch > PANEL_WHITE).mean()) > PANEL_RATIO


def find(image, exclude=None, debug=False):
    """找引导高亮框，返回它的中心 ``(x, y)``，没有就 None。

    Args:
        image: 整屏（PIL / ndarray 都行）。
        exclude: 不要找的区域，默认 `DEFAULT_EXCLUDE`。
        debug: True 时把候选框和分数打出来（排查误判用）。

    Returns:
        tuple[int, int] | None
    """
    if exclude is None:
        exclude = DEFAULT_EXCLUDE

    gray = _gray(image)

    # 白色弹窗面板上不找框 —— 那是 Dialog，不是引导框。
    if _is_panel(gray):
        if debug:
            print('    白色弹窗面板，不找框')
        return None

    # 先找方框（白框套技能卡这类）：轮廓法在离线素材上是像素级准确的，
    # 所以优先。
    mask = (gray > WHITE).astype(np.uint8)
    # 边框是细线、还可能被外发光断开，先闭运算连成一条完整的环
    # 核要给到 15：白圈是半透明白，二值化后会断成几段弧，7x7 连不起来
    # （真机 live_q.png 里它连轮廓都没形成，候选列表里根本没有 y≈390 那一块）。
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best = None
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        cx, cy = _center((x, y, w, h))
        inner = gray[y + 10:y + h - 10, x + 10:x + w - 10]
        inner_luma = float(inner.mean()) if inner.size else 255.0
        fill = float(mask[y:y + h, x:x + w].mean())
        edge_ratio = cv2.arcLength(contour, True) / float(2 * (w + h))
        reason = ''
        if w * h < MIN_AREA:
            reason = '太小 %d' % (w * h)
        elif not (RATIO[0] <= w / float(max(h, 1)) <= RATIO[1]):
            reason = '长宽比 %.2f' % (w / float(max(h, 1)))
        elif any(_inside((cx, cy), area) for area in exclude):
            reason = '在排除区'
        elif inner_luma > INNER_MAX_LUMA:
            reason = '实心 内部亮度 %.0f' % inner_luma
        elif fill > MAX_FILL:
            reason = '实心块 亮占比 %.2f' % fill
        elif fill < MIN_FILL:
            reason = '太稀疏 亮占比 %.2f' % fill
        elif w * h > MAX_AREA:
            reason = '太大 %d' % (w * h)
        elif edge_ratio > MAX_EDGE_RATIO:
            reason = '轮廓锯齿 %.2f' % edge_ratio
        elif best is not None and w * h <= best[0]:
            reason = '不是最大的'

        if debug:
            print('    候补 (%4d,%4d) %3dx%-3d 内部 %3.0f 亮 %.2f 边 %.2f %s'
                  % (cx, cy, w, h, inner_luma, fill, edge_ratio, reason or '✔'))
        if reason:
            continue

        if best is None or w * h > best[0]:
            best = (w * h, (cx, cy))
    if best:
        return best[1]

    # 方框没找到，再试圆（白圈套敌人那种）。
    # ⚠️ 这一支还没调稳：真机 `live_q.png` 里那个白圈它找不到，
    #    而列表页 `live_now2.png` 会给一个假圆。先留着当兜底，
    #    它只在轮廓法完全没结果时才跑，不会抢掉上面那些准确的结果。
    circle = _find_circle(gray, exclude)
    if circle is not None and debug:
        print('    圆 (%d,%d)' % circle)
    return circle
