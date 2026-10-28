"""
Global asset namespace of the running instance.

In the original project this file stores the game server ('cn', 'en', 'jp', 'tw').
Here the same mechanism is reused as a **game namespace**: every game owns an
`assets/<namespace>/...` folder plus its own entry in the `assets.py` dicts, so
switching game is exactly the same operation as switching server used to be.

Rules:
- Always `import module.config.server as server`, never `from ... import server`,
  otherwise you get a snapshot and switching has no effect.
- Always switch with `set_server()`. It also releases cached resources, which is
  required because asset images are cached per namespace.
"""

# All asset namespaces = all supported games.
VALID_SERVER = ['hazeworld', 'lostsword', 'browndust']

# Current namespace. Default to the first one to avoid errors in dev_tools.
server = VALID_SERVER[0]

# Package name -> namespace. Fill this with your own games:
#   'com.example.mygame': 'mygame'
VALID_PACKAGE = {
    'com.feimo.hazeworld.bilibili': 'hazeworld',
    # 失落之剑 (Lost Sword), Wemade Connect
    'com.wemadeconnect.aos.lostdgl': 'lostsword',
    # 棕色尘埃2 (Brown Dust II), Neowiz. Read off the emulator with
    # `adb shell pm list packages`, not guessed from the store listing.
    'com.neowizgames.game.browndust2': 'browndust',
}

# Channel packages that share a namespace: package -> (namespace, channel name)
VALID_CHANNEL_PACKAGE = {}

# Namespace -> list of server/region names, only used to build the GUI dropdown.
VALID_SERVER_LIST = {
    'hazeworld': ['default'],
    'lostsword': ['default'],
    'browndust': ['default'],
}

# Package name -> launch activity. Leave empty unless a game needs an explicit
# activity name; the device layer falls back to its own detection.
DICT_PACKAGE_TO_ACTIVITY = {}


def set_server(package_or_server: str):
    """
    Change namespace globally, including assets and namespace specific methods.

    Args:
        package_or_server: package name or namespace name.
    """
    global server
    server = to_server(package_or_server)

    from module.base.resource import release_resources
    release_resources()


def to_server(package_or_server: str) -> str:
    """
    Convert package/namespace to namespace.

    Args:
        package_or_server (str):

    Returns:
        str: Namespace, unknown names fall back to the first valid namespace.
    """
    if package_or_server in VALID_SERVER:
        return package_or_server
    elif package_or_server in VALID_PACKAGE:
        return VALID_PACKAGE[package_or_server]
    elif package_or_server in VALID_CHANNEL_PACKAGE:
        return VALID_CHANNEL_PACKAGE[package_or_server][0]
    else:
        return VALID_SERVER[0]


def to_package(package_or_server: str) -> str:
    """
    Convert package/namespace to package name.

    Args:
        package_or_server (str):

    Returns:
        str: Package name, None if not found.
    """
    package_or_server = package_or_server.lower()
    if package_or_server in VALID_PACKAGE:
        return package_or_server

    for key, value in VALID_PACKAGE.items():
        if value == package_or_server:
            return key

    if package_or_server in VALID_CHANNEL_PACKAGE:
        return package_or_server

    for key, value in VALID_CHANNEL_PACKAGE.items():
        if value[0] == package_or_server:
            return key

    return None
