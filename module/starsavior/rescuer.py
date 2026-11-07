"""救援者列表：定位每一行、判断哪一行是当前选中的。

只做这两件事。稀有度不看头像角标了 —— 用户 2026-11-06 18:45 要求改成
「点中一行，看左上角她框的那块稀有度」，所以 SSR 的判定在 `scan.py` 里，
用 spec page 194 那个稀有度模板（实测 SSR 1.000 / SR 0.000，比算颜色干净）。

这里只有像素运算，不碰设备也不碰配置，可以拿**离线整屏截图**直接验
（`python dev_tools/probe_starsavior_rescuer.py <图>`）。

坐标全部是 1280x720，来自 log/ss_explore 的真机像素测量（v1.610 版式）。
"""
import cv2
import numpy as np

# 右侧列表面板。不能框太大：大厅背景里也有圆形高光，HoughCircles 会被骗到，
# 多出来几行"头像"，后面就会去点不存在的位置。
PANEL = (1100, 80, 1270, 660)

# 头像半径。实测未选中行 27~29，取 28 当基准，搜索范围放宽到 ±8。
FACE_R = 28

# 未选中行的头像圆心 x 全都一样（实测 1206~1208，圆检测抖动 ±2）。
# 被选中的那一行会**缩放重绘**，圆心跑到 1172~1176 —— 所以「cx 明显偏小」
# 就是「这一行是当前选中的」。这是"选中态有没有移过去"的唯一判据：
# 不看它的话，点空了也会以为选中，然后连着读两遍同一个角色。
SEL_X = 1195


def _gray(image):
    """统一成 8UC1 灰度（HoughCircles 只吃这个）。"""
    if hasattr(image, 'convert'):
        image = image.convert('RGB')
    a = np.ascontiguousarray(np.asarray(image, dtype=np.uint8))
    return cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)


def rows(image):
    """在列表里找头像圆，返回按 y 排好序的 ``[(cy, cx, r)]``。

    用圆检测而不是按行距硬算 y：列表会滚、每行高度有 ±2px 抖动、
    而且第一行上面还有筛选栏，硬算迟早错一行。实测行距 71.7，但别依赖它。
    """
    y0, y1 = PANEL[1], PANEL[3]
    x0, x1 = PANEL[0], PANEL[2]
    sub = cv2.medianBlur(_gray(image)[y0:y1, x0:x1], 3)
    found = cv2.HoughCircles(
        sub, cv2.HOUGH_GRADIENT, dp=1, minDist=50,
        param1=100, param2=28,
        minRadius=FACE_R - 7, maxRadius=FACE_R + 8,
    )
    if found is None:
        return []
    out = [(int(c[1]) + y0, int(c[0]) + x0, int(c[2]))
           for c in np.round(found[0]).astype(int)]
    out.sort()
    return out


def selected(found):
    """被选中的那一行 ``(cy, cx)``，没有就 None。"""
    for cy, cx, _r in found:
        if cx < SEL_X:
            return cy, cx
    return None
