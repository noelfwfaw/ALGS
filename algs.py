from alas import GameScheduler
from module.logger import logger

"""
AlGS - A multi-game scheduler built on the Alas framework.

Every task in `module/config/argument/task.yaml` needs a method here whose name
is the snake_case form of the task name (`inflection.underscore`). The scheduler
calls it by name, so a task is "registered" simply by existing.

Game tasks are added under their own section, one line per task, so the game
code is imported only when the task actually runs.
"""


class AlGS(GameScheduler):
    """
    Scheduler of every supported game.

    Each game registers itself twice: a task method per task (see below) and an
    entry in `games`, which is how the framework finds the UI class when it has
    to walk pages on its own, such as `goto_main` while the queue is empty.
    """

    # Namespace -> (module, class name) of the game UI class.
    games = {
        'hazeworld': ('module.hazeworld.hazeworld_ui', 'HazeworldUI'),
        'lostsword': ('module.lostsword.lostsword_ui', 'LostswordUI'),
        'browndust': ('module.browndust.browndust_ui', 'BrowndustUI'),
        'chaoszero': ('module.chaoszero.chaoszero_ui', 'ChaoszeroUI'),
        'crosscore': ('module.crosscore.crosscore_ui', 'CrosscoreUI'),
        'starsavior': ('module.starsavior.starsavior_ui', 'StarsaviorUI'),
        'trickcal': ('module.trickcal.trickcal_ui', 'TrickcalUI'),
    }

    @property
    def ui_class(self):
        """
        UI class of the game currently bound to the config.

        Returns:
            type: Subclass of UI, or None when the namespace is unknown.
        """
        import importlib

        import module.config.server as server

        entry = self.games.get(server.server)
        if entry is None:
            return None
        module_name, class_name = entry
        return getattr(importlib.import_module(module_name), class_name)

    # ==================== Hazeworld (苍雾世界) ====================


    def hazeworld_mail(self):
        from module.hazeworld.mail import HazeworldMail
        HazeworldMail(config=self.config, device=self.device).run()

    def hazeworld_room(self):
        from module.hazeworld.room import HazeworldRoom
        HazeworldRoom(config=self.config, device=self.device).run()

    def hazeworld_exercise(self):
        from module.hazeworld.exercise import HazeworldExercise
        HazeworldExercise(config=self.config, device=self.device).run()

    def hazeworld_friend(self):
        from module.hazeworld.friend import HazeworldFriend
        HazeworldFriend(config=self.config, device=self.device).run()

    def hazeworld_task(self):
        from module.hazeworld.task import HazeworldTask
        HazeworldTask(config=self.config, device=self.device).run()

    def hazeworld_pass(self):
        from module.hazeworld.battle_pass import HazeworldPass
        HazeworldPass(config=self.config, device=self.device).run()

    def hazeworld_support(self):
        from module.hazeworld.support import HazeworldSupport
        HazeworldSupport(config=self.config, device=self.device).run()

    def hazeworld_core(self):
        from module.hazeworld.core import HazeworldCore
        HazeworldCore(config=self.config, device=self.device).run()

    def hazeworld_shop(self):
        from module.hazeworld.shop import HazeworldShop
        HazeworldShop(config=self.config, device=self.device).run()

    def hazeworld_logistics(self):
        from module.hazeworld.logistics import HazeworldLogistics
        HazeworldLogistics(config=self.config, device=self.device).run()

    def hazeworld_honor(self):
        from module.hazeworld.honor import HazeworldHonor
        HazeworldHonor(config=self.config, device=self.device).run()

    def hazeworldevent(self):
        from module.hazeworld.hazeworldevent import Hazeworldevent
        Hazeworldevent(config=self.config, device=self.device).run()

    # ==================== Lost Sword (失落之剑) ====================

    def lostsword_mail(self):
        from module.lostsword.mail import LostswordMail
        LostswordMail(config=self.config, device=self.device).run()

    def lostsword_guild(self):
        from module.lostsword.guild import LostswordGuild
        LostswordGuild(config=self.config, device=self.device).run()

    def lostsword_main(self):
        from module.lostsword.main_story import LostswordMain
        LostswordMain(config=self.config, device=self.device).run()

    def lostsword_boss(self):
        from module.lostsword.boss import LostswordBoss
        LostswordBoss(config=self.config, device=self.device).run()

    def lostsword_maze(self):
        from module.lostsword.maze import LostswordMaze
        LostswordMaze(config=self.config, device=self.device).run()

    def lostsword_event(self):
        from module.lostsword.event import LostswordEvent
        LostswordEvent(config=self.config, device=self.device).run()

    def lostsword_dungeon(self):
        from module.lostsword.dungeon import LostswordDungeon
        LostswordDungeon(config=self.config, device=self.device).run()

    def lostsword_star(self):
        from module.lostsword.star import LostswordStar
        LostswordStar(config=self.config, device=self.device).run()

    def lostsword_copy(self):
        from module.lostsword.copy import LostswordCopy
        LostswordCopy(config=self.config, device=self.device).run()

    def lostsword_arena(self):
        from module.lostsword.arena import LostswordArena
        LostswordArena(config=self.config, device=self.device).run()

    def lostsword_affection(self):
        from module.lostsword.affection import LostswordAffection
        LostswordAffection(config=self.config, device=self.device).run()

    def lostsword_round(self):
        from module.lostsword.round_table import LostswordRoundTable
        LostswordRoundTable(config=self.config, device=self.device).run()

    def lostsword_shop(self):
        from module.lostsword.shop import LostswordShop
        LostswordShop(config=self.config, device=self.device).run()

    def lostsword_treasure(self):
        from module.lostsword.treasure import LostswordTreasure
        LostswordTreasure(config=self.config, device=self.device).run()

    def lostsword_summon(self):
        from module.lostsword.summon import LostswordSummon
        LostswordSummon(config=self.config, device=self.device).run()

    def lostsword_task(self):
        from module.lostsword.task import LostswordTask
        LostswordTask(config=self.config, device=self.device).run()

    def lostsword_redeem(self):
        from module.lostsword.redeem import LostswordRedeem
        LostswordRedeem(config=self.config, device=self.device).run()

    # ==================== Brown Dust II (棕色尘埃2) ====================

    def browndust_summon(self):
        from module.browndust.summon import BrowndustSummon
        BrowndustSummon(config=self.config, device=self.device).run()

    def browndust_hunt(self):
        from module.browndust.hunt import BrowndustHunt
        BrowndustHunt(config=self.config, device=self.device).run()

    def browndust_mail(self):
        from module.browndust.mail import BrowndustMail
        BrowndustMail(config=self.config, device=self.device).run()

    def browndust_manager(self):
        from module.browndust.manager import BrowndustManager
        BrowndustManager(config=self.config, device=self.device).run()

    def browndust_task(self):
        from module.browndust.task import BrowndustTask
        BrowndustTask(config=self.config, device=self.device).run()

    def browndust_pass(self):
        from module.browndust.battle_pass import BrowndustPass
        BrowndustPass(config=self.config, device=self.device).run()

    def browndust_event(self):
        # 一期的五件事全在这一个任务里：剧情 → 活动战斗 → 魔兽追踪者 →
        # 活动任务 → 活动商店。只启动一次模拟器、只进一次活动页。
        from module.browndust.event import BrowndustEvent
        BrowndustEvent(config=self.config, device=self.device).run()

    def browndust_redeem(self):
        from module.browndust.redeem import BrowndustRedeem
        BrowndustRedeem(config=self.config, device=self.device).run()

    # ==================== Chaos Zero Nightmare (卡厄思梦境) ====================

    def chaoszero_main(self):
        # 唤起：把客户端从任意一屏带到主界面。这个游戏的其它任务都排在它后面。
        from module.chaoszero.main import ChaoszeroMain
        ChaoszeroMain(config=self.config, device=self.device).run()

    def chaoszero_simulation(self):
        # 战斗训练：把每天的体力刷掉。
        from module.chaoszero.simulation import ChaoszeroSimulation
        ChaoszeroSimulation(config=self.config, device=self.device).run()

    def chaoszero_ark(self):
        # 方舟都市：政策室批政策 + 咖啡廳领体力。
        from module.chaoszero.ark import ChaoszeroArk
        ChaoszeroArk(config=self.config, device=self.device).run()

    def chaoszero_daily(self):
        # 日常任務：當日行程的「全部領取」。
        from module.chaoszero.daily import ChaoszeroDaily
        ChaoszeroDaily(config=self.config, device=self.device).run()

    def chaoszero_pass(self):
        # 通行證（阿爾基亞農補給）：任务奖励 + 等级奖励。
        # 文件名不能用 pass.py：`pass` 是保留字，`from module.chaoszero.pass import`
        # 直接 SyntaxError（交错战线也是 battle_pass.py）。
        from module.chaoszero.battle_pass import ChaoszeroPass
        ChaoszeroPass(config=self.config, device=self.device).run()

    def chaoszero_redeem(self):
        # 兑换码：从 GameKee 抓，新的在游戏里兑掉（不按服务器过滤）。
        from module.chaoszero.redeem import ChaoszeroRedeem
        ChaoszeroRedeem(config=self.config, device=self.device).run()

    # ==================== Cross Core (交错战线) ====================

    def crosscore_main(self):
        # 唤起：把客户端从任意一屏带到主界面。这个游戏的其它任务都排在它后面。
        from module.crosscore.main import CrosscoreMain
        CrosscoreMain(config=self.config, device=self.device).run()

    def crosscore_mail(self):
        # 邮箱：一键领取全部邮件。
        from module.crosscore.mail import CrosscoreMail
        CrosscoreMail(config=self.config, device=self.device).run()

    def crosscore_task(self):
        # 任务：日常 → 周常 依次一键领取。
        from module.crosscore.task import CrosscoreTask
        CrosscoreTask(config=self.config, device=self.device).run()

    def crosscore_pass(self):
        # 通行证（勘探指南）：每日 / 每周 / 本期任务领取 + 通行证全部领取。
        from module.crosscore.battle_pass import CrosscorePass
        CrosscorePass(config=self.config, device=self.device).run()

    def crosscore_explore(self):
        # 每日探索：选一个子项的最高已解锁层，扫荡消耗全部体力。
        from module.crosscore.explore import CrosscoreExplore
        CrosscoreExplore(config=self.config, device=self.device).run()

    def crosscore_exercise(self):
        # 模拟军演：只打对手列表第一个，打满模拟次数后到军演商店买东西。
        from module.crosscore.exercise import CrosscoreExercise
        CrosscoreExercise(config=self.config, device=self.device).run()

    def crosscore_base(self):
        # 基地：领素材 / 驻员换班 / 订单库买构建订单。
        from module.crosscore.base import CrosscoreBase
        CrosscoreBase(config=self.config, device=self.device).run()

    def crosscore_redeem(self):
        # 兑换码：从 GameKee 抓，新的在游戏里兑掉（官服 / B服 都试一遍）。
        from module.crosscore.redeem import CrosscoreRedeem
        CrosscoreRedeem(config=self.config, device=self.device).run()

    # ==================== Star Savior (星之救援者) ====================
    #
    # ❗这是**工具**不是任务（`task.yaml` 里 `page: 'tool'`、没有 `Scheduler` 组）：
    #   调度器的 `loop()` 永远挑不到它，只有 WebUI「工具」页点 Start
    #   → `ProcessManager.run_process('Starsavior2')` → 这里，跑完进程即退出。

    def starsavior2(self):
        """刷初始：登录 → 引导 → 旅程 → 结算 → 领奖 → 抽卡 → 验号（按配置决定停在哪）。"""
        from module.config.server import set_server

        # 工具是手动启动的，没有调度器 `loop()` 那套兜底，这几步顺序不能错：
        #
        # 1. 先把 `Device` 建出来。它的 `__init__` 会按 `Emulator_PackageName`
        #    把命名空间设成**包名对应的游戏**（这台机子上是 `hazeworld`），
        #    所以要先建、后切，否则它会把第 2 步切好的又改回去。
        # 2. `set_server('starsavior')`：`switch_game()` 只在"游戏真的换了"
        #    时才切命名空间，模拟器本来就停在星之救援者上时它直接返回，
        #    命名空间还留在 `hazeworld`，`game_ui()` 会拿成 `HazeworldUI`。
        # 3. `switch_game('starsavior')`：停掉别的游戏、把 `device.package`
        #    指到星之救援者、冷启动。
        # 4. ❗`Starsavior2` 必须在 `set_server()` **之后**才 import：`assets.py`
        #    在模块导入时就展开 `Button.file`，命名空间还是 hazeworld 时会
        #    `KeyError: 'hazeworld'`。
        # 5. `config.bind('Starsavior2')`：不 bind 的话 `self.config.Starsavior2_Nickname`
        #    读到的是 `config_generated.py` 里的默认值，用户在 GUI 里填的昵称白填。
        device = self.device
        set_server('starsavior')
        self.switch_game('starsavior')

        from module.starsavior.starsavior2 import Starsavior2

        self.config.bind('Starsavior2')
        Starsavior2(config=self.config, device=device).run()

    # ==================== Trickcal (嘟嘟脸恶作剧) ====================
    #
    # 登录流程由 dev_tools/spec_build.py 从页面卡片生成（chain=True，按钮驱动）。
    # 保留这个段落头：spec_build.add_entry() 靠它定位，否则新任务方法会被
    # 插到 `if __name__ == '__main__'` 前面（苍雾活动踩过一次）。



    def trickcal_login(self):
        from module.trickcal.trickcal_login import TrickcalLogin
        TrickcalLogin(config=self.config, device=self.device).run()

    def trickcal_mail(self):
        from module.trickcal.mail import TrickcalMail
        TrickcalMail(config=self.config, device=self.device).run()

    def trickcal_friend(self):
        from module.trickcal.friend import TrickcalFriend
        TrickcalFriend(config=self.config, device=self.device).run()

    def trickcal_task(self):
        from module.trickcal.task import TrickcalTask
        TrickcalTask(config=self.config, device=self.device).run()

    def trickcal_shop(self):
        from module.trickcal.shop import TrickcalShop
        TrickcalShop(config=self.config, device=self.device).run()

    def trickcal_normal_shop(self):
        from module.trickcal.normal_shop import TrickcalNormalShop
        TrickcalNormalShop(config=self.config, device=self.device).run()

    def trickcal_pass(self):
        from module.trickcal.pass_task import TrickcalPass
        TrickcalPass(config=self.config, device=self.device).run()


if __name__ == '__main__':
    logger.hr('AlGS', level=0)
    AlGS().loop()
