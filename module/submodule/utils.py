import os

MOD_DICT = {}
MOD_FUNC_DICT = {}
MOD_CONFIG_DICT = {}


def get_available_func():
    """工具页能单独启动的任务名（`config_manual.TOOL_TASKS`）。

    这些不是调度任务：它们不在 `SCHEDULER_PRIORITY` 里、也没有 `Scheduler` 组，
    只由 WebUI 的「工具」页点 Start 手动跑一次。
    `ProcessManager.run_process()` 先用这个判断该走 `AlGS.run(<task>)` 的单任务分支，
    还是走 mod / mod_func 分支 —— 返回空元组的话，工具页点 Start 只会打出
    `No function matched`。

    ❗延迟导入：本模块在 WebUI 启动时就被 `process_manager` 拉进来，
    而 `module.config.config_manual` 会连带 `module.config.server` 与一堆资源。
    """
    from module.config.config_manual import ManualConfig

    return tuple(ManualConfig.TOOL_TASKS.split())


def get_available_mod():
    return set(MOD_DICT)


def get_available_mod_func():
    return set(MOD_FUNC_DICT)


def get_func_mod(func):
    return MOD_FUNC_DICT.get(func)


def list_mod_dir():
    return list(MOD_DICT.items())


def get_mod_dir(name):
    return MOD_DICT.get(name)


def get_mod_filepath(name):
    return os.path.join('./submodule', get_mod_dir(name))


def list_mod_template():
    out = []
    for file in os.listdir('./config'):
        name, extension = os.path.splitext(file)
        config_name, mod_name = os.path.splitext(name)
        mod_name = mod_name[1:]
        if config_name == 'template' and extension == '.json' and mod_name != '':
            out.append(f'{config_name}-{mod_name}')

    return out


def list_mod_instance():
    global MOD_CONFIG_DICT
    MOD_CONFIG_DICT.clear()
    out = []
    for file in os.listdir('./config'):
        name, extension = os.path.splitext(file)
        config_name, mod_name = os.path.splitext(name)
        mod_name = mod_name[1:]
        if config_name != 'template' and extension == '.json' and mod_name != '':
            out.append(config_name)
            MOD_CONFIG_DICT[config_name] = mod_name

    return out


def get_config_mod(config_name):
    """
    Args:
        config_name (str):
    """
    if config_name.startswith('template-'):
        return config_name.replace('template-', '')
    try:
        return MOD_CONFIG_DICT[config_name]
    except KeyError:
        return 'alas'
