"""
邮箱领取 (Brown Dust II).

Flow measured on the real device (2026-10-28, screenshots in
`screenshots/browndust/`):

    page_main  --右上角那个信封图标-->  page_mail（停在「普通邮箱」）
    page_mail  --右下「全部领取」-->  REWARD 结算页（「获得N种」+ 道具一排）
                                      --点底部空白--> 回到 page_mail
    page_mail  领完：按钮变灰、计数 0/100、中间写「尚未收到邮件。」
    page_main  --左上角箭头-->

Three things here are not what they look like, and all three were measured
rather than guessed:

1. **「全部领取」还亮不亮，是唯一的"还有没有邮件"信号**，而模板匹配回答不了：
   领完之后按钮的**形状一模一样**，`MAIL_CLAIM` 依然打 0.952，只是被画成了
   灰的。亮度才分得开 —— 可领时 `luma>200` 有 5137 个像素，领完是 **0**。
   （同 page.py 里那条"亮暗两态的按钮不可靠"，只是这次反过来用：不拿它判
   页面在不在，拿它判这个功能还能不能用。）

2. **REWARD 结算页的横条跟快速狩猎是同一个**，可以直接复用 `HUNT_REWARD`
   （邮箱结算页 0.992~0.996，邮箱列表页 0.509，其它页 0.475），但**底部提示
   的位置不一样**：快速狩猎那张在 y 604 附近，这一张在 y 655 附近。所以快速
   狩猎的点击点 `(610,580,670,620)` 在这里正好落在蓝色 V 形条纹上 —— 那片点
   不动（快速狩猎时连点 10 次无反应）。这一页的落点取更下面的空白带 `(620,700)`。

3. **`page_mail` 的检查点在结算页上也是 0.945**，因为结算页是半透明覆盖，底下的
   按钮还看得见。所以"已到邮箱页"必须再加一条"没有结算页盖着"，见
   `BrowndustUI.ui_reward_clean()` —— 跟 `page_hunt` 完全同一个理由。

页签暂时只做「普通邮箱」：商品邮箱是付费/商品邮件，自动领有风险；记录页没有
可领的东西。默认页签实测是「普通邮箱」，但游戏会记住上次看的那一页，所以还是
先用白字判据确认一次（选中 375 个 `luma>200` 的像素，未选中 0）。
"""
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.browndust.assets import HUNT_REWARD, MAIL_CLAIM
from module.browndust.browndust_ui import BrowndustUI, page_mail
from module.logger import logger

# 左侧三个页签。`label` 只数白像素（选中态），`point` 是文字的点击点。
MAIL_TAB_LABELS = {
    'normal': (190, 105, 300, 132),
    'shop': (190, 160, 300, 188),
    'record': (190, 218, 300, 245),
}
MAIL_TAB_POINTS = {
    'normal': (235, 119),
    'shop': (235, 174),
    'record': (235, 231),
}
MAIL_TAB_NAMES = {
    'normal': '普通邮箱',
    'shop': '商品邮箱',
    'record': '记录',
}

# 选中态判据：白像素数。实测选中 375，未选中 0。100 两边都留着 3 倍以上余量。
MAIL_LABEL_LUMA = 200
MAIL_LABEL_PIXELS = 100

# 「全部领取」可不可点。实测可领 5137 个 luma>200 的像素，领完 0。
# 模板分数在这一对状态里是 1.000 和 0.952，完全分不开，只能用亮度。
MAIL_CLAIM_LUMA = 200
MAIL_CLAIM_PIXELS = 100

# 结算页的点击点：所有道具和「点击画面即可返回。」下面那条空白带。
# 见模块 docstring 第 2 条 —— 快速狩猎的落点在这一页是 V 形条纹，点不动。
MAIL_REWARD_TAP = Button(area=(600, 680, 640, 720), color=(0, 0, 0),  # alas-lint: allow - the reward screen says 点击画面即可返回, there is no button to match
                         button=(620, 700, 620, 700), name='MAIL_REWARD_TAP')

# 点掉结算页之后再等回邮箱的时限。结算页一消失页面就是可见的，不需要长等。
MAIL_RESULT_TIMEOUT = 30
# 点「全部领取」到结算页出现。实测一下就出来，给 10 秒是防网络卡。
MAIL_REWARD_TIMEOUT = 10
# 结算页是"点一下才走"，节流一下，免得被框架判成连点。
MAIL_TAP_INTERVAL = 2
# 领完一次之后再检查还有没有。正常一次就领空了，多给两次是防"结算页关掉时
# 又有新邮件落地"（成就奖励就是边领边发的）。
MAIL_CLAIM_TRIES = 3
# 切页签之后等选中态画出来。页签是纯本地的，给它一屏动画的时间。
MAIL_TAB_TIMEOUT = 10


class BrowndustMail(BrowndustUI):
    """
    Claim everything in 普通邮箱.

    Pages:
        in: page_main
        out: page_main
    """

    def mail_label_selected(self, area):
        """
        Whether a tab label is drawn in the selected (white) colour.

        Args:
            area (tuple): Label area.

        Returns:
            bool: True if selected.
        """
        return self.ui_bright_count(area, MAIL_LABEL_LUMA) >= MAIL_LABEL_PIXELS

    def mail_claim_available(self):
        """
        Whether 「全部领取」 is drawn in its enabled (bright) state.

        This is the only "is there any mail left" signal the page gives. The
        button keeps its shape and its template score when the box is empty,
        it just goes grey, so the question has to be asked in luma.

        Returns:
            bool: True if there is mail to claim.
        """
        return self.ui_bright_count(MAIL_CLAIM.area, MAIL_CLAIM_LUMA) >= MAIL_CLAIM_PIXELS

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        self.ui_goto(page_mail)
        if not self.mail_open_tab('normal'):
            logger.warning('The 普通邮箱 tab did not open, claim whatever is on screen')
        claimed = self.mail_claim_all()
        logger.info(f'[Mail claimed] {claimed}')
        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def mail_open_tab(self, tab):
        """
        Switch the mailbox to one of the three tabs.

        Pages:
            in: page_mail
            out: page_mail

        Args:
            tab (str): normal / shop / record.

        Returns:
            bool: If the tab is selected.
        """
        label = MAIL_TAB_LABELS[tab]
        if self.mail_label_selected(label):
            logger.info(f'Already on the {MAIL_TAB_NAMES[tab]} tab')
            return True

        logger.info(f'Open the {MAIL_TAB_NAMES[tab]} tab')
        press = Timer(2)
        for _ in self.loop(timeout=MAIL_TAB_TIMEOUT):
            if self.mail_label_selected(label):
                # 切页签时左侧整列都在重画，一帧命中不算数（硬约束 89）。
                self.wait_until_still(label, timeout=2)
                if self.mail_label_selected(label):
                    return True
            if press.reached():
                press.reset()
                self.device.click_minitouch(MAIL_TAB_POINTS[tab][0], MAIL_TAB_POINTS[tab][1])  # alas-lint: allow - verified by the label's colour on the next round

        logger.warning(f'The {MAIL_TAB_NAMES[tab]} tab did not open')
        return False

    def mail_claim_all(self):
        """
        Press 「全部领取」 until the box is empty.

        Pages:
            in: page_mail
            out: page_mail

        Returns:
            int: How many batches went through.
        """
        claimed = 0
        pressed = False
        for i in range(MAIL_CLAIM_TRIES):
            if not self.mail_claim_available():
                break
            pressed = True
            logger.info(f'Claim all the mail ({i + 1})')
            self.device.click(MAIL_CLAIM)  # alas-lint: allow - the button being bright is checked right above, and the reward screen below is the proof it took
            # 先记上再判结果：按钮已经按下去了，这一批的附件就已经进包，
            # 哪怕结算页没点掉，也**不能**当成"没领到"报出去。
            claimed += 1
            if not self.mail_close_reward():
                logger.warning('The claim did not come back to the mailbox')
                break

        # 「一次都没点下去」和「点了但没回来」是两件事，不能共用一个 "no mail"。
        # 后者上面已经报过 warning 了，这里再说"没有邮件"会把人带偏。
        if not claimed and not pressed:
            logger.info('No mail to claim')
        return claimed

    def mail_close_reward(self):
        """
        Sit through the REWARD screen and come back to the mailbox.

        The order is the same trick as `hunt_start()`: the mailbox check point
        (`MAIL_CLAIM`) scores 0.945 **through** the reward screen, because the
        screen is a translucent overlay. So the reward banner is asked about
        first and the loop only accepts the mailbox once the banner is gone.

        Pages:
            in: page_mail (reward screen opening)
            out: page_mail

        Returns:
            bool: If the mailbox is back.
        """
        if not self.wait_until_appear(HUNT_REWARD, offset=(20, 20), timeout=MAIL_REWARD_TIMEOUT, settle=2):
            if self.ui_page_appear(page_mail, offset=(20, 20)):
                # 只有金币之类的纯货币邮件可能不弹结算页，直接回到列表。
                logger.info('No reward screen, already back to the mailbox')
                return True
            logger.warning('Neither the reward screen nor the mailbox came back')
            return False

        tap = Timer(MAIL_TAP_INTERVAL).start()
        for _ in self.loop(timeout=MAIL_RESULT_TIMEOUT):
            if self.appear(HUNT_REWARD, offset=(20, 20)):
                if tap.reached():
                    tap.reset()
                    logger.info('Reward screen, tap to go back')
                    self.device.click(MAIL_REWARD_TAP)  # alas-lint: allow - the reward screen has no button, it says 点击画面即可返回
                continue
            if self.ui_page_appear(page_mail, offset=(20, 20)):
                return True

        logger.warning('The reward screen did not go away')
        return False
