import json
import os
from datetime import datetime

import onepush.core
import yaml
from onepush import get_notifier
from onepush.core import Provider
from onepush.exceptions import OnePushException
from onepush.providers.custom import Custom
from requests import Response

from module.logger import logger

onepush.core.log = logger

# Headline of a push for an error the script recovers from itself: game stuck,
# too many clicks, game client bug, game not running. All four schedule a
# `Restart`, so the script may go on; fatal errors use the "脚本已停止" headline.
RECOVERABLE_HEADLINE = 'AlGS 运行出错，已安排重启游戏。'

# Whether a fatal error has already been pushed in this process.
#
# The scheduler pushes in the deepest frame that knows what went wrong; the
# WebUI process wrapper is a second, much coarser net around the very same
# exception. Without this flag a crash outside a task (config reload, game
# switching) would send two messages for one error.
_error_pushed = False


def load_onepush_conf(raw):
    """把 `Error.OnePushConfig` 解析成 onepush 的参数字典，**容忍整段多缩进**。

    GUI 里那段是 `mode: yaml` 的手填文本框，从文档复制时很容易除第一行外
    每行都多带一个前导空格（本机 2026-11-07 的配置就是这样：
    `provider: custom\\n url: https://...`）。YAML 会把 ` url:` 当成
    `provider` 的续行，抛 `ScannerError: mapping values are not allowed here`
    —— 结果就是推送永远发不出去，而日志只说「没配 provider」，看不出原因。

    所以先按原样解析，失败再把**第一行之后**的行统一去掉公共缩进重试。
    第一行不动：它本来就该在顶格，多缩进的情况交给 YAML 自己处理。

    Returns:
        tuple: `(dict, str)` —— 参数字典 + 规整后的 YAML 文本。
        第二项必须回传给 `handle_notify()`，因为它在内部还要自己再解析一遍，
        给它原始那份照样会失败。
    """
    raw = (raw or '').replace('\r\n', '\n').replace('\r', '\n')

    def parse(text):
        data = {}
        for item in yaml.safe_load_all(text):
            if isinstance(item, dict):
                data.update(item)
        return data

    try:
        data = parse(raw)
        if data:
            return data, raw
    except Exception:
        pass

    lines = raw.split('\n')
    head, tail = lines[:1], lines[1:]
    widths = [len(line) - len(line.lstrip(' ')) for line in tail if line.strip()]
    if widths:
        pad = min(widths)
        if pad:
            tail = [line[pad:] if line.strip() else line for line in tail]
    text = '\n'.join(head + tail)

    try:
        return parse(text), text
    except Exception:
        return {}, text


def read_onepush_config(config_name='alas'):
    """直接从 `config/<config_name>.json` 读 `Alas.Error.OnePushConfig`。

    不能走 `AlasConfig`：这个函数存在的理由就是「配置对象本身建不出来」的那
    种错误（读文件失败、某个选项非法、模拟器信息不全）。那时候文件通常还是
    好的，而正是最需要推一条消息的场合。
    """
    path = os.path.join('./config', f'{config_name}.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f'Cannot read push config from {path}: {e}')
        return ''

    try:
        return data['Alas']['Error']['OnePushConfig'] or ''
    except (KeyError, TypeError):
        return ''


def format_error_message(config_name, message, task=None, log_file=None,
                         headline='AlGS 发生无法处理的异常，脚本已停止。'):
    """统一的错误推送正文：实例 / 任务 / 错误 / 时间 / 日志。

    ❗首行带 `AlGS`，标题固定 `Alas推送`：钉钉连接器的 flow 挂了关键词过滤，
    两处都不含关键词时消息会被丢掉，而 HTTP 照样 200。改文案别删这两个词。

    Args:
        config_name (str): 实例名。
        message (str): 出错内容，多行也可以。
        task (str): 任务名，None 表示不带。
        log_file (str): 日志文件路径，None 表示不带。
        headline (str): 首行。默认是「脚本已停止」；可恢复的错误用
            `RECOVERABLE_HEADLINE`。

    Returns:
        str:
    """
    lines = [headline,
             f'实例：{config_name}']
    if task:
        lines.append(f'任务：{task}')
    lines.append(f'错误：{message}')
    lines.append(f'时间：{datetime.now():%Y-%m-%d %H:%M:%S}')
    if log_file:
        lines.append(f'日志：{log_file}')
    return '\n'.join(lines)


def push_message(raw_config, title, content):
    """解析一段 onepush YAML 并推一条消息。

    `provider` 为空（默认值 `provider: null`）时直接跳过，不算失败。
    任何异常都吞掉只记日志：这里跑在「已经在处理错误」的路径上，推送自己
    再炸一次只会把原来的错误盖掉。

    Returns:
        bool: 是否真的发出去了。
    """
    data, config = load_onepush_conf(raw_config)
    provider = data.get('provider')
    if not provider or str(provider).strip().lower() in ('null', 'none'):
        logger.info('Push notify skipped, no provider in Error.OnePushConfig')
        return False
    try:
        return bool(handle_notify(config, title=title, content=content))
    except Exception as e:
        logger.warning(f'Push notify failed: {e}')
        return False


def notify_error(config_name, message, title='Alas推送', raw_config=None):
    """推送一条**致命错误**，同一进程只推一次。

    ❗标题固定带 `Alas`：钉钉连接器的 flow 里挂了关键词过滤，输入里不出现
    关键词会直接 break，而 HTTP 照样 200。正文里的 `AlGS` 同理，改文案时
    这两个词都别删。

    Args:
        config_name (str): 实例名，`raw_config` 为空时用它去读配置文件。
        message (str): 推送正文。
        title (str): 推送标题。
        raw_config (str): 已经拿到的 `Error.OnePushConfig` 原文，None 表示现读。

    Returns:
        bool: 是否真的发出去了（没配 / 发失败 / 本进程已推过都是 False）。
    """
    global _error_pushed
    if _error_pushed:
        logger.info('Fatal error already pushed in this process, skip')
        return False
    _error_pushed = True

    if raw_config is None:
        raw_config = read_onepush_config(config_name)

    logger.hr('Notify', level=1)
    return push_message(raw_config, title=title, content=message)


def notify_warning(config_name, message, title='Alas推送', raw_config=None):
    """推送一条**可恢复**的错误（卡死 / 误点过多 / 客户端异常 / 游戏不在运行）。

    ❗**不碰** `_error_pushed`：这些错误脚本会自己 `Restart` 接着跑，如果占用
    致命错误的去重名额，之后真正让进程退出的那条反而推不出去。

    Args:
        config_name (str): 实例名，`raw_config` 为空时用它去读配置文件。
        message (str): 推送正文。
        title (str): 推送标题。
        raw_config (str): 已经拿到的 `Error.OnePushConfig` 原文，None 表示现读。

    Returns:
        bool: 是否真的发出去了。
    """
    if raw_config is None:
        raw_config = read_onepush_config(config_name)

    logger.hr('Notify', level=1)
    return push_message(raw_config, title=title, content=message)


def handle_notify(_config: str, **kwargs) -> bool:
    try:
        config = {}
        for item in yaml.safe_load_all(_config):
            config.update(item)
    except Exception:
        logger.error("Fail to load onepush config, skip sending")
        return False
    try:
        provider_name: str = config.pop("provider", None)
        if provider_name is None:
            logger.info("No provider specified, skip sending")
            return False
        notifier: Provider = get_notifier(provider_name)
        required: list[str] = notifier.params["required"]
        config.update(kwargs)

        # pre check
        for key in required:
            if key not in config:
                logger.warning(
                    f"Notifier {notifier.name} require param '{key}' but not provided"
                )

        if isinstance(notifier, Custom):
            if "method" not in config or config["method"] == "post":
                config["datatype"] = "json"
            # 原写法 `not ("data" in config or isinstance(config["data"], dict))`
            # 在配置里**没写 data** 时会拿 `config["data"]` 抛 KeyError（or 的右边
            # 照样求值），整个推送直接失败。用 get() 判断才是有意的那句「data 不是
            # dict 就当空的」。
            if not isinstance(config.get("data"), dict):
                config["data"] = {}
            if "title" in kwargs:
                config["data"]["title"] = kwargs["title"]
            if "content" in kwargs:
                config["data"]["content"] = kwargs["content"]

        if provider_name.lower() == "gocqhttp":
            access_token = config.get("access_token")
            if access_token:
                config["token"] = access_token

        resp = notifier.notify(**config)
        if isinstance(resp, Response):
            if resp.status_code != 200:
                logger.warning("Push notify failed!")
                logger.warning(f"HTTP Code:{resp.status_code}")
                return False
            else:
                if provider_name.lower() == "gocqhttp":
                    return_data: dict = resp.json()
                    if return_data["status"] == "failed":
                        logger.warning("Push notify failed!")
                        logger.warning(
                            f"Return message:{return_data['wording']}")
                        return False
    except OnePushException:
        logger.error("Push notify failed")
        return False
    except Exception as e:
        # don't show any exceptions because exceptions contain variable traceback
        logger.error(e)
        return False

    logger.info("Push notify success")
    return True
