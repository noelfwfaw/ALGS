"""从救援者列表读一个号：一行一行点过去，SSR 才展开。

用户 2026-11-06 18:45 定的流程（照做，不要再自作主张）：

    点一行 → 看左上角那块稀有度
        不是 SSR  → 整个扫描到此为止（列表是 SSR 在前，后面没有了）
        是 SSR    → 记团名 + 人名 → 查看详情 → 突破极限 → 读「获得多少个」→ 退回列表

和上一版的区别：
- **不看头像的红点、也不看头像角的稀有度**，稀有度只看用户框的左上角那一块；
- 名字和团名在**列表页**读（点中一行左上角就有），不用进详情页才读；
- 不再预先筛 SSR，而是从上往下点，遇到第一个非 SSR 就停 —— 这样不用维护
  「哪个稀有度算目标」，也不会因为稀有度判错而漏行。

和刷初始主流程的区别：这一段**有状态**（要记住点到第几行），所以不能用
`press()` 那种"每帧重扫"的写法，只能一行一行遍历；但每一步仍然是
「等判据成立」而不是「等固定秒数」。

半成品那一版一个角色要 8 秒，大半是睡掉的：`sleep(0.6)` 等转场、
`sleep(0.45)` 等数字渲染、`tap(x, y, 1.2)` 点完闭眼等。这里全换成判据。

坐标全部是 1280x720（真机实测）。纯算法在 `rescuer.py` 和 `ocr.py`，
都能离线跑（`dev_tools/probe_starsavior_rescuer.py` / `probe_starsavior_ocr.py`）。
"""
from module.base.button import Button
from module.base.timer import Timer
from module.logger import logger
from module.starsavior import rescuer
from module.starsavior.assets import (E_193_1, E_194_1, E_194_4, E_195_1, E_196_2,
                                      E_204_1, E_204_2)
from module.starsavior.ocr import (CONSENSUS_AREA, LABEL_AREA, read_consensus,
                                   read_label)

# 点行的位置：落在行的**名字 / 等级那一列**（x≈1160）。
# 不能点头像 (1208, cy)：那是"进详情"，选不中；
# 也不能点 1120：那里落在行左边的空隙里，点了等于没点（半成品实测每一行都选不中）。
ROW_TAP_X = 1160

# 选中态判定：圆心 y 差在这个范围内就算"还是同一行"，避免行高 ±2px 抖动误判。
ROW_Y_TOL = 22

# 「突破极限」入口的**图标中心**。
# ❗`E_195_1` 的 area 是 (44, 615, 98, 695)，里面同时包着上面的图标
#   (55, 616, 97, 650) 和下面的文字「突破极限」(40, 668, 116, 696)；
#   `device.click()` 在整个 area 里**随机取点**，落到文字上就毫无反应
#   （用户 2026-11-06 19:18：「突破极限不能点突破极限这四个字，这不是入口，
#   点了没反应的，要点图标」）。所以点击目标写死图标中心，只拿 area 当匹配判据。
#   图标中心 (76, 633) 和半成品 log/ss_explore/verify.py 的 BREAK_ENTRY 一致。
# 突破极限入口 = **`E_195_1` 的 area 中心**，别写死坐标（用户 2026-11-06 22:19：
# 「怎么没有点到突破极限的图标上，你别改坐标」）。
#
# `E_195_1`(44,615,98,695) 框的就是左下角那颗星星 + 「突破极限」四个字，
# 中心 (71,655) 真机点通（22:20 打开的面板和用户给的截图一致）。
# 之前写死的 (76,633) 偏上 22 像素，落到图标上边缘外，点开的是技能详情 ——
# 那里也有个 `N/1`（技能升级材料），被当成重复数读，所以三个 SSR 全记成 0。
BREAK_ICON = ((E_195_1.area[0] + E_195_1.area[2]) // 2,
              (E_195_1.area[1] + E_195_1.area[3]) // 2)



class RescuerScan:
    """读救援者列表。要配合 UI 基类用：`class X(RescuerScan, XUI)`。"""

    def tap_at(self, x, y, note):
        """点一个坐标，并记一笔日志。

        `device.click()` 只收 Button（它要在 `button` 矩形里随机取点），
        所以这里临时包一个 4x4 的按钮出来。这个 Button 没有 file，
        永远不会进 `appear()` 家族，只用来点击 —— 不违反「纯坐标按钮不能当判据」。
        """
        self.click_count = getattr(self, 'click_count', 0) + 1
        logger.info('第 %d 次点击：%s @ (%d, %d)' % (self.click_count, note, x, y))
        self.device.click(Button(  # alas-lint: allow - the caller only reaches here after `list_rows()` returned rows AND `rescuer.selected()` said this row is not the current one
            area=(x - 2, y - 2, x + 2, y + 2),
            color=(0, 0, 0),
            button=(x - 2, y - 2, x + 2, y + 2),
            name=note,
        ))

    def click_button(self, button, note):
        """点 Button 的 **area 中心**，并记一笔日志。

        ❗用户 2026-11-07 00:46：「所有的点击都点中间」。
        原来 `device.click(button)` 在 `button.button` 矩形里随机取点，而
        `Button.match` 的 offset 还会改写那个矩形（硬约束 136）—— 真机
        00:44 点 `E_171_1`（area (1211,25,1234,50)，中心 (1222,37)）实际
        落在 **(1220,20)**，菜单没打开，验号/重置整轮断在这里。
        和 `press()`、`tap_at()` 一样统一钉到 area 中心：框多歪，落点都在中间。

        用 `.area` 不用 `.button`：后者会被匹配偏移改写。
        """
        self.click_count = getattr(self, 'click_count', 0) + 1
        cx = (button.area[0] + button.area[2]) // 2
        cy = (button.area[1] + button.area[3]) // 2
        logger.info('第 %d 次点击：%s（%s）@ (%d, %d)'
                    % (self.click_count, button.name, note, cx, cy))
        self.device.click(Button(  # alas-lint: allow - 调用方都已先做过判据；这里只负责"按下去"，且没有 file、不进 appear 家族
            area=(cx - 2, cy - 2, cx + 2, cy + 2),
            color=(0, 0, 0),
            button=(cx - 2, cy - 2, cx + 2, cy + 2),
            name=button.name,
        ))

    def click_once(self, button, note, offset=(20, 20), interval=1.5):
        """看到一个按钮就点它，但**同一次点击之后 `interval` 秒内不再点**。

        ❗不要用 `appear_then_click(interval=2)` —— 那个 `interval` 是假的。
        `appear()` 里新建的 `Timer(2)` 从来没 `.start()`，而 `Timer.reached()`
        在 `_start == 0` 时直接返回 True（源码注释："not started, return True
        for fast first try"），于是每帧都成立。一帧 0.3 秒，等于**每秒点三次**：

            - 点「查看详情」进到详情页后，还在原地 (1129, 670) 继续连点，把详情页点乱；
            - 点「✕」关突破极限面板时连点，紧跟着点「左上返回」会被关闭动画吃掉
              （用户 2026-11-06 18:56 撞到的就是这个）。

        用户 2026-11-06 18:56：「点右上角退出到点左上角退出太快了，导致点左上角没有点到。」

        Returns:
            bool: 这一帧点了没有。
        """
        if not self.appear(button, offset=offset):  # alas-lint: allow - "it is not there" means "do not click", which is the safe direction, and the next frame re-checks
            return False
        timers = getattr(self, '_click_timers', None)
        if timers is None:
            timers = self._click_timers = {}
        timer = timers.get(button.name)
        if timer is not None and not timer.reached():
            # 上一次点完，间隔还没到
            return False
        # ❗第一次必须**直接点**：Timer 刚 start() 时 reached() 一定是 False，
        #   如果像上面那样一起判，那"只调用一次"的地方（关面板）就永远不点 ——
        #   真机实测卡在突破极限页出不来，就是这一行。
        if timer is None:
            timers[button.name] = Timer(interval).start()
        else:
            timer.reset()
        self.click_button(button, note)
        return True

    def list_rows(self):
        """当前这一帧的列表行。空列表 = 不在列表页。"""
        if self.device.image is None:
            return []
        return rescuer.rows(self.device.image)

    def wait_for_list(self, timeout=20):
        """等救援者列表出现，返回行列表。"""
        for _ in self.loop(timeout=timeout):
            rows = self.list_rows()
            if rows:
                return rows
        logger.warning('验号：%s 秒内没看到救援者列表' % timeout)
        return []

    def is_ssr(self):
        """左上角摘要里那一块稀有度是不是 SSR。

        用的是用户框的 spec page 194 稀有度模板。实测（四张真机图）

            SSR 行  匹配分 1.000
            SR 行   匹配分 0.000

        边界宽到不用调阈值。而且它用 `TM_CCOEFF_NORMED`（归一化互相关），
        整个画面被转场遮罩压暗时照样是 1.000 —— `detail.png` 那张暗图就是。

        只看这块，不看头像角标：头像角标是画在头像圆下沿的，判它要自己算颜色，
        而且选中的那一行头像会缩放重绘，角标位置也跟着变。
        """
        return self.appear(E_194_1, offset=(4, 4))

    def select_row(self, cy, timeout=8):
        """把 y=cy 那一行选成"当前行"。

        判据是**圆心左移**：未选中行的圆心 x≈1208，被选中的那一行会缩放重绘、
        跑到 1172~1176。点空了圆心不会动，所以不看这个就会连着读两遍同一个角色。

        如果这一行本来就是选中的，直接返回 —— 别因为"点了没变化"反复点。
        """
        # ❗Timer 故意**不 start**：`Timer.reached()` 在没启动时返回 True
        # （源码注释 "not started, return True for fast first try"），
        # 正好让第一次直接点下去，之后 `reset()` 才开始算 1.2 秒的间隔。
        # 如果写成 `Timer(1.2).start()`，第一次要白等 1.2 秒才点。
        tapping = Timer(1.2)
        for _ in self.loop(timeout=timeout):
            # 「NOA指南」帮助弹窗会盖住列表，点多久都选不中（2026-11-14 19:18）。
            self.dismiss_noa_guide()
            rows = self.list_rows()
            if not rows:
                # 已经掉进详情页了（点到头像会这样），先退回列表再来
                self.click_once(E_193_1, '退出详情页', offset=(10, 10))
                continue
            sel = rescuer.selected(rows)
            if sel and abs(sel[0] - cy) < ROW_Y_TOL:
                return True
            if tapping.reached():
                self.tap_at(ROW_TAP_X, cy, '选中 y=%d' % cy)
                tapping.reset()
        logger.warning('验号：y=%d 选不中' % cy)
        return False

    def read_label_ready(self, timeout=4):
        """读左上角的 (人名, 团名)，等这块画面更新完再读。

        ❗点完一行，**列表高亮是立刻的，左上角摘要要淡入 0.3~0.5 秒**。
        不等这一下就会读到**上一行**的名字 —— 2026-11-06 18:56 真机实测：
        第 2 行（亚瑟菈）被读成了第 1 行的「丝卡蕾@小暴君」。
        而"读完再读一次，两次一样"也解决不了：旧内容同样稳定。
        所以判据只能是"这块画面不动了"。

        ❗名字必须连剧团一起记：**同名不同团是两个不一样的角色**
        （亚瑟菈@星光华尔兹 和 亚瑟菈@航行者救援团 完全两码事），
        只按名字去重会把两个号的两个角色并成一个。
        """
        self.wait_until_still(LABEL_AREA, timeout=timeout)
        name, troupe = read_label(self.device.image)
        if name:
            return name, troupe
        # 还是空 = 抓到的那一帧太暗（转场遮罩把白字压成灰字），再等一次
        self.wait_until_still(LABEL_AREA, timeout=2)
        return read_label(self.device.image)

    def open_detail(self, timeout=10):
        """点「查看详情」，等详情页左下角的「突破极限」入口出现。

        ❗用 `E_194_4`（用户在第 194 页框的那块**文字**），不要用 `E_187_1`：
        187 是「救援者引导3」那一页的按钮，**外面套着一圈引导白框**，
        而正常列表页的按钮没有白框 —— 真机实测 `E_187_1` 在当前画面上只有
        0.000，一个都点不出去。`E_194_4` 在三张真机帧上都是 1.000。
        """
        for _ in self.loop(timeout=timeout):
            if self.appear(E_195_1, offset=(20, 20)):
                # ❗入口一露出来就往下点会点空：详情页是**滑入**的，这半秒里左下角
                #   还是列表页的**技能图标**（还没淡出），点下去会打开技能详情。
                #   用户 2026-11-06 19:19：「进入详情页不能点太快，不然可能没进去就点了，
                #   导致点到左下角未淡出的技能，这是游戏自身的问题，但是得我们解决。」
                #
                #   判据用「列表页的『查看详情』彻底消失」= 详情页完全盖住了 ——
                #   比等整屏静止可靠（详情页有常驻动画，整屏永远不静）。
                self.wait_until_disappear(E_194_4, offset=(10, 10), timeout=3, settle=3)
                return True
            self.click_once(E_194_4, '查看详情', offset=(10, 10), interval=1)
        logger.warning('验号：点不进角色详情')
        return False

    def read_dups(self, timeout=15):
        """开突破极限面板，读「所需材料 N/1」的 N，读完关掉。

        N = 这个角色重复获得的次数，**不是**详情页右上角那个「共鸣」——
        实测丝卡蕾详情页写 0，突破极限页却是 2/1，两个数不一样。

        ❗入口要**重试**着点：详情页淡入要 0.5 秒，这期间的点击会被动画吞掉
        （实测前两个角色一次点空，面板压根没开）。但也不能连点 ——
        `click_once` 保证同一个按钮两秒内只点一次。

        ❗点击目标是**图标**（`BREAK_ICON`），不是 `E_195_1` 整块 —— 那块里包着
        下面的文字「突破极限」，随机落到文字上点了没反应，这就是之前"要点两三次
        才开一次面板"的原因。用图标中心之后一次就中。

        还要**重试**：详情页淡入那 0.5 秒里点击会被动画吞掉，所以入口还在就再点。
        """
        opened = False
        # Timer 不 start：第一次直接点，之后 reset 才开始算 2 秒间隔。
        retry = Timer(2)
        for _ in self.loop(timeout=timeout):
            # 「NOA指南」帮助弹窗会盖住整屏（2026-11-14 19:18 面板被判"没打开"）。
            self.dismiss_noa_guide()
            if self.appear(E_196_2, offset=(10, 10)):
                opened = True
                break
            # 万一那一次点击把页面退回了列表，就不要再干等下去 ——
            # 真机遇到过一次：点了入口没开面板，15 秒后超时，白等一整段。
            # ❗判"在列表"必须连「查看详情」按钮一起看：详情页是滑入的，
            #   滑到一半时右侧列表还没退场，光靠 `list_rows()` 会误判
            #   （实测点完详情 0.3 秒就报"已退回列表"，把 SSR 漏掉）。
            if self.list_rows() and self.appear(E_194_4, offset=(10, 10)):
                logger.warning('验号：已经退回列表，跳过这个角色的重复数')
                return None
            if self.appear(E_195_1, offset=(20, 20)) and retry.reached():
                self.tap_at(BREAK_ICON[0], BREAK_ICON[1], '突破极限图标')
                retry.reset()
        if not opened:
            # 留证据：到底是入口没认出来、面板没开，还是已经不在详情页
            image = self.device.image
            logger.warning('验号：突破极限面板没打开（入口 %.2f 面板 %.2f 列表 %d 行）'
                           % (E_195_1.match(image, offset=(20, 20)),
                              E_196_2.match(image, offset=(10, 10)),
                              len(self.list_rows())))
            return None

        # 数字和星星都是弹入动画，面板刚出来那一帧读到的是 0 或空串。
        # 等那一小块不再变化再读 —— 比 sleep 稳（不用猜多久），也更快。
        self.wait_until_still(CONSENSUS_AREA, timeout=3)
        value = read_consensus(self.device.image)
        if value is None:
            # 数字还在飘的时候第二次通常就有了，再等一次，别直接判失败。
            self.wait_until_still(CONSENSUS_AREA, timeout=2)
            value = read_consensus(self.device.image)

        # ❗这里**不再重试 0**。`read_consensus` 内部已经走过两步：
        #   原图读一次、不行再放大 3 倍读一次，两次都解析不出数字才返回 None。
        #   能返回 0 就说明**确实读到了东西、而且分子位是空的**（红字），
        #   那是确定答案。原来这里又循环 2 次"取最大值"，纯属白跑 OCR
        #   （用户 2026-11-06 22:27：「之前还挺快的，现在…慢了不少」）。

        # 关闭面板。**这里必须慢一点**：
        # 点 ✕ 之后面板还有 0.3~0.5 秒的收起动画，这期间点「左上返回」会被动画吃掉
        # （用户 2026-11-06 18:56：「突破界面点右上角退出到点左上角退出太快了，
        #   导致点左上角没有点到」）。所以：
        #   ① ✕ 只点一次 —— click_once 保证不连点；
        #   ② 然后要求「突破极限入口」**连续 3 帧**都在才算收干净。
        #      settle 就是为动画帧准备的：动画快就早走，慢就多等一帧，
        #      比 sleep 固定 1.2 秒准，也不会白等。
        # ❗**要重试到关掉为止**（硬约束 153：点一下没反应不等于失败）。
        #   真机 2026-11-07 04:55:41 那一轮 ✕ 点得很准 —— 离线量到 X 字形
        #   bbox x 1214~1233 / y 35~54，落点 (1224,45) 正中，E_196_2 匹配 1.000
        #   —— 但面板正在弹入动画里，这一下被吞了。原来只点一次、然后空等
        #   10 秒，于是「面板关不掉」→「回不到列表」→ 后面几行的 SSR 全漏读。
        #   现在等入口出现 → 没出现就按 1.5 秒节流补点（`click_once` 自己限流）。
        for _ in self.loop(timeout=15):
            if self.wait_until_appear(E_195_1, offset=(20, 20), timeout=2, settle=3):
                break
            self.click_once(E_196_2, '关闭突破极限', offset=(10, 10), interval=1.5)
        else:
            logger.warning('验号：突破极限面板关不掉')
        return value

    def close_review(self):
        """「团长！喜欢星之救援者吗？」好评弹窗盖住整屏时点「取消」。

        ❗它**整屏盖住**，任何一段都认不出自己的按钮：真机 2026-11-07 06:14
        连着三轮全空转 —— 开场引导 40 秒、昵称 12 秒、引导 12 秒都没东西可点，
        `gacha` 只跑了 0.4 秒。判据用 `E_204_1`（那行「别忘了给个好评喔！」，
        只在弹窗上出现，离线 1.000 / 其它帧远低于阈值），点击用 `E_204_2`
        （「取消」按钮本身，中心 (703,490)）。

        Returns:
            bool: 这一帧点掉了弹窗（调用方应当跳过本帧的其它判断）。
        """
        if self.appear(E_204_1, offset=(10, 10)):
            self.click_once(E_204_2, '关闭好评弹窗', offset=(10, 10))
            return True
        return False

    def back_to_list(self, timeout=12):
        """从详情页退回列表。"""
        for _ in self.loop(timeout=timeout):
            if self.list_rows():
                return True
            if self.close_review():
                continue
            # ❗突破极限面板开着的时候左上返回点在面板底下，点不动 ——
            #   真机 2026-11-07 04:59 就卡在这一屏：「回不到列表」接着
            #   「20 秒内没看到救援者列表」，整轮一个 SSR 都没读到。
            #   先把 ✕ 点掉（`read_dups` 里那一套补点逻辑之前漏了这条出路）。
            if self.appear(E_196_2, offset=(10, 10)):
                self.click_once(E_196_2, '关闭突破极限', offset=(10, 10))
                continue
            self.click_once(E_193_1, '返回列表', offset=(10, 10))
        logger.warning('验号：回不到列表')
        return False

    def scan_rescuers(self):
        """当前列表 → `[{name, troupe, label, dups, count}]`。

        从上往下一行一行点；**遇到第一个非 SSR 就结束**（列表是 SSR 在前）。
        只读当前一屏 —— 露一半的那一行不算，它的圆心在面板边缘上，点它是点屏幕外。
        """
        rows = self.wait_for_list()
        if not rows:
            return []
        logger.info('验号：列表 %d 行，从上往下一个一个看' % len(rows))

        result = []
        for i, (cy, cx, _r) in enumerate(rows):
            logger.hr('第 %d/%d 行  y=%d' % (i + 1, len(rows), cy), level=3)

            # 好评弹窗可能在任何时候盖上来：先点掉再读这一行，不然会读到弹窗上的字
            for _ in self.loop(timeout=10):
                if not self.close_review():
                    break

            if not self.select_row(cy):
                # 选不中是技术故障，不是"这行不是 SSR"，别把它当结束条件
                continue

            # ❗点完一行，列表高亮是立刻的，**左上角摘要要淡入 0.3~0.5 秒**。
            #   不等这一下，稀有度会判成上一行的：真机实测第 5 行是 SR，
            #   却因为是第 4 行（SSR）的旧画面被判成 SSR，还展开了详情去读重复数。
            self.wait_until_still(LABEL_AREA, timeout=4)

            if not self.is_ssr():
                logger.info('第 %d 行不是 SSR，后面的都不看了' % (i + 1))
                break

            name, troupe = self.read_label_ready()
            if not name:
                logger.warning('第 %d 行是 SSR，但名字没读出来，跳过' % (i + 1))
                continue

            dups = None
            if self.open_detail():
                dups = self.read_dups()
            self.back_to_list()

            info = {
                'name': name,
                'troupe': troupe,
                'label': '%s@%s' % (name, troupe) if troupe else name,
                'dups': dups,
                'count': None if dups is None else 1 + dups,
            }
            result.append(info)
            logger.info('SSR %s，重复 %s 次（共 %s 个）'
                        % (info['label'], info['dups'], info['count']))
        return result
