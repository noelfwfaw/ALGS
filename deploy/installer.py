from deploy.patch import pre_checks

pre_checks()

from deploy.adb import AdbManager
from deploy.alas import AlasManager
from deploy.app import AppManager
from deploy.config import ExecutionError
from deploy.git import GitManager
from deploy.pip import PipManager


class Installer(GitManager, PipManager, AdbManager, AppManager, AlasManager):
    def install(self):
        from deploy.atomic import atomic_failure_cleanup
        atomic_failure_cleanup('./config')
        try:
            # The installer is an explicit user action: it must initialise the
            # git checkout even when AutoUpdate is off (the default for release
            # archives). `git_install()` short-circuits on that flag.
            self.git_repository_init(
                repo=self.Repository,
                source='origin',
                branch=self.Branch,
                proxy=self.GitProxy,
                ssl_verify=self.SSLVerify,
            )
            self.alas_kill()
            self.pip_install()
            self.app_update()
            self.adb_install()
        except ExecutionError:
            exit(1)


if __name__ == '__main__':
    Installer().install()
