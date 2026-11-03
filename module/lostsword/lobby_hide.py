"""把被游戏自己藏掉的大厅 UI 拍醒。

V1.610.1 起大厅会进入「影院模式」：闲置约三分钟（冷启动登录完也算闲置），
UI 整层消失，只剩会动的酒馆立绘。`page_main` 一个图标都不在，所有任务当场
"Game page unknown"；唯一的线索是**点一下画面，右上角浮出一枚眼睛开关**，
点它 UI 才回来（2026-11-04 实机，整个任务队列就这么全灭过两轮）。

拍醒的舞步：点画面空白处 → 眼睛浮出（(1200, 39) 附近）→ 点眼睛 → UI 回来。

判据两道，缺一不可：
  - 左下角酒桶区（`LOBBY_HIDDEN_AREA`）：影院模式的机位，帧间完全静止
    （4 帧实拍 std=0.0，判据 1.000）；正常大厅是拉远的另一个机位，0.076；
    94 张历史整屏最高 0.611。
  - `page_main` 不在场：正常大厅虽然机位不同判据过不了，但保底再拦一道，
    正常状态下这一支永远闭嘴。

跟 sign_in.py / offer.py 一样单独放一支：混入 `LostswordUI` 使用，
`handle_app_boot()` 和 `ui_additional()` 各挂一次。
"""
import cv2

from module.base.timer import Timer
from module.base.utils import crop
from module.logger import logger
from module.lostsword.assets import LOBBY_EYE, LOBBY_HIDDEN, LOBBY_REVEAL
from module.lostsword.page import page_main
from module.lostsword.utils import match

# 影院模式的静态机位：左下角酒桶+石墙。模板从整屏 PNG 按 area 现裁，见
# sign_in.py 顶部注释（整屏按钮不能直接喂窄窗匹配）。
# 实测（2026-11-04，模板 140x180，精确匹配）：
#
#   影院模式 4 帧 1.000（帧间动画零噪声）
#   正常大厅（拉远机位）0.076
#   94 张历史整屏最高 0.611
#
LOBBY_HIDDEN_AREA = (0, 300, 140, 480)
LOBBY_HIDDEN_SIMILARITY = 0.85

# 眼睛浮出的位置（点完画面后 3 秒内在场）。用模板认它，认不出就不按 ——
# 空白处连点两下是这一支最大的动作，第二步必须看见再按。
LOBBY_EYE_SEARCH = (1162, 4, 1240, 74)

# 拍醒用的落点：吧台前的空地板，避开三位角色的可交互热区。素材就是
# 那块地板的裁切，button 即落点。


class LobbyHide:
    """
    恢复被影院模式藏掉的大厅 UI。

    混入 `LostswordUI` 使用，不单独实例化。
    """

    # 舞步的冷却。UI 藏掉是闲置行为，任务跑起来之后基本不会再触发；
    # 冷却只防 ui_additional 每帧都来一遍。
    LOBBY_REVEAL = Timer(5)

    def lobby_ui_hidden(self):
        """
        大厅是否处于影院模式（UI 整层被藏掉）。

        Returns:
            bool: 是否处于影院模式。
        """
        if self.ui_page_appear(page_main):
            return False
        # 模板从整屏 PNG 按 `LOBBY_HIDDEN_AREA` 现裁 —— 整屏按钮直接喂
        # `match()` 会拿 720p 模板在 180x140 的窗里找，永远 0.0（sign_in.py
        # 顶部注释里 SIGN_IN_TITLE 的教训）。
        LOBBY_HIDDEN.ensure_template()
        template = crop(LOBBY_HIDDEN.image, LOBBY_HIDDEN_AREA)
        x1, y1, x2, y2 = LOBBY_HIDDEN_AREA
        patch = self.device.image[y1:y2, x1:x2]
        if patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
            return False
        res = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
        return float(cv2.minMaxLoc(res)[1]) > LOBBY_HIDDEN_SIMILARITY

    def handle_lobby_hide(self):
        """
        拍醒影院模式：点画面 → 眼睛浮出 → 点眼睛。

        Args:
            (无)

        Returns:
            bool: If the lobby was in cinema mode (and the dance ran).
        """
        if not self.lobby_ui_hidden():  # alas-lint: allow - the absence is the answer, the caller continues on False
            return False

        if self.LOBBY_REVEAL.reached_and_reset():
            logger.info('Lobby UI is hidden (cinema mode), reveal it')
            self.tap_asset(LOBBY_REVEAL)

            # 眼睛浮出需要一拍，最多等 3 秒；看见了就按，没看见说明 UI
            # 已经自己回来了（第一下点到别的东西上），不瞎按。
            timeout = Timer(3).start()
            for _ in self.loop():
                if match(self.device.image, LOBBY_EYE,
                         LOBBY_EYE_SEARCH) > 0.85:
                    self.tap_asset(LOBBY_EYE)
                    break
                if timeout.reached():
                    break
        return True
