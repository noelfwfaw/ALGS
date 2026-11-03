"""关掉活动期的签到通行证弹窗（「万圣节签到通行证」那版）。

活动期（2026.10.29~11.12）每天登录，游戏把通行证面板弹在大厅前面。关它是一套
舞步（2026-11-04 实测）：点 ✕ → 游戏把当天的签到奖励发了，「已获得道具」弹出来
→ 点掉它 → 面板带着勾弹回来 → 再点一次 ✕ → 回大厅。面板「领奖前」和「领完弹
回来」两个状态都会挡住大厅，boot 循环不认识它们，300 秒 BOOT_TIMEOUT 直接
耗光（冷启动卡死在这里）。

所以这一支跟 `handle_offer_popup()` 同款：一次一击 —— 在场就点一下 ✕，舞步
的剩下两步（领奖弹窗、弹回来的面板）由调用方的循环一圈圈接：

  - boot 循环：`handle_event_pass()` 和「已获得道具」分支各一圈；
  - `ui_additional()`：本支 + 既有的 reward popup 分支。

跟 sign_in.py / offer.py 一样单独放一支：混入 `LostswordUI` 使用，
`handle_app_boot()` 和 `ui_additional()` 各挂一次，前者管冷启动撞上，
后者管跑到一半撞上。

换活动（同款版式、标题换了）时：重抓一张弹窗整屏存成 `EVENT_PASS_POPUP.png`
（整屏，硬约束 105；button_extract 按整屏 bbox 生成 area，幂等），改
`EVENT_PASS_TITLE_AREA` 的判据坐标，再从新截图裁一枚右上角 ✕ 存成
`EVENT_PASS_CLOSE.png`，处理逻辑不动。
"""
import cv2

from module.base.timer import Timer
from module.base.utils import crop
from module.logger import logger
from module.lostsword.assets import EVENT_PASS_CLOSE, EVENT_PASS_POPUP

# 判据：面板标题「万圣节签到通行证」+ 日期行。领奖前后这一块一个像素都不变
# （变的是奖品格子的高亮和勾），所以领完弹回来的那一版也认得 —— 判据必须选
# 不变的元素（硬约束 103 同款思路），整屏对比会认不出第二版。
# 实测（2026-11-04，模板 = 整屏 PNG 按 `EVENT_PASS_TITLE_AREA` 裁 418x50）：
#
#   弹窗领奖前 1.000、领完弹回来 1.000
#   关掉后的大厅 -0.033
#   94 张历史整屏（大厅 / 战斗 / 弹窗 / 加载页）最高 0.068
#
# 0.85 两边余量都大。
EVENT_PASS_TITLE_AREA = (150, 128, 568, 178)
EVENT_PASS_SIMILARITY = 0.85


class EventPassPopup:
    """
    关掉活动期的签到通行证弹窗。

    混入 `LostswordUI` 使用，不单独实例化。
    """

    # ✕ 的冷却。关掉要过「领奖弹窗 → 面板弹回来」两步，按太快会对着中间
    # 状态乱按（领奖弹窗上的任意点都可能点到格子的道具说明）。
    EVENT_PASS_BACK = Timer(2)

    @staticmethod
    def _event_pass_score(image):
        """
        标题块在屏上的匹配分。

        模板从整屏 PNG 按 `EVENT_PASS_TITLE_AREA` 现裁（`ensure_template()`
        有缓存，裁切开销可忽略）—— 不能把整屏按钮直接喂给窄窗匹配，见
        sign_in.py 顶部注释里 SIGN_IN_TITLE 的教训。

        Args:
            image (np.ndarray): Screenshot.

        Returns:
            float: 0~1。
        """
        EVENT_PASS_POPUP.ensure_template()
        template = crop(EVENT_PASS_POPUP.image, EVENT_PASS_TITLE_AREA)
        x1, y1, x2, y2 = EVENT_PASS_TITLE_AREA
        patch = image[y1:y2, x1:x2]
        if patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
            return 0.0
        res = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
        return float(cv2.minMaxLoc(res)[1])

    def event_pass_popup_appear(self):
        """
        签到通行证面板（领奖前后两个状态都算）是否在屏幕上。

        Returns:
            bool: 面板是否在。
        """
        return self._event_pass_score(self.device.image) > EVENT_PASS_SIMILARITY

    def handle_event_pass(self):
        """
        按一下签到通行证面板右上角的 ✕。

        只按一下：面板被关掉后可能先弹「已获得道具」、再把带勾的面板弹回来，
        那两步由调用方的循环接（见模块顶部的说明）。跟 `handle_offer_popup()`
        同款的节流与消失判断。

        Returns:
            bool: If the popup was on screen (and its close key was pressed).
        """
        # "看不到" 就是这一支要问的问题：看不到才轮到别的分支，看得到就关掉它。
        if not self.event_pass_popup_appear():  # alas-lint: allow - the absence is the answer, the caller continues on False
            return False

        if self.EVENT_PASS_BACK.reached_and_reset():
            logger.info('Event pass popup, close it')
            # 这枚 ✕ 实测 adb 一点一个准；tap_asset 走 adb（硬约束 60），
            # 对不对由调用方下一轮的判据回答。
            self.tap_asset(EVENT_PASS_CLOSE)
        return True
