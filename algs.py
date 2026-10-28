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

    # ==================== Lost Sword (失落之剑) ====================

    def lostsword_mail(self):
        from module.lostsword.mail import LostswordMail
        LostswordMail(config=self.config, device=self.device).run()

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


if __name__ == '__main__':
    logger.hr('AlGS', level=0)
    AlGS().loop()
