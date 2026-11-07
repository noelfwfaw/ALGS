# -*- coding: utf-8 -*-
"""「引导 1~142」的页链，用来在 press() 里逐页淘汰已经走过的引导素材。

数据源：用户的 `starsavior_Starsavior2.spec.json`（页面卡编辑器导出，195 页）。
spec 是用户本机的 297MB 文件、不进仓库，所以这里固化成常量；页面卡改版后
按 `dev_tools/serve_asset_maker.bat` 重新导出再核对本文件。

实测结构（2026-11-07 从 spec 解析）：
    - 标题形如「引导N」的页共 140 个：引导 1 = page_7，引导 142 = page_192，
      引导编号缺 53/54/55，但**页号是连续的 7..58**，别按引导编号 +1 推算。
    - 其余 55 页（登录 / 昵称 / 主页面 / 邮箱 / 菜单 / 任务 / 抽卡 / 验号 /
      重置…）**不是引导**，一律不参与淘汰。
    - 引导页里只有 page_134 有两个元素（134_1 高亮、134_2 自动战斗）。
    - 引导页 exits 不是「下一页」的只有 1 条：page_24(引导18) -> page_15(引导9)。
      这就是回跳保护区间的由来。

淘汰规则（在 `press()` 里）：某引导页的按钮**点成功**后，只把它的紧邻
前一引导页标为过期，后续帧不再对它做模板匹配。不一次性禁用前面全部，
单帧误识别最多影响 1 页；非引导按钮、保护区内的页永不受影响。
"""
import re

# 140 个引导页的页号，按 spec 的页链顺序（严格递增）。
GUIDE_PAGES = tuple(
    list(range(7, 59))          # 引导 1~52（引导编号缺 53/54/55 页，页号不缺）
    + list(range(62, 69))       # 60/61 是昵称页，不是引导
    + list(range(70, 115))      # 69 是抽卡动画 SKIP，不是引导
    + list(range(127, 135))
    + [140, 141]
    + list(range(151, 169))
    + list(range(185, 193))
)
GUIDE_PAGE_SET = frozenset(GUIDE_PAGES)

# page_24(引导18) 的 exit 会回到 page_15(引导9)。这段里的页不能被淘汰，
# 否则回跳之后引导 9 的素材已经不在扫描表里，整段卡死。
GUIDE_PROTECT = frozenset(range(15, 25))

# 同一引导页上的额外元素。其余引导页的元素名都是 E_<页号>_1。
GUIDE_EXTRA_ELEMENTS = {
    'E_134_2': 134,            # 自动战斗，和 134_1（引导高亮）同屏
}

_ELEMENT = re.compile(r'^E_(\d+)_1$')


def guide_page(name):
    """按钮属于哪个引导页；不是引导素材返回 None。

    Args:
        name (str): Button.name，形如 `E_134_1`。

    Returns:
        int: 页号，或 None。
    """
    page = GUIDE_EXTRA_ELEMENTS.get(name)
    if page is not None:
        return page
    m = _ELEMENT.match(name or '')
    if not m:
        return None
    page = int(m.group(1))
    return page if page in GUIDE_PAGE_SET else None


def previous_guide_page(page):
    """`page` 的紧邻前一引导页；链首 / 非引导 / 保护区内的返回 None。"""
    if page is None or page in GUIDE_PROTECT or page not in GUIDE_PAGE_SET:
        return None
    index = GUIDE_PAGES.index(page)
    # ❗index == 0 必须挡住：GUIDE_PAGES[-1] 是 page_192，链首 page_7
    #    会把「最后一页」当成自己的前一页淘汰掉（离线回放抓到过）。
    if index <= 0:
        return None
    prev = GUIDE_PAGES[index - 1]
    return None if prev in GUIDE_PROTECT else prev
