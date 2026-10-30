"""把游戏唤起并走到主界面。

这是这个游戏的第一个任务，也是后面所有任务的前提：调度器切到本游戏时先跑它，
把客户端从「冷启动 / 标题屏 / 闲置立绘」任意一屏带到主界面，后面的任务才有一个
共同的起点。它自己不做任何游戏内操作 —— 不领奖、不进任何模式。

「主界面」的判据在 `module/chaoszero/page.py`，启动流程在
`module/chaoszero/chaoszero_ui.py` 的 `handle_app_boot()`。
"""

from module.chaoszero.chaoszero_ui import ChaoszeroUI, page_main
from module.logger import logger


class ChaoszeroMain(ChaoszeroUI):
    def run(self):
        """
        Pages:
            in: any
            out: page_main
        """
        logger.hr('Enter main page', level=1)

        # 游戏可能停在任何一屏：标题屏（调度器只把进程拉到前台，没走
        # `app_start()`，比如上一个任务是本游戏的、`game_in_foreground` 还是
        # True）、闲置立绘（放着二十秒不动就这样）、或者已经在主界面。
        # 不在认识的那几页上就把启动流程再走一遍 —— 这条流程本身是幂等的：
        # 已经在主界面时第一帧就返回。
        if not self.ui_any_page_appear():
            logger.info('Game is not on a page this task knows, walk the boot screens')
            self.handle_app_boot()
        self.ui_ensure(page_main)

        self.config.task_delay(server_update=True)
