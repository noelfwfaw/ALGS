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


if __name__ == '__main__':
    logger.hr('AlGS', level=0)
    AlGS().loop()
