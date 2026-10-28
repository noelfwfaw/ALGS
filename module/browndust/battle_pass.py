"""
通行证领取 (Brown Dust II).

实机看到的样子（2026-10-28，截图在 `screenshots/browndust/`）：

    page_main   --右侧那枚「RETURN / 通行证」图标-->  page_pass
    page_pass   左边是一列通行证卡片（本期 5 张），每张卡片右上角带一枚红「!」，
                表示这张通行证有东西可以领；右边是选中的那张的详情
                （LEVEL + 基础 [+ 豪华] 三列奖励，底部右下角「全部获得」）
    ...         点一张卡 -> 右边换成它的详情，**「全部获得」把这张通行证的任务和
                奖励一起领掉**，弹 REWARD 结算页 -> 点画面任意处回同一页
    ...         领完之后那张卡的红点消失、「全部获得」变灰

为什么只能靠左列的红点定位（用户 2026-10-28 的原话："通行证每期都不一样，而且有
很多个。你可以像抽卡一样定位左边的红点去点不同的通行证，没有红点的就是没有东西
可以领"）：

- 通行证是按赛季/活动一批批换的，卡片上的名字（「特别赛季通行证」「Loyal Maid
  赛季通行证」「毁灭之星艾瑞克角色通行证」）每次都不一样，立绘也会换，**没法写死
  任何一张卡的名字、位置或用模板认卡片**；
- 红「!」是游戏自己画的"这张有东西可领"，跟卡片内容无关，所以它同时回答了
  "哪张要开"和"还有没有剩余"；
- 一屏放得下 5 张卡，卡片行距实测 85 px（红点 y = 242 / 327 / 412 / 497）。

三个不是从截图上能看出来、必须实机量的事实：

1. **红点只钉在卡片右缘那条窄带里**（x=274~290）。卡片本身的立绘里红色很多
   （Loyal Maid 是紫红、毁灭之星是红披风），扫整张卡会把立绘当成徽标。
2. **「全部获得」在五种通行证里的位置是同一个**（(933,518)-(1090,564)），哪怕
   列数从两列（角色通行证）变成三列（赛季通行证）、面板底色从绿换成紫/橙。
   但**它外围那圈彩绘背景每次都不同**，所以模板只取胶囊内的一段，否则同一个
   按钮的相似度会从 0.98 掉到 0.84，正好压在 0.85 的阈值上。
3. **结算页盖不住这一页**：REWARD 横条只盖中间，通行证页的标题照样 0.966、
   「全部获得」照样 0.916~0.960，所以"按下去有没有领到"只能看红点有没有消失，
   不能看按钮还在不在（硬约束 79/96）。
"""
from module.base.timer import Timer
from module.base.utils import color_mask
from module.browndust.assets import HUNT_REWARD, PASS_CLAIM
from module.browndust.browndust_ui import BrowndustUI, page_main, page_pass
from module.logger import logger

import cv2
import numpy as np

# 左列卡片右缘那条窄带。红「!」是 16x16，钉在 x=274~290，卡片立绘全在 x<274
# 里，所以只扫这一条 —— 扫整张卡时 Loyal Maid 的紫红立绘和毁灭之星的红披风
# 都会被当成徽标（抽抽乐的卡池列表踩过同一个坑）。
PASS_LIST = (268, 80, 298, 560)
# 徽标红：(202,63,50)，14x14 的框里约 100 个像素。
PASS_BADGE_COLOR = (202, 63, 50)
PASS_BADGE_THRESHOLD = 60
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

# 结算页底部写着「点击画面即可返回。」，这一片是空的。和邮箱 (620,700)、
# 任务 (620,700) 落在同一条空白带上。
PASS_REWARD_TAP = (620, 700)

# 点图标到页面出来：实机 1.8 秒，慢的模拟器按 25 秒兜底。
PASS_ENTRY_TIMEOUT = 25
# 点一张卡到右边详情画完。卡片是原位切换，没有转场，10 秒足够。
PASS_CARD_TIMEOUT = 10
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
        self.pass_close_reward()

        claimed = 0
        # 试过但没领成的红点（y 坐标）。记下来是为了不在一张废卡上打转 ——
        # 红点还在但「全部获得」是灰的，说明这张的"有新任务"和"有奖励可领"
        # 不是一回事，跳过它继续下一张。
        skipped = set()

        for _ in range(PASS_ROUNDS_MAX):
            self.device.screenshot()
            badges = [b for b in self.pass_badges() if b[1] not in skipped]
            if not badges:
                break

            badge = badges[0]
            for i in range(PASS_CARD_TRIES):
                if self.pass_claim_one(badge):
                    claimed += 1
                    break
                logger.warning(f'The pass at {badge[1]} was not claimed ({i + 1}/{PASS_CARD_TRIES})')
            else:
                skipped.add(badge[1])

        logger.info(f'[Pass claimed] {claimed}')
        return claimed

    def pass_claim_one(self, badge):
        """
        Open one pass, press 全部获得 and close the reward screen.

        The press is verified by the badge disappearing - the only observation
        that answers "did it land". Everything else on this page survives the
        reward screen: the title scores 0.966 through it and even
        「全部获得」 itself still scores 0.916~0.960, so neither can tell
        "claimed" from "still up".

        Pages:
            in: page_pass
            out: page_pass

        Args:
            badge (tuple[int, int]): Centre of the 「!」 on that pass's card.

        Returns:
            bool: If the badge is gone afterwards, i.e. this pass was claimed.
        """
        self.pass_open_card(badge)
        if self.pass_close_reward():
            # 上一轮留下的结算页被点掉了，这一帧的亮度不可信，重新看一次。
            self.device.screenshot()

        if not self.pass_claim_ready():
            logger.warning('「全部获得」 is grey on this pass, nothing to claim there')
            return False

        logger.info('Press 全部获得')
        self.device.click(PASS_CLAIM)  # alas-lint: allow - guarded by pass_claim_ready() right above and verified by the badge below
        if not self.pass_close_reward():
            # 结算页没关掉（或者根本没弹）。两条路都读不出"红点还在不在"：
            # 横条盖着时左列那一片会变暗，`pass_badges()` 返回空 —— 拿它当证据
            # 会把"没领成"记成"领成了"。这里宁可报没领成，让调用方再试一次，
            # 由轮数上限收场，剩下的交给 `ui_goto_main()` 把横条点掉。
            logger.warning('The reward screen did not close, the pass list is not readable')
            return False

        self.device.screenshot()
        return badge[1] not in {b[1] for b in self.pass_badges()}

    def pass_open_card(self, badge):
        """
        Select the pass whose card carries the badge.

        A card press repaints the whole detail panel, and the panel comes back
        with 「全部获得」 in the same place for every pass type (两列/三列、绿/紫/橙
        底都一样), so there is no position change to wait for - only "it stopped
        moving".

        Pages:
            in: page_pass
            out: page_pass

        Args:
            badge (tuple[int, int]): Centre of the 「!」 on that card.

        Returns:
            bool: If the panel settled.
        """
        point = (badge[0] + PASS_CARD_DX, badge[1])
        logger.info(f'Open the pass at {point}')
        self.device.click_minitouch(point[0], point[1])  # alas-lint: allow - a card press in the list, verified by the badge check in pass_claim_one()
        self.wait_until_still(PASS_CLAIM.area, timeout=PASS_CARD_TIMEOUT)
        return True

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
        mask = color_mask(self.image_crop(PASS_LIST, copy=False),
                          color=PASS_BADGE_COLOR, threshold=PASS_BADGE_THRESHOLD)
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
