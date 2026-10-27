import module.config.server as server


class ManualConfig:
    """
    Hard-coded values that are not exposed to users.

    Only framework level constants live here. Game specific constants belong to
    the game package, so the framework stays game independent.
    """

    @property
    def SERVER(self):
        return server.server

    # Task priority, tasks on the left run first.
    # Ordering rule: restart > collect > daily collect > daily sortie > sortie > filler.
    # Keep one task per game block so that games run one after another.
    # The task-reward claim of each game sits at the end of its own block: it is
    # the least important task of the game, and running it last keeps the game
    # from being closed between two tasks of the same game. Missing a task here
    # drops it from the schedule entirely, so every task must be listed.
    #
    # The Lostsword block was reordered by the user (2026-10-27): the free gifts
    # and the mailbox come first because they are one click each, the timed
    # modes (boss / dungeon / copy / event / star / arena) follow, and the three
    # long ones (maze, main story, round table) close the block. 好感 sits next
    # to them: it is a slow walk through a deep character list, worth nothing
    # compared to a mode that expires.
    SCHEDULER_PRIORITY = """
    Restart
    > HazeworldMail > HazeworldRoom > HazeworldSupport > HazeworldExercise > HazeworldFriend > HazeworldCore > HazeworldPass > HazeworldTask
    > LostswordTreasure > LostswordShop > LostswordMail > LostswordBoss > LostswordDungeon > LostswordCopy > LostswordEvent > LostswordStar > LostswordArena > LostswordMaze > LostswordMain > LostswordRound > LostswordAffection > LostswordTask
    """

    """
    module.assets
    """
    ASSETS_FOLDER = './assets'
    ASSETS_MODULE = './module'
    ASSETS_RESOLUTION = (1280, 720)

    """
    module.base
    """
    BUTTON_OFFSET = 30
    WAIT_BEFORE_SAVING_SCREEN_SHOT = 1

    """
    module.device
    """
    DEVICE_OVER_HTTP = False
    FORWARD_PORT_RANGE = (20000, 21000)
    REVERSE_SERVER_PORT = 7903

    ASCREENCAP_FILEPATH_LOCAL = './bin/ascreencap'
    ASCREENCAP_FILEPATH_REMOTE = '/data/local/tmp/ascreencap'

    # 'DroidCast', 'DroidCast_raw'
    DROIDCAST_VERSION = 'DroidCast'
    DROIDCAST_FILEPATH_LOCAL = './bin/DroidCast/DroidCast_raw-release-1.0.apk'
    DROIDCAST_FILEPATH_REMOTE = '/data/local/tmp/DroidCast_raw.apk'

    MINITOUCH_FILEPATH_REMOTE = '/data/local/tmp/minitouch'

    HERMIT_FILEPATH_LOCAL = './bin/hermit/hermit.apk'

    SCRCPY_FILEPATH_LOCAL = './bin/scrcpy/scrcpy-server-v1.20.jar'
    SCRCPY_FILEPATH_REMOTE = '/data/local/tmp/scrcpy-server-v1.20.jar'

    MAATOUCH_FILEPATH_LOCAL = './bin/MaaTouch/maatouchsync'
    MAATOUCH_FILEPATH_REMOTE = '/data/local/tmp/maatouchsync'
