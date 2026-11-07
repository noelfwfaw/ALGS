import numpy as np

from module.logger import logger
from module.starsavior.assets import E_116_1, E_203_1

# 顶部倍速按钮（▶▶）。三档：全灰 = 1x、左白 = 2x、双白 = 3x。
#
# 实测（2026-11-06 20:28，真机 live_j1 / live_sp1 / live_sp3 三张）：
#     1x   左 0.000  右 0.000
#     2x   左 0.444  右 0.008
#     3x   左 0.444  右 0.440
# 阈值 200、判定线 0.20，差得极开，不用调。
#
# ❗**不能用模板区分这三档**：`E_116_1 / E_117_1 / E_118_1` 的 area 是同一块
#   (984,29,1012,47)，三张模板在三种状态下匹配分全是 1.000 ——
#   `TM_CCOEFF_NORMED` 只比结构不比颜色，灰三角和白三角在它眼里一模一样。
#   用户 2026-11-06 20:26：「到旅程了，这里最关键的是能不能点上 3 倍数」。
SPEED_BOX = (984, 29, 1012, 47)

# 左右两个三角的分界（相对 SPEED_BOX 的列号）
SPEED_SPLIT = 14

# 一个像素算不算"三角亮了"。三角是纯白 ~230，灰的是 ~120，
# 取 200 两边都碰不到。
SPEED_TH = 200

# 亮像素占比超过这个数就算"这一半的三角亮了"
SPEED_ON = 0.20

# 倍速按钮「在不在」用**明暗结构**判，不用模板、也不用暗像素占比。
#
# ❗`E_116_1` 模板判存在性已废：真机/离线帧里它匹配分全是 0.000。
# ❗暗像素占比 (`dark>=0.35`) 也曾当存在性用过，但它只认得出 1x：
#   三角点亮成白色之后，亮背景下 3x 的 dark 只有 **0.119**（真机
#   after_leave.png，左右白三角 0.444/0.456，确实是 3x），会被读成
#   「这一屏没有倍速按钮」，ensure_speed 于是空等到超时、日志误报失败。
#
# 现在两道门禁：
#   ① std：倍速按钮是「深灰胶囊 + 灰/白三角」，一定有明暗结构；
#      战斗 / VICTORY / 黑屏那一块是**一片纯暗**，白屏是纯亮。
#      实测 std：对话 1x 38.6 / 2x 84.9 / 3x 91.0 / 亮底 3x 58.9 /
#      战斗 9.4 / VICTORY 5.4 / 自动战斗开 1.6 / 全黑 0.0 / 白屏 0.0。
#      2026-11-07 02:41 在 VICTORY 页把纯暗块读成 1x，press 每 2 秒补点
#      一次 E_116_1、连点 60 多次，quiet 被每次补档 reset，整段退不出去。
#   ② right > 0.80：标题页 / 加载白底那一块整片发亮，右半区几乎全白
#      （标题 0.988、reset 后 1.000），真 3x 最多 0.675。
#   ③ 剧情对话页（2026-11-07 04:13 加的）：右上角是「LOG / AUTO / SKIP」，
#      LOG 的 "L" 压在 SPEED_BOX 右边缘上，背景是亮天空 —— std 41.14 过得了
#      ①、right 0.063 又过得了 ②，兜底被判 1x，补档就点到了 LOG 上。
#      倍速胶囊和 LOG **版式互斥**，用 E_203_1 直接判 0；见 speed_level()。
SPEED_STD = 15
SPEED_RIGHT_MAX = 0.80


class JourneySpeed:
    """旅程里的倍速控制。

    单独一个 mixin，因为 `starsavior2.py` 已经接近 500 行的惯例上限，
    而这块是纯像素判断、和流程无关，拆出来好单独验。
    """

    def speed_level(self):
        """当前倍速档位：1 / 2 / 3；这一屏没有倍速按钮时返回 0。

        ❗**不能用 `E_116_1` 模板判存在性**：真机 2026-11-07 02:3x 离线量过，
        对话页 / 评鉴战 / 标题页 / 大招动画**全部**匹配 0.000（版式换了）。
        结果真的 1x 被读成 0「没有按钮」，`ensure_speed` 12 秒空等不补档，
        1x 下对话不自动推进，整条旅程链断在那儿（用户 02:19 说的
        「变成一倍数不会过对话」根因之一）。
        现在用按钮区的**明暗结构**判存在性（SPEED_STD / SPEED_RIGHT_MAX），
        再用左右半区的白三角占比读档位；详见模块顶部常量注释。
        """
        image = self.device.image
        if image is None:
            return 0
        # ❗剧情对话页没有倍速按钮，但右上角有「LOG / AUTO / SKIP」，而 LOG 的
        #   字形压在本按钮的位置上（实测 x 1003~1038，SPEED_BOX 右边缘 1012
        #   正好切到它的 "L"），背景还是**亮天空**：std 41.14 过得了 SPEED_STD、
        #   right 0.063 又没到白屏门禁，于是落到兜底分支被判成 1x ——
        #   `press(speed=True)` 去点 E_116_1，点击点 (998,38) 就是 LOG 的左缘
        #   （真机 2026-11-07 04:13:16；用户：「正常应该点跳过，但是点了 log」）。
        #   倍速胶囊和 LOG 是**版式互斥**的：有 LOG 的地方就没有倍速按钮，
        #   所以认到 LOG 直接判 0。E_203_1 离线验：真机帧 1.000，其余 0.23~0.30。
        if self.appear(E_203_1, offset=(20, 10)):
            return 0
        crop = image[SPEED_BOX[1]:SPEED_BOX[3], SPEED_BOX[0]:SPEED_BOX[2]]
        lum = np.asarray(crop, dtype=np.int32).mean(axis=2)
        if float(lum.std()) < SPEED_STD:
            return 0
        left = float((lum[:, :SPEED_SPLIT] > SPEED_TH).mean())
        right = float((lum[:, SPEED_SPLIT:] > SPEED_TH).mean())
        if right > SPEED_RIGHT_MAX:
            return 0
        if right > SPEED_ON:
            return 3
        if left > SPEED_ON:
            return 2
        return 1

    def ensure_speed(self, want=3, timeout=25):
        """把倍速点到 `want` 档；已经在那一档就立刻返回。

        三档是循环的（3x 再点回 1x），所以**不能靠"点几次"**，只能每次
        点完读一次档位再决定要不要继续点。用户 2026-11-07 02:19：
        「倍数点了三次导致变成了一倍数不会过对话，只需要点两次就行」。

        三道闸：
          ① 静止确认：点之前先等 SPEED_BOX 静止，再读一次档位。
             淡入淡出那一帧会把 3x 读成 1x，读完立刻点就是那要命的第三下。
          ② 点击验收：只认「换到了预期下一档」且连续两帧成立，
             不认「只要变了就行」—— 变到 0（白屏）或跨档都是过渡帧。
          ③ 达标封按钮：读到 3x 立刻 return，绝不因为抖动再点一下。
        """
        clicks = 0
        for _ in self.loop(timeout=timeout):
            level = self.speed_level()
            if level == want:
                logger.info('旅程：倍速已经是 %dx' % want)
                return True
            if level == 0:
                # 这一屏没有倍速按钮（剧情 / 加载 / 动画 / VICTORY），等它出来
                continue
            if clicks >= 3:
                logger.warning('旅程：倍速点了 3 下还没到 %dx，交给 press 盯着' % want)
                break

            self.wait_until_still(SPEED_BOX, timeout=1, threshold=2.0)
            level = self.speed_level()
            if level in (0, want):
                continue
            expect = level % 3 + 1
            self.click_button(E_116_1, '倍速 %d→%d' % (level, expect))
            clicks += 1

            stable = 0
            for _ in self.loop(timeout=2):
                if self.speed_level() == expect:
                    stable += 1
                    if stable >= 2:
                        break
                else:
                    stable = 0
            else:
                # 点一下没反应不等于失败（硬约束 153）：按 2 秒节流重新读档位，
                # 不立刻补第二下，免得把其实已经生效的点击又点回去。
                logger.warning('旅程：倍速 %d→%d 没验收到，重新读档位' % (level, expect))
                self.wait_until_still(SPEED_BOX, timeout=2, threshold=2.0)

        logger.warning('旅程：没能把倍速点到 %dx' % want)
        return False


# ===== 训练失败 =====
#
# 用户 2026-11-06 20:33：「训练会失败，我没有考虑到，你加上这个状态机吧」。
#
# 失败之后右上角弹三行选项，取的是行内**文字区**（不含右边的消耗数字，
# 那个每轮都可能变）：
TRAIN_OPTION_NAMES = ('休息', '再努力看看', '活力药水')
TRAIN_OPTIONS = (
    (878, 408, 1030, 426),   # 不，今天还是休息比较好   ← 永远可选（四角星）
    (878, 448, 1005, 466),   # 好，我们再努力看看       ← 要 20 货币
    (878, 487, 990, 505),    # 递给她活力药水           ← 要 1 道具
)

# 行内亮度标准差：有字 44~73，空白 7~11。
OPTION_TEXT_STD = 25

# 可点的那一行是**白字**（亮度 >180 的像素占 20.9%），
# 锁着的两行是暗字（0.6% 和 0.0%）—— 真机 20:36 连点两次锁着的选项，
# 画面一动不动，所以必须靠亮度判，不能盲点。
OPTION_TH = 180
OPTION_ENABLED = 0.08


class TrainFail:
    """训练失败那个三选一对话框。

    ❗单独的判据要两条一起用：左上角「训练失败」标题（`E_201_1`）在选项消失
      之后**还会留一会儿**（真机 live_j8 实测还是 1.000），所以光看标题会在
      "已经处理完"的画面上反复触发。真正判"对话框在不在"的，是那三行里
      有没有字（std）。
    """

    def train_fail_options(self):
        """读三行选项：[(能不能点, 中心点或 None), ...]；不是这一屏就返回 []。"""
        image = self.device.image
        if image is None:
            return []
        found = []
        for box in TRAIN_OPTIONS:
            crop = image[box[1]:box[3], box[0]:box[2]]
            lum = np.asarray(crop, dtype=np.int32).mean(axis=2)
            has_text = float(lum.std()) > OPTION_TEXT_STD
            enabled = has_text and float((lum > OPTION_TH).mean()) > OPTION_ENABLED
            center = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2) if has_text else None
            found.append((enabled, center))

        # 三行里至少两行有字才算这一屏 —— 背景偶尔会有一行长得像字
        if sum(1 for _, center in found if center) < 2:
            return []
        return found

    def handle_train_fail(self):
        """点掉训练失败对话框。返回 True 表示点了。

        优先级：再努力看看（花通用货币）> 活力药水（花道具）> 休息。
        前两个锁着的时候只能休息 —— 休息会推进一天，旅程继续。
        """
        options = self.train_fail_options()
        if not options:
            return False

        for index in (1, 2, 0):
            enabled, center = options[index]
            if enabled and center:
                self.tap_at(center[0], center[1], '训练失败：%s' % TRAIN_OPTION_NAMES[index])
                return True

        logger.warning('训练失败：三个选项全是灰的（资源不够），等资源恢复')
        return False
