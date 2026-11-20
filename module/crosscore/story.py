"""独立工具：交错战线自动跳过剧情。

WebUI「工具」页单独启动（`task.yaml` 里 `page: 'tool'`、没有 `Scheduler` 组）。
脚本从当前画面直接进入状态循环，不接管启动也不走回主界面，只在看到：

1. 「跳过剧情」确认弹窗（`STORY_CONFIRM_TITLE`）→ 点黄色「确认」(`STORY_CONFIRM`)；
2. 剧情右上角「跳过」（`STORY_SKIP`）→ 点「跳过」，等下一帧状态机接手弹窗。

两步之间清除点击计数并喂看门狗，防止连续跳过超过 6 段触发双键交替保护
（`GameTooManyClickError`），也防止手动打关期间长时间无剧情触发超时重启。
在「工具」页点 Stop 即可退出。
"""

from module.crosscore.assets import (STORY_CONFIRM, STORY_CONFIRM_TITLE,
                                     STORY_SKIP)
from module.crosscore.crosscore_ui import CrosscoreUI
from module.logger import logger

# 剧情跳过与确认模板来自 1024x576 压缩图缩放到 720p，且「跳过」底板为半透明，
# 阈值取 0.80 留足余量；全库 51 张非剧情截图上最高干扰分分别为 0.516 / 0.585 / 0.722。
STORY_MATCH_SIMILARITY = 0.80
# 同一按钮的点击节流（秒），避免淡出过渡帧连点。
STORY_CLICK_INTERVAL = 1.5


class CrosscoreStory(CrosscoreUI):
    """
    Loop state machine that clicks top-right 「跳过」 and dialog 「确认」.
    """

    def run(self):
        """
        Keep watching the current screen and skip story dialogues until stopped.
        """
        logger.hr('Crosscore story skip', level=1)
        if not self.device.app_is_running():
            logger.info('Game is not in the foreground, bring it to front')
            self.device.app_start()

        for _ in self.loop(skip_first=False):
            if self.config.stop_event is not None and self.config.stop_event.is_set():
                logger.info('Stop requested, exit story skip tool')
                break

            # 剧情工具可能挂在手动推图或战斗间隙，长时间无剧情点击属于正常等待。
            self.device.stuck_record_clear()

            # 1. 确认弹窗优先：弹窗盖在剧情上面，先确认再回到剧情页检测。
            if self.appear(STORY_CONFIRM_TITLE, offset=30, similarity=STORY_MATCH_SIMILARITY):
                if self.appear_then_click(STORY_CONFIRM, offset=30,
                                          interval=STORY_CLICK_INTERVAL,
                                          similarity=STORY_MATCH_SIMILARITY):
                    logger.info('Confirm story skip')
                    # 一轮 跳过 -> 确认 完成，清空点击历史以免连跳 6 段触发双键防卡死。
                    self.device.click_record_clear()
                continue

            # 2. 剧情画面：点右上角「跳过」。
            if self.appear_then_click(STORY_SKIP, offset=30,
                                      interval=STORY_CLICK_INTERVAL,
                                      similarity=STORY_MATCH_SIMILARITY):
                logger.info('Skip story')
                continue
