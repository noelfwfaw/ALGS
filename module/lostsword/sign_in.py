"""处理失落之剑登录后自己打开的签到面板。

每天第一次登录时游戏先播登录奖励，再把活动中心的签到页顶到大厅前面。这个面板
盖住大厅以后 `page_main` 就认不出来了（2026-10-29 实机：整整 63 秒 main=False），
`handle_app_boot()` 会一直等到 300 秒超时，整个任务失败。这一份只管把它关掉。

单独一个文件是因为 `lostsword_ui.py` 已经接近规范的上限（500 行），而这个处理跟
启动流程是一件事、跟页面切换不是 —— 混进来只会让两边都难读。
"""
from module.base.timer import Timer
from module.logger import logger
from module.lostsword.assets import SIGN_IN_TITLE
from module.lostsword.utils import match

# 活动中心（签到页）左上角那块「礼物盒 + 活动」（`SIGN_IN_TITLE`），在它周围
# 放宽二十像素找。实测分数（2026-10-29，模板从 `SIGN_IN_TITLE.png` 按 area 裁）；
# 冷启动的 90 帧逐帧量过，面板在场的是 084~089 那六帧淡入：
#
#   面板在 0.929~0.995（089 是稳定帧 0.995）
#   面板不在：最高 0.884（弹窗刚顶上来那一帧），最低 0.013（黑屏）
#   单张：大厅 0.336、战斗页 0.354、活动卡片页 0.354、登录奖励弹窗 0.478/0.522
#
# 0.90 卡在两边中间：离 0.884 有 0.016，离 0.929 有 0.029。
SIGN_IN_TITLE_SEARCH = (218, 0, 392, 60)
SIGN_IN_TITLE_SIMILARITY = 0.9


class SignIn:
    """
    关掉启动时挡路的签到面板。

    混入 `LostswordUI` 使用，不单独实例化。
    """

    # 返回键的冷却。面板关掉要走一帧动画，这期间再按会按到大厅上，而大厅上
    # 那个键问的是「确认退出」。
    SIGN_IN_BACK = Timer(3)

    def sign_in_panel_appear(self):
        """
        活动中心（签到页）是否在屏幕上。

        判据见 `SIGN_IN_TITLE_SEARCH`。签到页的几个页签共用这一块标题，所以
        调用方在页签之间切换时它也一直为真。

        Returns:
            bool: 面板是否在。
        """
        return match(self.device.image, SIGN_IN_TITLE,
                     SIGN_IN_TITLE_SEARCH) > SIGN_IN_TITLE_SIMILARITY

    def handle_sign_in(self):
        """
        关掉每天第一次登录时游戏自己打开的签到面板。

        游戏先把登录奖励一个个播给你看（「已获得道具」，每个停二十秒左右，不用
        点也会自己换下一个），播完把活动中心的签到页顶到最前面。面板盖在大厅上，
        `page_main` 认不出来，不处理就是等满 300 秒超时。

        面板只是展示：奖励在登录时已经发了 —— 当天面板上打勾的是前三格、
        「Next」压在第 4 格，而登录弹的正是第 3 格那份（100 钻 + 5 个蓝道具）。
        所以这里一个按钮都不按：点格子弹出的是道具说明面板（实测是钻石那条），
        关掉它还得再按一次。

        返回键一下就能关（实测直接回大厅）。它只在面板上发，因为同一个键在标题屏
        会弹「确认退出」，确认了就把账号退掉了。

        Pages:
            in: any
            out: any

        Returns:
            bool: 是否处理了。
        """
        if not self.sign_in_panel_appear():
            return False

        if self.SIGN_IN_BACK.reached_and_reset():
            logger.info('Sign-in panel, close it')
            self.device.adb_shell(['input', 'keyevent', '4'])
        return True
