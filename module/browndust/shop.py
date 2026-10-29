"""
活动商店 (Brown Dust II) —— 按一张可调的优先级清单把活动兑换道具花掉。

Measured on the real device, 2026-10-29, season 「BROKEN BONDS」:

    page_main --右侧活动横幅--> page_event --底部第六块木牌「活动商店」--> page_shop
    page_shop --点商品图标--> 购买弹窗 --「购买」--> 「购买完成。」 --「确认」--> page_shop

这一页有五件事是量出来的，全部跟"位置不能写死"有关：

1. **商品是一张 7 列的流式网格**（列 x = 195/329/464/597/732/867/1001，格宽 130、
   高 221、行距 230）。**买满限量的商品不会留在原位变灰，而是沉到列表最后、
   显示「购买成功」并变暗**，中间的商品整体往前顶一格。所以不能记"第几行第几列
   是抽抽乐券" —— 买掉一个，后面每一格的意义都变了。每次下手之前都要重扫。

2. **"可买的永远排在前面"是这个任务能站着的前提**：沉底的只有已购的，所以从
   第一格往后扫，**碰到第一个「购买成功」就可以收工**，不用滚到底看完整张列表。
   这也正是用户说的"不需要做滚动扫描"。

3. **但一屏只装得下两排**。列表是 7 列 × 3 排（最后一格空着）。滚到顶时第一排
   y 92~313、第二排 322~543 完整可见；第三排从 552 开始，到 720 就断了 —— 只剩
   图标，**连名称都没有**（底部还压着一层渐变和「一键购买」）。所以是两次扫描：
   滚到顶扫 y 92/322，滚到底扫 y 417（那时第二排落在 188、第三排落在 417，两排
   都完整）。两屏的结果放进同一个列表再比优先级，不然第三排的抽抽乐券会排到
   第二排的精髓后面去。

4. **付费道具靠价格左边那枚货币图标认，不靠名字也不靠商品图**：蓝钻石是**同样
   形状、同样位置、每期都不变**的，会换的只有商品名、商品图、以及活动币的图标
   （幽灵糖果 → 蓝粉糖果）。判据是价格行左边 (x+8, y+186)-(x+80, y+218) 那块里
   蓝像素（B-R>50 且 B>120）> 0.03 **且** 粉像素（R-B>25 且 R>130）< 0.005 ——
   活动币的图标每期都带粉。实测钻石 0.067 / 0.000，活动币 0.012 / 0.016。
   注意 `uint8` 相减会回绕，必须先转 int（转之前每一格都会判成付费）。

5. **活动限定的装备在名字里带 `(UR)` / `(SR)`**，而装备名本身每期都换
   （这一期是「怪诞裙裾」）。OCR 会把"裙裾"读成"围裙"，但 `UR` / `SR` 两个字
   每次都读对 —— 所以装备只认后缀，不认全名。

另外几件：

- **商品名用 OCR 读**（`(x, y+126)-(x+130, y+152)`，`letter=(255,255,255)`
  `threshold=140`）。实测 14 格读对 12 格，错的两次都是装备名，而装备本来就走
   `UR`/`SR` 后缀。名字读出来是为了让过滤器可以直接写中文名（见下）。
  区域必须贴着名称那一行：往上会吃到「拥有 N 个」、往下会吃到「各账号限量」，
  两种都会让 cnocr 把名字读残（实测"生命精髓"→"生命"）。

- **「可购买 N 个」就是剩余限购次数**（远古水晶「各账号限量8次 0/8」→
  「可购买8个」）。按 `MAX` 等于"把这一档买满"，而**游戏自己会把 MAX 截到余额
  买得起的数量**（限购 99999 个的精炼粉末，余额 4650 时 MAX 填的是 4649），
  所以数量不用脚本算。

- **买不动就停，不许往下买**（用户 2026-10-29 纠正过一版）：清单是按价值排的，
  越靠后越不值。高优先级那一档还有货、只是币不够时，把币花在后面的档上等于
  挪用了它的预算 —— 活动币每天涨、限购不会跑，今天买不起的那一档明天接着买
  就是了。所以失败分支不是"跳过它"，而是"整趟收工"。

- **买完会自动滚回列表顶部**，所以循环不用自己记账位置。

用户的原话：「活动商店兑换每期基本都差多，会变的只有第一排的前三个付费道具、
活动限定的装备、活动限定装备的强化材料。你需要做成碧蓝那样的可调式的兑换优先级
设计。」以及「购买优先级（没写就是不买）：抽抽乐券-女神之泪-活动限定装备UR-
活动限定装备SR-活动装备强化材料（一般在装备的右边能买45个）-远古水晶-三种精髓-
精练水晶-4星升星之星」。
"""
import re

import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.base.utils import crop
from module.browndust.assets import (EVENT_TAB_SHOP, SHOP_BUY_DONE, SHOP_BUY_PANEL,
                                     SHOP_SOLD_OUT, SHOP_TITLE)
from module.browndust.browndust_ui import page_event, page_shop
from module.browndust.page import SHOP_BACK
from module.browndust.utils import match
from module.logger import logger
from module.ocr.ocr import Ocr

# ---- 网格 ------------------------------------------------------------------
#
# 列是实测的格子左边界（格宽 130，间隔 5），行距 230、格高 221。
SHOP_COLS = (195, 329, 464, 597, 732, 867, 1001)
SHOP_CELL_WIDTH = 130
SHOP_CELL_HEIGHT = 221
SHOP_ROW_STEP = 230

# 滚到顶时第一、二排的顶边。第三排（552）只露出图标，名称在 678 那一行被底部
# 渐变吃掉了，所以它不进这一轮。
SHOP_ROWS_TOP = (92, 322)
# 滚到底时第三排的顶边（第二排落在 188，已经扫过）。这一条是量出来的：两次
# 独立截图（`page_3` 和实机）都是 417。
SHOP_ROWS_BOTTOM = (417,)

# 格子内部，相对格子左上角。
SHOP_NAME_OFFSET = (0, 126, 130, 152)
SHOP_NAME_THRESHOLD = 140
# 名称那一行的实际位置会飘：滚到顶和滚到底停的地方差了十来像素（甩动的惯性），
# 同一屏里几排是一致的，但写死偏移就会把名字读成乱码。所以在格子下半部分
# (相对 y 116~168) 里找"最强的那条白字带"当名称行：高 8~22 像素、中心离标称
# 位置 13 像素以内的那一条；找不到才退回标称位置。
SHOP_NAME_SEARCH = (116, 168)
SHOP_NAME_HEIGHT = (8, 22)
SHOP_NAME_CENTER = 13
SHOP_NAME_TOLERANCE = 25
SHOP_NAME_BRIGHT = 170
SHOP_NAME_MIN_PIXELS = 6
# 价格行左边那块：货币图标会随价格位数左右移动，所以框得宽一点。
SHOP_PRICE_OFFSET = (8, 186, 80, 218)
# 付费道具的货币图标是那枚蓝钻石：**纯蓝，不带一点红**。活动币的图标每期都换
# （这一期是蓝粉双色的糖果），共同点是带粉。所以两条一起判，值是
# (阈值, 亮度下限, 占比门限)：
#   蓝（B-R>50 且 B>120）> 0.03，且粉（R-B>25 且 R>130）< 0.005
# 实测钻石 0.067 / 0.000，活动币 0.012 / 0.016，中间空得很开。
#
# 注意必须先把 `uint8` 转成 int 再相减 —— 直接减会回绕（100-200 变成 156），
# 红比蓝亮的像素全被算成"蓝"，那样每一格都会判成付费道具。
SHOP_PAID_BLUE = (50, 120, 0.03)
SHOP_PAID_PINK = (25, 130, 0.005)
# 「购买成功」在格子里的相对位置（`SHOP_SOLD_OUT.area` 减掉抽抽乐券那格的左上角）。
# 它压在价格那一行上，位置跟着格子走，所以每次都要在格子附近重新找一遍。
SHOP_SOLD_RELATIVE = (29, 187, 109, 214)
SHOP_SOLD_PAD = 20
SHOP_SOLD_SCORE = 0.85

# 点商品开购买弹窗：点图标中心。放大镜在左下角 (x+30, y+95)，别点那儿。
SHOP_ICON_OFFSET = (65, 55)

# ---- 购买弹窗 --------------------------------------------------------------
#
# 弹窗是固定尺寸的一块面板，三种商品量下来一模一样：
#   标题 y 205~235，黄字「购买商品将立刻发放。」(275,267)-(437,282)，
#   「1个 🎟300」y 424，「MIN/-10/+10/MAX」y 509，「购买」(837,496)-(1005,524)。
SHOP_PANEL_AREA = (250, 195, 1060, 490)
SHOP_PANEL_TIMEOUT = 10
SHOP_DONE_TIMEOUT = 15
SHOP_PANEL_CLOSE = Button(area=(992, 172, 1026, 206), color=(0, 0, 0),  # alas-lint: allow - a plain close X on the dialog, nothing behind it to match
                          button=(1009, 189, 1009, 189), name='SHOP_PANEL_CLOSE')
# 「MAX」/「MIN」两段按钮。买满限量是 MAX —— **游戏会把 MAX 截到"买得起"为止**
# （限购 99999 个的精炼粉末，余额 4650 时 MAX 填的是 4649），所以不用自己算数量。
SHOP_AMOUNT_MAX = Button(area=(540, 490, 638, 530), color=(0, 0, 0),  # alas-lint: allow - a plain text segment in the amount bar
                         button=(588, 509, 588, 509), name='SHOP_AMOUNT_MAX')
SHOP_AMOUNT_MIN = Button(area=(255, 490, 380, 530), color=(0, 0, 0),  # alas-lint: allow - a plain text segment in the amount bar
                         button=(318, 509, 318, 509), name='SHOP_AMOUNT_MIN')
SHOP_CONFIRM = Button(area=(837, 496, 1005, 524), color=(0, 0, 0),  # alas-lint: allow - the only bright capsule in the dialog, and SHOP_BUY_PANEL already proved the dialog is up
                     button=(921, 510, 921, 510), name='SHOP_CONFIRM')
# 「购买完成。」弹窗上那颗「确认」。
SHOP_DONE_OK = Button(area=(576, 385, 703, 421), color=(0, 0, 0),  # alas-lint: allow - a one-button alert, SHOP_BUY_DONE already proved it is up
                      button=(640, 403, 640, 403), name='SHOP_DONE_OK')

# 滚一格。一次 swipe 在实测里大约滚 300 像素（够从顶到底，列表只有 4 排）。
SHOP_SWIPE_FROM = (640, 300)
SHOP_SWIPE_TO_TOP = (640, 620)
SHOP_SWIPE_TO_BOTTOM = (640, 180)
SHOP_SWIPE_DURATION = 0.3

# 一轮最多买几种。列表是 7 列 × 3 排（最后一格空着），一天买不到 10 种，给 30
# 是防死循环。
SHOP_BUY_ROUNDS = 30
# 等列表画稳。买完之后整张列表会重排（买掉的那一格沉底，后面的往前顶）。
SHOP_SETTLE_TIMEOUT = 5

# ---- 优先级 ----------------------------------------------------------------
#
# 用户给的清单，一条不多（不写就是不买）。`>` 分隔，前面优先。
# 特殊代号：Paid / EquipUR / EquipSR / EquipMaterial；其余按商品名子串匹配，
# 所以换期想知道"这期的材料叫什么"时，直接写名字就行。
SHOP_FILTER_DEFAULT = (
    'GachaTicket > GoddessTear > EquipUR > EquipSR > EquipMaterial'
    ' > AncientCrystal > Essence > RefineCrystal > Star4'
)


def shop_filter_parse(string):
    """
    把过滤器字符串拆成优先级列表。

    顺手把全角/相似的 `>` 和空白都归一化 —— 用户从 wiki 上抄下来的是 `＞`。

    Args:
        string (str):

    Returns:
        list[str]: 从左到右，越靠前越优先。
    """
    string = str(string)
    string = re.sub(r'[＞﹥›˃ᐳ❯]', '>', string)
    string = re.sub(r'[ \t\r\n]', '', string)
    return [item for item in string.split('>') if item]


def shop_plain(text):
    """
    归一化商品名，用来做名字匹配。

    星星有三种写法（`★` / `☆` / `*`），而人写的时候多半写成「星」—— 先统一成
    「星」再去标点，这样 `4★升星之星` 和用户写的 `4星升星之星` 都是
    `4星升星之星`，OCR 读没读到那个 ★ 都不影响。

    Args:
        text (str):

    Returns:
        str:
    """
    text = re.sub(r'[★☆＊*]', '星', str(text).lower())
    return re.sub(r'[^0-9a-z\u4e00-\u9fa5]', '', text)


def shop_code(name):
    """
    从 OCR 出来的商品名推一个代号。

    装备只认 `UR` / `SR` 后缀 —— 装备名每期都换（这一期「怪诞裙裾」被 cnocr
    读成「怪诞围裙」），但后缀每次都读对。

    Args:
        name (str):

    Returns:
        str: 代号，认不出来返回空串。
    """
    name = str(name).replace(' ', '')
    if not name:
        return ''
    upper = name.upper()
    if 'UR' in upper:
        return 'EquipUR'
    if 'SR' in upper:
        return 'EquipSR'
    if '抽' in name and '券' in name:
        return 'GachaTicket'
    if '女神之泪' in name:
        return 'GoddessTear'
    if '远古' in name:
        return 'AncientCrystal'
    if '精炼' in name and '水晶' in name:
        return 'RefineCrystal'
    if '精髓' in name:
        return 'Essence'
    star = re.search(r'[1-4]', name)
    if '升星' in name and star:
        return 'Star' + star.group(0)
    return ''


class ShopGoods:
    """
    商店里的一个格子。

    Attributes:
        col (int): 第几列（0~6）。
        top (int): 格子顶边的 y。
        page (str): 这一格是在哪个滚动位置量到的 —— `top` 还是 `bottom`。坐标只在
            那个位置成立，下手之前得先把列表滚回去。
        name (str): OCR 读出来的商品名。
        paid (bool): 价格是钻石（付费道具）。
        sold_out (bool): 限量已经买完，这一格写着「购买成功」。
        code (str): 认出来的代号，see `shop_code()`。
        left_code (str): 左边那一格的代号 —— 只用来认"装备右边那个强化材料"。
    """

    def __init__(self, col, top, page='top'):
        self.col = col
        self.top = top
        self.page = page
        self.x = SHOP_COLS[col]
        self.name = ''
        self.paid = False
        self.sold_out = False
        self.code = ''
        self.left_code = ''

    def __str__(self):
        tag = self.code or ('Paid' if self.paid else '?')
        return f'{self.name or "<blank>"}({tag}) @row{self.top}col{self.col}'

    @property
    def icon(self):
        """
        点它开购买弹窗的那一点。

        给的是 `Button` 而不是坐标元组 —— `device.click()` 只认 Button（它要读
        `.button`）。这个 Button 没有 `file=`，所以**永远不能**拿去做 `appear()` /
        `match()`（硬约束 82），只能点。
        """
        x, y = self.x + SHOP_ICON_OFFSET[0], self.top + SHOP_ICON_OFFSET[1]
        return Button(area=(x - 16, y - 16, x + 16, y + 16), color=(0, 0, 0),  # alas-lint: allow - click-only, never matched
                      button=(x, y, x, y), name='SHOP_GOODS_%d_%d' % (self.col, self.top))

    @property
    def material(self):
        """
        它像不像"活动限定装备的强化材料"。

        这一期是「魔法之丝」：紧挨着 SR 装备右边、活动币结算、可买 45 个。名字和
        图标每期都换，所以只能认结构。装备先买走的话这一条会失效 —— 那时候在
        过滤器里直接写这期的名字即可（`魔法之丝`）。

        Returns:
            bool:
        """
        return (self.code not in ('EquipUR', 'EquipSR')
                and self.left_code in ('EquipUR', 'EquipSR'))

class EventShop:
    """
    Spend the event currency on whatever the priority list asks for.

    Pages:
        in: page_event
        out: page_event
    """

    def event_shop_run(self):
        """
        Pages:
            in: page_event
            out: page_event
        """
        if self.shop_enter():
            bought = self.shop_buy_all()
            logger.attr('Shop bought', bought)
            self.shop_back()

    # ---- 导航 --------------------------------------------------------------

    def shop_enter(self):
        """
        活动页点底部第六块木牌「活动商店」进页面。

        `EVENT_TAB_SHOP` 只当"这块木牌画出来了"的判据，点击点写死它的中心 ——
        `appear()` 带回来的匹配偏移会改写点击位置（硬约束 136）。

        Pages:
            in: page_event
            out: page_shop

        Returns:
            bool: 有没有进去。
        """
        self.ui_goto(page_event)
        if not self.wait_until_appear(EVENT_TAB_SHOP, offset=(20, 20), timeout=10):
            logger.warning('[Shop] the 活动商店 tab did not show up')
            return False
        # 活动页有入场动画，木牌最后才画；淡入期间点下去游戏不认。
        self.wait_until_still((900, 620, 1080, 690), timeout=5)

        for _ in range(2):
            self.device.click(EVENT_TAB_SHOP)  # alas-lint: allow - the tab was matched right above, the shop title below is the proof
            if self.wait_until_appear(SHOP_TITLE, offset=(20, 20), timeout=20):
                return True
            # 还没到：要么这一下被吞了（还在活动页），要么正在加载。用"木牌还在
            # 不在"分开，加载期间绝不能补点（会落到商店页的某个格子上直接买东西）。
            if not self.wait_until_appear(EVENT_TAB_SHOP, offset=(20, 20), timeout=2):
                if self.wait_until_appear(SHOP_TITLE, offset=(20, 20), timeout=20):
                    return True
                logger.warning('[Shop] left the event page but the shop did not show up')
                return False
            logger.info('[Shop] still on the event page, tap the tab again')

        logger.warning('[Shop] cannot open the shop')
        return False

    def shop_back(self):
        """
        退出商店，回活动页。

        返回键也会被吞（买完之后列表还在重排），所以给它和进页面一样的两次机会。
        `SHOP_BACK` 在左上角，商店页和活动页画的是同一颗，判据只能靠"活动页的
        木牌回来了没有"。

        Pages:
            in: page_shop
            out: page_event

        Returns:
            bool: 回到活动页了没有。
        """
        for _ in range(2):
            self.device.click(SHOP_BACK)  # alas-lint: allow - leaving the page, the event tab below confirms it
            if self.wait_until_appear(EVENT_TAB_SHOP, offset=(20, 20), timeout=15):
                return True
            logger.info('[Shop] still in the shop, tap back again')
        logger.warning('[Shop] cannot leave the shop')
        return False

    def shop_scroll_top(self):
        """
        把列表滚到最上面。

        进页面时的位置不一定是顶（上次退出时停在哪、重排之后又落在哪），所以每轮
        下手之前都先归位。连 swipe 两次是因为一次大约只滚 300 像素，而列表最长
        有 4 排（多滚几下到底之后就不再动了，不会出事）。
        """
        for _ in range(2):
            self.device.swipe(SHOP_SWIPE_FROM, SHOP_SWIPE_TO_TOP, duration=SHOP_SWIPE_DURATION)
        self.wait_until_still((SHOP_COLS[0], 92, SHOP_COLS[-1] + SHOP_CELL_WIDTH, 543),
                              timeout=SHOP_SETTLE_TIMEOUT)

    def shop_scroll_bottom(self):
        """
        把列表滚到最下面，让第三排完整露出来（那时它在 y 417）。
        """
        for _ in range(2):
            self.device.swipe(SHOP_SWIPE_FROM, SHOP_SWIPE_TO_BOTTOM, duration=SHOP_SWIPE_DURATION)
        self.wait_until_still((SHOP_COLS[0], 417, SHOP_COLS[-1] + SHOP_CELL_WIDTH, 638),
                              timeout=SHOP_SETTLE_TIMEOUT)

    # ---- 扫描 --------------------------------------------------------------

    def shop_scan(self, rows, page='top'):
        """
        扫一遍当前屏上这几排的格子。

        **碰到第一个「购买成功」就停**：已购的沉在列表最后，所以在它之后的每一格
        也都是已购的，没必要再读（可买的永远排在前面）。停下来之后照样把已经收进
        来的格子读一遍名字 —— 不然这一次扫到的商品全是空的，什么都买不了。

        Args:
            rows (tuple[int]): 每排的顶边 y，比如 `SHOP_ROWS_TOP`。
            page (str): 现在的滚动位置，会记在每一格上（`ShopGoods.page`）。

        Returns:
            list[ShopGoods]: 按网格顺序排好的格子，已含 name / paid / sold_out / code。
                最后一个若是 `sold_out`，说明后面全是已购的。
        """
        self.device.screenshot()
        image = self.device.image
        goods = []

        for top in rows:
            for col in range(len(SHOP_COLS)):
                item = ShopGoods(col=col, top=top, page=page)
                goods.append(item)
                if self.shop_sold_out(image, item):
                    item.sold_out = True
                    logger.info(f'[Shop] {item} — 购买成功, everything below it is sold out too')
                    return self.shop_fill(image, goods)

        return self.shop_fill(image, goods)

    def shop_fill(self, image, goods):
        """
        给扫出来的格子补上名字、代号、是不是付费道具。

        名字一次性读完（一次 cnocr 调用喂一批图，比一格一格叫快得多）。

        Args:
            image (np.ndarray):
            goods (list[ShopGoods]):

        Returns:
            list[ShopGoods]: 就是传进来的那个列表。
        """
        if not goods:
            return goods

        names = self.shop_read_names(image, goods)
        for item, name in zip(goods, names):
            item.name = name
            item.code = shop_code(name)
            item.paid = self.shop_read_paid(image, item)

        # 强化材料认的是"紧挨着装备右边"，所以整排的代号都算完再回头补一遍。
        by_cell = {(item.top, item.col): item for item in goods}
        for item in goods:
            left = by_cell.get((item.top, item.col - 1))
            item.left_code = left.code if left else ''
        return goods

    def shop_read_names(self, image, goods):
        """
        读一排格子的商品名。

        Args:
            image (np.ndarray):
            goods (list[ShopGoods]):

        Returns:
            list[str]: 和 `goods` 一一对应。
        """
        ocr = Ocr([], lang='cnocr', letter=(255, 255, 255), threshold=SHOP_NAME_THRESHOLD)
        ocr.SHOW_LOG = False
        areas = [self.shop_name_area(image, item) for item in goods]
        images = [crop(image, np.array(area)) for area in areas]
        return ocr.ocr(images, direct_ocr=True)

    @staticmethod
    def shop_name_area(image, item):
        """
        在格子里找名称那一行的确切位置。

        滚动到位的位置不是每次一样（惯性），所以不写死 y，改成读"格子下半部分
        里最强的那条白字带"。上面是商品图、下面是「各账号限量」那一行，两者都
        不算，所以按高度和"离标称位置多远"筛。

        Args:
            image (np.ndarray):
            item (ShopGoods):

        Returns:
            tuple[int]: (x1, y1, x2, y2) 拿去 OCR 的区域。
        """
        x1 = item.x + SHOP_NAME_OFFSET[0]
        x2 = x1 + SHOP_NAME_OFFSET[2]
        y1 = item.top + SHOP_NAME_SEARCH[0]
        y2 = item.top + SHOP_NAME_SEARCH[1]
        profile = (image[y1:y2, x1:x2].astype(int).max(axis=2) > SHOP_NAME_BRIGHT).sum(axis=1)
        nominal = item.top + SHOP_NAME_OFFSET[1] + SHOP_NAME_CENTER

        best, best_distance = None, SHOP_NAME_TOLERANCE + 1
        start = None
        for i, count in enumerate(list(profile) + [0]):
            if count >= SHOP_NAME_MIN_PIXELS and start is None:
                start = i
            elif count < SHOP_NAME_MIN_PIXELS and start is not None:
                top, bottom = y1 + start, y1 + i
                start = None
                if not SHOP_NAME_HEIGHT[0] <= bottom - top <= SHOP_NAME_HEIGHT[1]:
                    continue
                distance = abs((top + bottom) / 2 - nominal)
                if distance < best_distance:
                    best, best_distance = (top - 2, bottom + 2), distance

        if best is None:
            # 找不到（这一排只露出半截，或者写着「购买成功」把名字换掉了）——
            # 就按标称位置读，读不出来是空的，自然也匹配不上任何一条规则。
            return (x1, item.top + SHOP_NAME_OFFSET[1], x2, item.top + SHOP_NAME_OFFSET[3])
        return (x1, best[0], x2, best[1])

    def shop_sold_out(self, image, item):
        """
        这一格是不是已经买完了（写着「购买成功」）。

        「购买成功」压在价格那一行上，位置跟着格子走。`appear()` 的搜索范围由
        `Button.area` 定死、且 `Button.match()` 的模板和截图是反着传的，两样都用
        不上 —— 用 `match()` 在格子价格行附近重新找。

        Args:
            image (np.ndarray):
            item (ShopGoods):

        Returns:
            bool:
        """
        x1 = item.x + SHOP_SOLD_RELATIVE[0] - SHOP_SOLD_PAD
        y1 = item.top + SHOP_SOLD_RELATIVE[1] - SHOP_SOLD_PAD
        x2 = item.x + SHOP_SOLD_RELATIVE[2] + SHOP_SOLD_PAD
        y2 = item.top + SHOP_SOLD_RELATIVE[3] + SHOP_SOLD_PAD
        return match(image, SHOP_SOLD_OUT, (x1, y1, x2, y2)) > SHOP_SOLD_SCORE

    def shop_read_paid(self, image, item):
        """
        这一格的价格是不是钻石（付费道具）。

        这一期是「怪诞裙裾」那几件，但名字和商品图每期都会换，唯一不变的是价格
        左边那枚蓝钻石。活动币的图标每期都换（幽灵糖果 → 蓝粉糖果），共同点是
        **带粉** —— 所以"够蓝"和"不粉"两条一起看。

        Args:
            image (np.ndarray):
            item (ShopGoods):

        Returns:
            bool:
        """
        patch = crop(image, np.array((
            item.x + SHOP_PRICE_OFFSET[0], item.top + SHOP_PRICE_OFFSET[1],
            item.x + SHOP_PRICE_OFFSET[2], item.top + SHOP_PRICE_OFFSET[3],
        )))
        # uint8 直接相减会回绕，红比蓝亮的地方也会算成"蓝"。
        red = patch[:, :, 0].astype(int)
        blue = patch[:, :, 2].astype(int)
        blue_min, blue_light, blue_ratio = SHOP_PAID_BLUE
        pink_min, pink_light, pink_ratio = SHOP_PAID_PINK

        blue_mean = ((blue - red > blue_min) & (blue > blue_light)).mean()
        if blue_mean <= blue_ratio:
            return False
        pink_mean = ((red - blue > pink_min) & (red > pink_light)).mean()
        return pink_mean < pink_ratio

    def shop_pick(self, goods, rules):
        """
        按优先级挑**当前最该下手的那一格**：清单从上往下走，第一条还有货就不看第二条。

        只在同一优先级内部才看"哪一格" —— 那一档可能分几格卖（比如两格不同的限购），
        买完一格它会沉底，下一轮自然轮到另一格。

        Args:
            goods (list[ShopGoods]):
            rules (list[str]): `shop_filter_parse()` 的结果。

        Returns:
            ShopGoods: 没有可买的返回 None。
        """
        for rule in rules:
            for item in goods:
                if item.sold_out:
                    continue
                if self.shop_match(item, rule):
                    return item
        return None

    @staticmethod
    def shop_match(item, rule):
        """
        一个格子满不满足过滤器里的某一条。

        Args:
            item (ShopGoods):
            rule (str): 过滤器的一项，比如 `GachaTicket` / `EquipUR` / `魔法之丝`。

        Returns:
            bool:
        """
        if rule.lower() == 'paid':
            return item.paid
        if item.code and rule.lower() == item.code.lower():
            return True
        if rule.lower() == 'equipmaterial' and item.material:
            return True
        keyword = shop_plain(rule)
        return bool(keyword) and keyword in shop_plain(item.name)

    # ---- 购买 --------------------------------------------------------------

    def shop_buy_all(self):
        """
        按优先级把能买的都买一遍。

        每一轮都重新扫：买掉的那一格会沉底，后面的往前顶，位置全变了。

        Pages:
            in: page_shop
            out: page_shop

        Returns:
            int: 买了几次。
        """
        rules = shop_filter_parse(self.config.BrowndustEvent_ShopFilter)
        logger.attr('Shop priority', ' > '.join(rules))
        buy_max = str(self.config.BrowndustEvent_BuyAmount).lower() == 'max'

        bought = 0
        # 是被"买不动"停下来的，还是真的没有可买的了。收尾那句日志要分开说。
        broke = False

        for _ in range(SHOP_BUY_ROUNDS):
            # 一场 OCR 要一两秒，这期间一个点击都没有 —— 明说"我在盯着屏幕"，
            # 免得框架的卡死计时器把这当成卡住（硬约束 13）。
            self.device.stuck_record_clear()
            # 一轮要滚六次（`swipe()` 也会记进点击历史），两轮就把框架的
            # "同一个按钮点了 12 次"告警踩出来了。每一轮都是看了新截图重新决定
            # 的，上一轮的历史不该算在这一轮头上。
            self.device.click_record_clear()

            goods, page = self.shop_collect()
            target = self.shop_pick(goods, rules)
            if target is None:
                break
            # 扫描量到的坐标只在那一趟的滚动位置成立，先滚回去再点。
            if target.page != page:
                self.shop_goto(target.page)
            if not self.shop_buy(target, buy_max=buy_max):
                # 买不动了。**这里不降级去买后面的档**：清单是按价值排的，越靠后越
                # 不值，活动币每天涨、限购不会跑，今天买不起的那一档明天接着买。
                #
                # 但"买不动"有两种，得分开：这一档其实**已经买满**（只是刚才没识别
                # 出「购买成功」）要接着下一档；**有货但币不够**才是真的收工。
                # 判据就是"再看一眼这一格现在写的是什么"。
                self.shop_goto(target.page)
                self.device.screenshot()
                if self.shop_sold_out(self.device.image, target):
                    logger.info('[Shop] it turns out that one is sold out, go on with the next')
                    continue
                logger.info(f'[Shop] cannot afford {target}, stop here — '
                            f'everything below it on the list is worth less')
                broke = True
                break
            bought += 1
            # 买完之后游戏自己会滚回顶部，但别指望它 —— 下一轮从顶开始扫。
            self.shop_scroll_top()

        if not bought and not broke:
            logger.info('[Shop] nothing to buy today')
        return bought

    def shop_collect(self):
        """
        把整张列表上还买得到的东西都扫出来。

        先滚到顶扫前两排。**只有顶上没扫到「购买成功」才去滚到底看第三排** ——
        已购的沉在最后，扫到它就说明后面全是已购的，这一趟白跑。

        两屏的结果放在同一个列表里交给 `shop_pick()`，优先级才是按整张列表排的：
        第三排的抽抽乐券该排在第二排的精髓前面。

        Returns:
            tuple[list[ShopGoods], str]: 格子（按屏幕顺序）和扫完时停在哪（`top` /
                `bottom`）。格子上的坐标只在那个位置成立。
        """
        self.shop_scroll_top()
        goods = self.shop_scan(SHOP_ROWS_TOP, page='top')
        if goods and goods[-1].sold_out:
            logger.info('[Shop] the sold-out boundary is on the first screen, skip the third row')
            return goods, 'top'

        self.shop_scroll_bottom()
        goods += self.shop_scan(SHOP_ROWS_BOTTOM, page='bottom')
        return goods, 'bottom'

    def shop_goto(self, page):
        """
        把列表滚到扫描那一趟所在的位置 —— 格子坐标只在那时成立。

        Args:
            page (str): `top` 或 `bottom`。
        """
        if page == 'bottom':
            self.shop_scroll_bottom()
        else:
            self.shop_scroll_top()

    def shop_buy(self, item, buy_max=True):
        """
        点开一格、选数量、买下来。

        Pages:
            in: page_shop
            out: page_shop

        Args:
            item (ShopGoods):
            buy_max (bool): 买满限购次数（True）还是只买一个。

        Returns:
            bool: 买成了没有。
        """
        logger.info(f'[Shop] buy {item}')
        # 这一点是扫描时从这一帧截图上读出来的格子中心，不是写死的坐标；"点到
        # 了没有"由下面弹出的购买面板回答。列表刚重排完时还在动，一下点空是
        # 可能的 —— 归位之后再给一次机会。
        for _ in range(2):
            self.device.click(item.icon)  # alas-lint: allow - the cell was measured on the screenshot right above, SHOP_BUY_PANEL below is the proof it took
            if self.wait_until_appear(SHOP_BUY_PANEL, offset=(30, 30), timeout=SHOP_PANEL_TIMEOUT):
                break
            logger.info('[Shop] the cell did not open, align the list and try again')
            self.shop_goto(item.page)
        else:
            logger.warning('[Shop] the purchase dialog did not show up')
            return False
        # 面板是淡入的，第一帧就能匹配到 1.00 但按下去不算数（魔兽的确认框、
        # 推荐部署面板都栽过），等它画稳。
        self.wait_until_still(SHOP_PANEL_AREA, timeout=3)

        if buy_max:
            self.device.click(SHOP_AMOUNT_MAX)  # alas-lint: allow - the dialog was matched above, 「购买完成。」below is the proof
            self.wait_until_still(SHOP_PANEL_AREA, timeout=3)

        self.device.click(SHOP_CONFIRM)  # alas-lint: allow - same dialog, same proof
        if not self.wait_until_appear(SHOP_BUY_DONE, offset=(30, 30), timeout=SHOP_DONE_TIMEOUT):
            # 多半是活动币不够买哪怕一个（MAX 已经按余额截过了），偶尔是这一档
            # 刚好在这几秒里被别人买空。拍照留证、关掉弹窗，交给调用方判断该继续
            # 还是收工。
            logger.warning('[Shop] the purchase did not go through')
            self.device.save_screenshot(genre='shop_buy_failed')
            if self.appear(SHOP_BUY_PANEL, offset=(30, 30)):
                self.device.click(SHOP_PANEL_CLOSE)  # alas-lint: allow - a plain close X
                self.wait_until_disappear(SHOP_BUY_PANEL, offset=(30, 30), timeout=5)
            return False

        self.device.click(SHOP_DONE_OK)  # alas-lint: allow - 「购买完成。」was just matched
        if not self.wait_until_disappear(SHOP_BUY_DONE, offset=(30, 30), timeout=10):
            logger.warning('[Shop] the「购买完成。」alert did not go away')
            return False
        return True
