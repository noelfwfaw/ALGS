import copy
from typing import Optional, Union

from deploy.logger import logger
from deploy.utils import *


class ExecutionError(Exception):
    pass


# AlGS lives in its own repository. `git_repository_init()` does
# `remote set-url origin` + `reset --hard origin/master`, so an upstream ALAS
# default would silently replace this working tree with the Azur Lane code.
ALGS_REPOSITORY = 'https://github.com/noelfwfaw/ALGS.git'

# Legacy aliases and mirrors left over from upstream ALAS / StarRailCopilot
# installers. Users upgrading from an old `config/deploy.yaml` may still have
# one of these written down; redirect them instead of letting `reset --hard`
# pull a completely different project into this directory.
LEGACY_REPOSITORIES = (
    'global',
    'cn',
    'https://github.com/LmeSzinc/AzurLaneAutoScript',
    'https://github.com/LmeSzinc/AzurLaneAutoScript.git',
    'https://github.com/LmeSzinc/StarRailCopilot',
    'https://github.com/LmeSzinc/StarRailCopilot.git',
    'https://gitee.com/LmeSzinc/AzurLaneAutoScript',
    'https://gitee.com/lmeszinc/azur-lane-auto-script-mirror',
    'https://e.coding.net/llop18870/alas/AzurLaneAutoScript.git',
    'https://e.coding.net/saarcenter/alas/AzurLaneAutoScript.git',
    'https://git.saarcenter.com/LmeSzinc/AzurLaneAutoScript.git',
    'git://git.lyoko.io/AzurLaneAutoScript',
)


class ConfigModel:
    # Git
    Repository: str = ALGS_REPOSITORY
    Branch: str = "master"
    GitExecutable: str = "./toolkit/Git/mingw64/bin/git.exe"
    GitProxy: Optional[str] = None
    SSLVerify: bool = False
    # GitHub release archives have no `.git/`. Keep the destructive git updater
    # off by default so it never rewrites a freshly unpacked installation.
    AutoUpdate: bool = False

    # Python
    PythonExecutable: str = "./toolkit/python.exe"
    PypiMirror: Optional[str] = None
    InstallDependencies: bool = True
    RequirementsFile: str = "requirements.txt"

    # Adb
    AdbExecutable: str = "./toolkit/Lib/site-packages/adbutils/binaries/adb.exe"
    ReplaceAdb: bool = True
    AutoConnect: bool = True
    InstallUiautomator2: bool = True

    # Ocr
    UseOcrServer: bool = False
    StartOcrServer: bool = False
    OcrServerPort: int = 22268
    OcrClientAddress: str = "127.0.0.1:22268"

    # Update
    EnableReload: bool = True
    CheckUpdateInterval: int = 0
    AutoRestartTime: Optional[str] = None

    # Misc
    DiscordRichPresence: bool = False

    # Remote Access
    EnableRemoteAccess: bool = False
    SSHUser: Optional[str] = None
    SSHServer: Optional[str] = None
    SSHExecutable: Optional[str] = None

    # Webui
    WebuiHost: str = "0.0.0.0"
    WebuiPort: int = 22267
    WebuiSSLKey: Optional[str] = None
    WebuiSSLCert: Optional[str] = None
    Language: str = "en-US"
    Theme: str = "default"
    DpiScaling: bool = True
    Password: Optional[str] = None
    CDN: Union[str, bool] = False
    Run: Optional[str] = None

    # Dynamic
    GitOverCdn: bool = False


class DeployConfig(ConfigModel):
    def __init__(self, file=DEPLOY_CONFIG):
        """
        Args:
            file (str): User deploy config.
        """
        self.file = file
        self.config = {}
        self.config_template = {}
        self.read()

        self.show_config()

    def show_config(self):
        logger.hr("Show deploy config", 1)
        for k, v in self.config.items():
            if k in ("Password", "SSHUser"):
                continue
            if self.config_template.get(k) == v:
                continue
            logger.info(f"{k}: {v}")

        logger.info(f"Rest of the configs are the same as default")

    def read(self):
        """
        Read and update deploy config, copy `self.configs` to properties.
        """
        self.config = poor_yaml_read(DEPLOY_TEMPLATE)
        self.config_template = copy.deepcopy(self.config)
        origin = poor_yaml_read(self.file)
        self.config.update(origin)

        for key, value in self.config.items():
            if hasattr(self, key):
                super().__setattr__(key, value)

        self.config_redirect()

        if self.config != origin:
            self.write()

    def write(self):
        poor_yaml_write(self.config, self.file)

    def config_redirect(self):
        """
        Redirect deploy config, must be called after each `read()`
        """
        if self.Repository in LEGACY_REPOSITORIES:
            logger.warning(
                f'Repository {self.Repository} is an upstream ALAS/SRC address, '
                f'redirect to {ALGS_REPOSITORY}'
            )
            # Bypass module.webui.config.DeployConfig.__setattr__() so we don't
            # write deploy.yaml in the middle of read().
            super().__setattr__('Repository', ALGS_REPOSITORY)
            self.config['Repository'] = ALGS_REPOSITORY
        if self.PypiMirror in [
            'https://pypi.tuna.tsinghua.edu.cn/simple'
        ]:
            self.PypiMirror = 'https://mirrors.aliyun.com/pypi/simple'
            self.config['PypiMirror'] = 'https://mirrors.aliyun.com/pypi/simple'

        # GitOverCdn packs contain upstream ALAS commits only and are not
        # compatible with AlGS. Keep the flag off unconditionally.
        # Bypass webui.config.DeployConfig.__setattr__(), don't write it to yaml.
        super().__setattr__('GitOverCdn', False)

    def filepath(self, key):
        """
        Args:
            key (str):

        Returns:
            str: Absolute filepath.
        """
        return (
            os.path.abspath(os.path.join(self.root_filepath, self.config[key]))
            .replace(r"\\", "/")
            .replace("\\", "/")
            .replace('"', '"')
        )

    @cached_property
    def root_filepath(self):
        return (
            os.path.abspath(os.path.join(os.path.dirname(__file__), "../"))
            .replace(r"\\", "/")
            .replace("\\", "/")
            .replace('"', '"')
        )

    def execute(self, command, allow_failure=False, output=True):
        """
        Args:
            command (str):
            allow_failure (bool):
            output(bool):

        Returns:
            bool: If success.
                Terminate installation if failed to execute and not allow_failure.
        """
        command = command.replace(r"\\", "/").replace("\\", "/").replace('"', '"')
        if not output:
            command = command + ' >nul 2>nul'
        logger.info(command)
        error_code = os.system(command)
        if error_code:
            if allow_failure:
                logger.info(f"[ allowed failure ], error_code: {error_code}")
                return False
            else:
                logger.info(f"[ failure ], error_code: {error_code}")
                self.show_error(command)
                raise ExecutionError
        else:
            logger.info(f"[ success ]")
            return True

    def show_error(self, command=None):
        logger.hr("Update failed", 0)
        self.show_config()
        logger.info("")
        logger.info(f"Last command: {command}")
        logger.info(
            "Please check your deploy settings in config/deploy.yaml "
            "and re-open Alas.exe"
        )
        logger.info("Take the screenshot of entire window if you need help")
