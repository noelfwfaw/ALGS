"""把游戏唤起并走到主界面。

这是这个游戏的第一个任务，也是后面所有任务的前提：调度器切到本游戏时先跑它，
把客户端从「冷启动 / 片头 / 标题屏 / 二级页」任意一屏带到主界面，后面的任务才有
一个共同的起点。它自己不做任何游戏内操作 —— 不领奖、不进任何模式。

「主界面」的判据在 `module/crosscore/page.py`，启动流程在
`module/crosscore/crosscore_ui.py` 的 `handle_app_boot()`。
"""

from module.crosscore.crosscore_ui import CrosscoreUI, page_main
from module.logger import logger


class CrosscoreMain(CrosscoreUI):
    def run(self):
        """
        Pages:
            in: any
            out: page_main
        """
        logger.hr('Enter main page', level=1)

        # 游戏可能停在任何一屏：进程没起（手动清过后台）、停在标题屏、停在基地
        # 建设或签到页、或者已经在大厅。`app_is_running()` 比的是**前台**包名，
        # 游戏退到后台时它回答 False，所以这句同时覆盖「没起」和「在后台」。
        if not self.device.app_is_running():
            logger.info('Game is not in the foreground, launch it')
            self.app_start()

        # 大厅之外的那几屏（标题屏、二级页、片头）都交给启动流程；它本身是幂等
        # 的：已经在大厅时第一帧就返回。
        if not self.ui_any_page_appear():
            logger.info('Game is not on a page this task knows, walk the boot screens')
            self.handle_app_boot()

        self.ui_ensure(page_main)

        self.config.task_delay(server_update=True)
