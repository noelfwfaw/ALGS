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
    SCHEDULER_PRIORITY = """
    Restart
    > HazeworldMail > HazeworldRoom > HazeworldExercise > HazeworldFriend > HazeworldTask > HazeworldPass
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
