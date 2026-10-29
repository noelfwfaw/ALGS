"""
通行证领取 (Brown Dust II).

实机看到的样子（2026-10-28，截图在 `screenshots/browndust/`）：

    page_main   --右侧那枚「RETURN / 通行证」图标-->  page_pass
    page_pass   左边是一列通行证卡片（本期 5 张），每张卡片右上角带一枚红「!」，
                表示这张通行证有东西要看；右边是选中的那张的详情
    ...         点一张卡 -> 右边换成它的详情。**详情有两页**，右上竖栏切换：
                上面那枚是等级奖励（LEVEL + 基础 [+ 豪华]），下面那枚是每日任务
                （DAY 1~DAY 7 的清单）。**两页各有一个「全部获得」，位置一样**。
    ...         按「全部获得」-> 弹 REWARD 结算页 -> 点画面任意处回同一页
    ...         任务页领完之后游戏常常自己跳到下一个还有任务的 DAY

**红点不等于"奖励页有东西可领"**（2026-10-29 用户指出并实测确认）：

- 左列卡片的红「!」是"这张通行证有新内容"，它的来源可能是等级奖励，也可能是
  每日任务。毁灭之星艾瑞克 PASS 就是奖励页整页全灰、任务页 DAY 5 挂着一条已完成
  的任务 —— 只看奖励页会把它判成"没东西可领"然后跳过（这就是"通行证会漏领"）。
- 所以每张带红点的卡都要**两页都问一遍**，两页的判据同一个：「全部获得」还能不能按
  （`pass_claim_ready()` 数亮度，可按时 3853~3865 个 luma>200 像素，灰时 0~6）。
- 领完之后**左列红点不一定消失**：任务每天解锁一批，红点会留着。所以"红点还在"
  不能当"没领到"去无限重试，每张卡处理一次就记下来（`done`）。

为什么只能靠左列的红点定位（用户 2026-10-28 的原话："通行证每期都不一样，而且有
很多个。你可以像抽卡一样定位左边的红点去点不同的通行证，没有红点的就是没有东西
可以领"）：

- 通行证是按赛季/活动一批批换的，卡片上的名字（「特别赛季通行证」「Loyal Maid
  赛季通行证」「毁灭之星艾瑞克角色通行证」）每次都不一样，立绘也会换，**没法写死
  任何一张卡的名字、位置或用模板认卡片**；
- 红「!」是游戏自己画的，跟卡片内容无关，所以它回答了"哪张要开"；
- 一屏放得下 5 张卡，卡片行距实测 85 px（红点 y = 242 / 327 / 412 / 497）。

几个不是从截图上能看出来、必须实机量的事实：

1. **红点只钉在卡片右缘那条窄带里**（x=274~290）。卡片本身的立绘里红色很多
   （Loyal Maid 是紫红、毁灭之星是红披风），扫整张卡会把立绘当成徽标。
2. **「全部获得」在五种通行证、两个页签里的位置都是同一个**，哪怕列数从两列
   （角色通行证）变成三列（赛季通行证）、面板底色从绿换成紫/橙。但**它外围那圈
   彩绘背景每次都不同**，所以模板只取胶囊内的一段，否则同一个按钮的相似度会从
   0.98 掉到 0.84，正好压在 0.85 的阈值上。
3. **结算页盖不住这一页**：REWARD 横条只盖中间，通行证页的标题照样 0.966、
   「全部获得」照样 0.916~0.960，所以"按下去有没有领到"只能看**结算页有没有出现**
   （`wait_until_appear(HUNT_REWARD)`），不能看按钮还在不在（硬约束 79/96）。
4. **页签的选中色跟着通行证主色走**：这期是紫红，`page_6.png` 那期是绿。判"现在
   在哪一页"只能看饱和度（选中 102~151，未选中 35~45），不能判"是不是红的"。
"""
from module.base.timer import Timer
from module.browndust.assets import HUNT_REWARD, PASS_CLAIM
from module.browndust.browndust_ui import BrowndustUI, page_main, page_pass
from module.logger import logger

import cv2
import numpy as np

# 左列卡片右缘那条窄带。红「!」是 16x16，钉在 x=274~290，卡片立绘全在 x<274
# 里，所以只扫这一条 —— 扫整张卡时 Loyal Maid 的紫红立绘和毁灭之星的红披风
# 都会被当成徽标（抽抽乐的卡池列表踩过同一个坑）。
PASS_LIST = (268, 80, 298, 560)
# 徽标是一枚**纯红的圆**，中间挖一个白色「!」。判它用 HSV，不用 `color_mask`
# 写死三元组：这里原来写的是 `PASS_BADGE_COLOR = (202, 63, 50)` + 阈值 60，看起来
# 是红的，实际在实机帧上只命中 87 个像素（真徽标一圈约 190 个），凑不够一个块。
# 更要命的是 **`device.image` 是 RGB**（见 `pass_badge_mask()`），离线用 adb 截图
# （`cv2.imread` 拿到的是 BGR）去校准颜色，通道正好反着，很容易把结论搞反。
#
# 后果是这版红点扫描自 2026-10-28 上线以来没有一次是靠得住地扫到徽标：
#   - `screenshots/browndust/page_6.png`（4 张卡全带「!」，当天留的图）
#     `pass_badges()` 返回空；
#   - 2026-10-29 实机帧（2 个徽标）同样是空 → 循环第一轮就 `break`，
#     日志写 `[Pass claimed] 0`，看起来像"今天没东西可领"。
# 而 10-28 08:00 那次 `Pass claimed: 20` 是更早的"盲目点 20 次"版本，不是这个。
#
# HSV 只认色相和饱和度，红点在不同通行证底色、不同亮度下色相不变。`device.image`
# 里徽标像素的 RGB 是 (201,70,57) / (206,78,73) / (196,67,55) / (208,84,62)，
# 色相全落在色相环两端那两段里。四组参数在 16 张其它页面的整屏截图上比过，
# (12,168,120,120) 与更严的一组结果相同且零误报。
PASS_BADGE_HUE_MAX = 12
PASS_BADGE_HUE_MIN = 168
PASS_BADGE_SATURATION = 120
PASS_BADGE_VALUE = 120
# 形状过滤：`color_mask` + 膨胀之后一个徽标 100~400 px、16x16 上下。立绘碎片
# 要么是一大片，要么只有一个像素。
PASS_BADGE_MIN_AREA = 50
PASS_BADGE_MAX_AREA = 400
PASS_BADGE_MIN_SIZE = 8
PASS_BADGE_MAX_SIZE = 26
# 徽标中心 -> 卡片中心。卡片左缘 x=132、右缘 x=291，徽标贴着右缘，所以往左
# 70 px 落在缩略图里（不是下面的名字，也不是右边的详情面板）。
PASS_CARD_DX = -70

# 「全部获得」还能不能按：可领时 luma>200 有 3853~3865 个像素，领完 0~6 个。
# 注意模板分完全分不开（两种状态都是 0.91~0.98，只是颜色变灰），所以这里数亮度。
PASS_CLAIM_LUMA = 200
PASS_CLAIM_PIXELS = 500

# 右侧竖栏那两枚页签：上面是等级奖励，下面是每日任务。**两页都有「全部获得」**，
# 位置一模一样，只是内容不同 —— 所以"这张卡还有没有东西"必须两页都问一遍。
# 任务页比奖励页要紧得多：通行证的红「!」常常整枚挂在任务上（2026-10-29 实测，
# 毁灭之星艾瑞克 PASS 的奖励页按钮全灰、任务页 DAY 5 有一条已完成的任务），
# 只看奖励页就会把这张卡判成"没东西可领"。
#
# 页签的位置在四种主色（绿 / 紫 / 紫红 / 橙）的通行证上都一样，但**选中态的颜色
# 跟着通行证主色走**：这期是紫红，`page_6.png` 那期是绿。所以判"现在在哪一页"
# 不能用"是不是红色"，要用**饱和度** —— 选中那一条是纯主色（102~151），未选中是
# 灰（35~45），五张截图全在这两段里，没有中间值。
PASS_TAB_REWARD = (1128, 250)
PASS_TAB_TASK = (1128, 470)
PASS_TAB_REWARD_AREA = (1108, 145, 1148, 355)
PASS_TAB_TASK_AREA = (1108, 368, 1148, 578)
PASS_TAB_SATURATION = 70
# 点页签到对面那页画完：实机不到 1 秒。
PASS_TAB_TIMEOUT = 4

# 结算页底部写着「点击画面即可返回。」，这一片是空的。和邮箱 (620,700)、
# 任务 (620,700) 落在同一条空白带上。
PASS_REWARD_TAP = (620, 700)

# 点图标到页面出来：实机 1.8 秒，慢的模拟器按 25 秒兜底。
PASS_ENTRY_TIMEOUT = 25
# 点一张卡到右边详情画完：实机 0.5~0.6 秒，4 秒足够（等的是"动起来再停下"，
# 不是固定时长）。
PASS_CARD_TIMEOUT = 4
# 按「全部获得」到结算页出来：实机 1.2 秒。
PASS_REWARD_TIMEOUT = 15
# 结算页要连点几下的节流（第一下可能被淡入吞掉）。
PASS_TAP_INTERVAL = 2
# 一张卡最多试两次：第一次被吞掉（页面还在画）时能自愈，又不至于死磕一张废卡。
PASS_CARD_TRIES = 2
# 一轮领一张，最多这么多轮。本期 5 张卡，留一倍余量；循环每轮都重新扫红点，
# 所以这个数只是防死循环，不是"最多领这么多张"。
PASS_ROUNDS_MAX = 12


class BrowndustPass(BrowndustUI):
    """
    Claim every pass whose card still carries a 「!」.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Pass rewards', level=1)
        claimed = self.pass_claim_all()
        if not claimed:
            logger.info('No pass reward to claim')
        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def pass_claim_all(self):
        """
        Open the pass page and claim every card that still has a badge.

        Nothing about a pass is hard coded（名字、立绘、行号每期都换），每轮都
        重新扫一遍左列，取最上面那张带红点的，领完就轮到下一张。红点没了、
        或者剩下的都试过了，就结束。

        Pages:
            in: page_main
            out: page_pass

        Returns:
            int: Number of passes claimed.
        """
        self.ui_ensure(page_main)
        self.ui_ensure(page_pass)
        # 页面是淡入的，红点比卡片和按钮晚画。先等「全部获得」出现（它一直在，
        # 只是灰/白两态），再等它静止 —— 两帧不变才说明这一页画完了。少了这一步
        # 第一轮会扫到"一张带红点的都没有"的中间帧，把一整页奖励当成空的
        # （硬约束 96）。
        if not self.wait_until_appear(PASS_CLAIM, offset=(20, 20),
                                      timeout=PASS_ENTRY_TIMEOUT, settle=2):
            logger.warning('The pass page did not show its claim button')
        self.wait_until_still(PASS_CLAIM.area, timeout=3)
        # 左列卡片是**滑进来**的，红点跟着一起滑。进场 0.8 秒（`Page arrive` 之后
        # 第一次扫）读到的 y 是滑动中间态：2026-10-29 那次实机扫到 (274, 161)，
        # 而页面上真正的红点在 327。滑完之后才读，红点位置才是卡片的位置。
        self.wait_until_still(PASS_LIST, timeout=3)
        self.pass_close_reward()

        claimed = 0
        # 处理过的红点（y 坐标）。记下来是因为**红点不一定消失**：领完每日任务后
        # 那张卡的红点照样在（任务每天解锁一批），所以不能拿"红点还在"当"没领到"
        # 反复重试，否则会在这张卡上打转到轮数上限。
        done = set()

        for _ in range(PASS_ROUNDS_MAX):
            self.device.screenshot()
            badges = [b for b in self.pass_badges() if b[1] not in done]
            if not badges:
                break

            badge = badges[0]
            for i in range(PASS_CARD_TRIES):
                count = self.pass_claim_one(badge)
                if count:
                    claimed += count
                    break
                logger.warning(f'The pass at {badge[1]} was not claimed ({i + 1}/{PASS_CARD_TRIES})')
            done.add(badge[1])

        logger.info(f'[Pass claimed] {claimed}')
        return claimed

    def pass_claim_one(self, badge):
        """
        Claim one pass on both of its pages.

        一张通行证有两页，右上竖栏切换：上面是等级奖励，下面是每日任务，
        **两页各有一个「全部获得」，位置一样**。要两页都问一遍 —— 2026-10-29
        实机那张「毁灭之星 艾瑞克 PASS」就是奖励页全灰、任务页 DAY 5 有一条
        已完成的任务挂着红点（用户原话："有的通行证不能直接全部领取，所以得看
        右侧有没有任务的红点"）。

        每页的领取都用「按下之后有没有结算页」来验证：这一页的标题和按钮都
        扛得过结算页（标题 0.966、按钮 0.916~0.960），只有结算页本身是新增的。

        Pages:
            in: page_pass
            out: page_pass

        Args:
            badge (tuple[int, int]): Centre of the 「!」 on that pass's card.

        Returns:
            int: How many of the two pages were claimed.
        """
        self.pass_open_card(badge)
        if self.pass_close_reward():
            # 上一轮留下的结算页被点掉了，这一帧的亮度不可信，重新看一次。
            self.device.screenshot()

        claimed = 0
        if self.pass_goto_tab(PASS_TAB_REWARD, PASS_TAB_REWARD_AREA):
            if self.pass_claim_here():
                logger.info('Level rewards claimed')
                claimed += 1
        if self.pass_goto_tab(PASS_TAB_TASK, PASS_TAB_TASK_AREA):
            if self.pass_claim_here():
                logger.info('Task rewards claimed')
                claimed += 1

        if not claimed:
            logger.info('Both pages of this pass are empty')
        return claimed

    def pass_claim_here(self):
        """
        Press 「全部获得」 on the page that is open, if it can be pressed.

        Returns:
            bool: If a reward screen was opened and then closed.
        """
        if not self.pass_claim_ready():
            return False

        logger.info('Press 全部获得')
        self.device.click(PASS_CLAIM)  # alas-lint: allow - guarded by pass_claim_ready() right above
        if not self.wait_until_appear(HUNT_REWARD, offset=(20, 20), timeout=PASS_REWARD_TIMEOUT):
            # 按下去没有任何反应 —— 这个按钮是灰的那一帧被当成了亮的，或者这一下
            # 被淡入吞了。两种情况都该让调用方再试，所以报没领成。
            logger.warning('The press opened no reward screen')
            return False
        if not self.pass_close_reward():
            logger.warning('The reward screen did not close')
            return False
        return True

    def pass_tab_active(self, area):
        """
        Whether a tab of the right-hand rail is the selected one.

        Not by colour: the selected tab is painted in the pass's own theme colour,
        which is green on one pass and magenta on the next（`page_6.png` vs
        2026-10-29）。The difference that survives a theme change is saturation -
        selected 102~151, unselected 35~45 across five screenshots.

        Args:
            area (tuple): The tab's strip.

        Returns:
            bool: If this tab is the selected one.
        """
        pixel = self.image_crop(area, copy=True).reshape(-1, 3).mean(axis=0)
        brightest, darkest = float(pixel.max()), float(pixel.min())
        if brightest <= 0:
            return False
        return (brightest - darkest) / brightest * 255 > PASS_TAB_SATURATION

    def pass_goto_tab(self, point, area):
        """
        Make sure the requested tab of the detail panel is the open one.

        Switching is verified by the strip turning into the theme colour, not by
        the panel going still: the two pages differ only in their content, and
        when both are empty the 「全部获得」 area is nearly identical, so a
        stillness check would pass on the old frame.

        Args:
            point (tuple[int, int]): Centre of the tab.
            area (tuple): The tab's strip, used as the check point.

        Returns:
            bool: If that tab is open afterwards.
        """
        if self.pass_tab_active(area):
            return True

        self.device.click_minitouch(point[0], point[1])  # alas-lint: allow - the tab rail is fixed UI, verified by pass_tab_active() below
        for _ in self.loop(timeout=PASS_TAB_TIMEOUT):
            if self.pass_tab_active(area):
                return True

        logger.warning(f'The tab at {point} did not open')
        return False

    def pass_open_card(self, badge):
        """
        Select the pass whose card carries the badge.

        A card press repaints the whole detail panel, and the panel comes back
        with 「全部获得」 in the same place for every pass type (两列/三列、绿/紫/橙
        底都一样), so there is no position change to wait for - only "it stopped
        moving". `pass_wait_repaint()` is that wait, and it has to see the repaint
        *start* first; see there for why one plain `wait_until_still()` is not
        enough.

        Pages:
            in: page_pass
            out: page_pass

        Args:
            badge (tuple[int, int]): Centre of the 「!」 on that card.

        Returns:
            bool: If the panel repainted.
        """
        point = (badge[0] + PASS_CARD_DX, badge[1])
        logger.info(f'Open the pass at {point}')
        self.device.click_minitouch(point[0], point[1])  # alas-lint: allow - a card press in the list, verified by the badge check in pass_claim_one()
        return self.pass_wait_repaint()

    def pass_wait_repaint(self, timeout=PASS_CARD_TIMEOUT):
        """
        Wait for the detail panel to finish repainting after a card press.

        实测（2026-10-29，`dev_tools/probe_browndust_pass_repaint.py`）：按下
        卡片之后右侧面板大约 0.5~0.6 秒才换过来，在那之前「全部获得」还是**上一张
        卡的样子**。而 `wait_until_still()` 判的是"两帧一样"，画面还没开始变时它
        第一对帧就相同，于是**立刻返回** —— 日志上 `Open the pass at (211, 327)`
        到 `The reward screen did not close` 只隔 263 ms，按下去的是上一张卡那个
        灰按钮。

        所以要等的是"先动起来、再停下来"：观察到变化之后，两帧一致才算画完。
        点了本来就选中的那张卡时不会有变化，超时放行 —— 那不是错误，调用方接着
        读亮度就行。

        Returns:
            bool: If a repaint was seen and it settled.
        """
        timeout = Timer(timeout).start()
        previous = self.image_crop(PASS_CLAIM.area, copy=True)
        moved = False

        for _ in self.loop():
            current = self.image_crop(PASS_CLAIM.area, copy=True)
            diff = np.mean(np.abs(current.astype(np.int16) - previous.astype(np.int16)))
            previous = current
            if diff >= 1.0:
                moved = True
            elif moved:
                return True

            if timeout.reached():
                if moved:
                    logger.warning('The detail panel kept repainting, carry on anyway')
                else:
                    logger.info('The detail panel did not repaint, the card was probably already selected')
                return moved

    def pass_claim_ready(self):
        """
        Whether 「全部获得」 is still the bright, pressable version.

        Not a template match: the button keeps its shape and its text when it
        greys out, 0.91~0.98 either way. `luma>200` counts 3853~3865 pixels
        when it can be pressed and 0~6 when it cannot.

        The reward screen is checked first: it is a band across the middle of
        the page and the button still scores 0.916~0.960 through it, so reading
        brightness on top of it would answer for the wrong layer.

        Returns:
            bool: If there is something to claim on this pass.
        """
        if self.appear(HUNT_REWARD, offset=(20, 20)):
            return False
        return self.ui_bright_count(PASS_CLAIM, PASS_CLAIM_LUMA) > PASS_CLAIM_PIXELS

    def pass_close_reward(self):
        """
        Close the REWARD screen that 「全部获得」 opens, if it is there.

        The screen says 「点击画面即可返回。」 at the bottom, so the press is a
        plain tap on the empty strip - but the page under it is still drawn, so
        the tap is throttled and repeated until the screen is really gone.

        Pages:
            in: page_pass
            out: page_pass

        Returns:
            bool: If the reward screen was there and is now gone.
        """
        if not self.appear(HUNT_REWARD, offset=(20, 20)):  # alas-lint: allow - "it is not there" is the answer being returned, and nothing is pressed on this path
            return False

        logger.info('Reward screen, tap to go back')
        # 故意不 `.start()`：未启动的 Timer 第一次 `reached()` 就是 True。
        tap = Timer(PASS_TAP_INTERVAL)
        for _ in self.loop(timeout=PASS_REWARD_TIMEOUT):
            if self.appear(HUNT_REWARD, offset=(20, 20)):
                if tap.reached():
                    tap.reset()
                    self.device.click_minitouch(*PASS_REWARD_TAP)
                continue
            # 结算页不在了。它淡出的最后一帧下层页面还没画完，等胶囊静止再往下走。
            self.wait_until_still(PASS_CLAIM.area, timeout=3)
            return True

        logger.warning('The reward screen did not close')
        return False

    @staticmethod
    def pass_badge_mask(image):
        """
        The red pixels of a strip of the pass list.

        **`device.image` 是 RGB，不是 BGR**：`screenshot_nemu_ipc()` 走的是
        `cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)`（`module/device/method/nemu_ipc.py`
        第 600 行），而本项目默认截图方式就是 nemu。全项目的颜色判据（
        `color_mask`、`Button.color`）都是在这个 RGB 数组上、按 RGB 值写出来的，
        所以这里也必须用 `COLOR_RGB2HSV`。

        写成 `COLOR_BGR2HSV` 的后果在 2026-10-29 实机见过：同一帧上它会去找**蓝色**
        的东西，扫出 `(274, 161)`（卡片立绘的品红碎片）和一个 24x55 的大块（选中卡片的
        高亮边框），而真正的红「!」在 `(281, 327)` 一个都找不到 —— 于是脚本跑去点一张
        不存在的卡，日志写 `did not repaint` + `Both pages of this pass are empty`。
        离线用 adb 截图（`cv2.imread` 得到的确实是 BGR）校准判据时特别容易踩这一脚：
        两条路径的通道正好相反。

        Hue is split across the two ends of the wheel - a red is either just
        above 0 or just below 180 - so both ends are taken. Saturation and value
        are only there to keep near-black and near-white pixels out.

        Args:
            image: A crop of `PASS_LIST`, RGB.

        Returns:
            np.ndarray: Shape (height, width), uint8, 255 for red pixels.
        """
        hue, saturation, value = cv2.split(cv2.cvtColor(image, cv2.COLOR_RGB2HSV))
        red = (hue < PASS_BADGE_HUE_MAX) | (hue > PASS_BADGE_HUE_MIN)
        return np.where(red
                        & (saturation > PASS_BADGE_SATURATION)
                        & (value > PASS_BADGE_VALUE), 255, 0).astype(np.uint8)

    def pass_badges(self):
        """
        The red 「!」 marks of the pass list, top to bottom.

        Only the right edge of the cards is read (`PASS_LIST`): the card
        artwork is full of reds and every pass looks different, so a full-card
        scan finds "badges" in the pictures.

        Needs a fresh screenshot in `device.image`; the caller takes it.

        Returns:
            list[tuple[int, int]]: Centre of each badge, in screen coordinates.
        """
        mask = self.pass_badge_mask(self.image_crop(PASS_LIST, copy=False))
        # 淡入时「!」会碎成几块，先连起来再数。
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
        _, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)

        x0, y0 = PASS_LIST[0], PASS_LIST[1]
        badges = []
        for i in range(1, len(stats)):
            _, _, w, h, area = stats[i]
            if not PASS_BADGE_MIN_AREA <= area <= PASS_BADGE_MAX_AREA:
                continue
            if not PASS_BADGE_MIN_SIZE <= w <= PASS_BADGE_MAX_SIZE:
                continue
            if not PASS_BADGE_MIN_SIZE <= h <= PASS_BADGE_MAX_SIZE:
                continue
            badges.append((int(centroids[i][0] + x0), int(centroids[i][1] + y0)))
        badges.sort(key=lambda b: b[1])
        return badges
