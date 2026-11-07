# -*- coding: utf-8 -*-
"""
双击 alas_tool.bat 打开的菜单。

为什么有这个东西：`python -m dev_tools.xxx` 那条命令不好记，路径里还有空格和中文，
要跑的东西又分散在三个脚本里。这里收成一个数字菜单，输出直接打在窗口里。

菜单里每一项都是薄封装，真正的逻辑还在各自的模块里：
    spec_live   实机验证链条（只看分数）
    spec_build  由 spec 生成代码
    run_task    跑一个已注册的任务
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAST = os.path.join(ROOT, 'dev_tools', '.tool_last.json')
PY = sys.executable


# ---------------------------------------------------------------- 小工具

def clean_path(text):
    """去掉引号：把文件拖进 cmd 窗口时，路径是带引号的。"""
    return text.strip().strip('"').strip("'")


def load_last():
    try:
        with open(LAST, encoding='utf-8') as f:
            return json.load(f).get('spec') or ''
    except Exception:
        return ''


def save_last(spec):
    try:
        with open(LAST, 'w', encoding='utf-8') as f:
            json.dump({'spec': spec}, f, ensure_ascii=False)
    except Exception:
        pass


def ask(prompt, default=''):
    """读一行；窗口被关掉（EOF）时安静退出。"""
    try:
        text = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(0)
    return text or default


def run(args):
    """跑一条命令，输出直接进窗口。"""
    print('')
    print('> ' + ' '.join(args))
    print('')
    return subprocess.call(args, cwd=ROOT)


# ---------------------------------------------------------------- 选文件

def pick_spec():
    """挑一份 spec：列仓库里的，也可以把文件直接拖进来。"""
    folder = os.path.join(ROOT, 'dev_tools', 'specs')
    specs = sorted(f for f in os.listdir(folder) if f.endswith('.json')) \
        if os.path.isdir(folder) else []
    last = load_last()

    print('')
    print('选一份 spec：')
    for index, name in enumerate(specs, 1):
        mark = '   ← 上次用的' if last and last.endswith(name) else ''
        print('  %d) %s%s' % (index, name, mark))
    print('  %d) 输入路径（把 spec.json 拖进这个窗口就行）' % (len(specs) + 1))
    if last:
        print('  直接回车 = 上次的：%s' % last)

    text = ask('> ')
    if not text:
        return last if last else ''
    if text.isdigit() and 1 <= int(text) <= len(specs):
        path = os.path.join(folder, specs[int(text) - 1])
    else:
        path = clean_path(text if not text.isdigit() else ask('把路径拖进来 > '))
    if not path or not os.path.isfile(path):
        print('  找不到这个文件：%s' % path)
        return ''
    save_last(path)
    return path


def load_tasks():
    """task.yaml 里注册的任务，按出现顺序。"""
    path = os.path.join(ROOT, 'module', 'config', 'argument', 'task.yaml')
    if not os.path.isfile(path):
        return []
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    tasks = []
    for index, line in enumerate(lines):
        match = re.match(r'^    ([A-Za-z]\w*):$', line)
        if match and index + 1 < len(lines) and lines[index + 1].startswith('      - '):
            tasks.append(match.group(1))
    return tasks


def pick_task():
    """先选游戏再选任务：四十多个任务平铺一屏放不下。"""
    tasks = load_tasks()
    if not tasks:
        print('  task.yaml 里没有任务')
        return None

    module_root = os.path.join(ROOT, 'module')
    games = sorted(d for d in os.listdir(module_root)
                   if os.path.isfile(os.path.join(module_root, d, 'assets.py')))

    groups = {}
    for task in tasks:
        lower = task.lower()
        game = next((g for g in games if lower.startswith(g)), '其它')
        groups.setdefault(game, []).append(task)

    names = sorted(groups)
    print('')
    print('选游戏：')
    for index, name in enumerate(names, 1):
        print('  %d) %-12s %d 个任务' % (index, name, len(groups[name])))
    text = ask('> ')
    if not text.isdigit() or not 1 <= int(text) <= len(names):
        print('  没这个编号')
        return None
    game = names[int(text) - 1]

    print('')
    print('%s 的任务：' % game)
    for index, task in enumerate(groups[game], 1):
        print('  %d) %s' % (index, task))
    text = ask('> ')
    if not text.isdigit() or not 1 <= int(text) <= len(groups[game]):
        print('  没这个编号')
        return None
    return game, groups[game][int(text) - 1]


# ---------------------------------------------------------------- 各项功能

def do_live(click):
    spec = pick_spec()
    if not spec:
        return
    frames = ask('看多少帧？[10] ', '10')
    args = [PY, '-m', 'dev_tools.spec_live', spec, '--frames', frames]
    if click:
        args.append('--click')
    run(args)


def do_build(write):
    spec = pick_spec()
    if not spec:
        return
    args = [PY, '-m', 'dev_tools.spec_build', spec]
    if write:
        args.append('--write')
    run(args)
    if write:
        print('')
        print('写完了。要让 GUI 里也能看到这个任务，还得跑一次菜单 7（config_updater）。')


def do_task():
    picked = pick_task()
    if not picked:
        return
    game, task = picked
    boot = ask('先启动游戏吗？[Y/n] ', 'y').lower()
    args = [PY, '-m', 'dev_tools.run_task', task]
    if boot == 'n':
        args.append('--no-boot')
    if game == 'chaoszero':
        # chaoszero 装在另一个模拟器实例上，配置也是单独一份
        args.extend(['--config', 'chaoszero'])
    run(args)


def do_editor():
    bat = os.path.join(ROOT, 'dev_tools', 'serve_spec_editor.bat')
    if not os.path.isfile(bat):
        print('  找不到 %s' % bat)
        return
    print('')
    print('启动编辑器：浏览器会自己打开，关掉那个最小化的服务窗口就结束。')
    os.startfile(bat)


def do_config():
    print('')
    print('重新生成 args.json / menu.json，GUI 里才会出现新注册的任务。')
    run([PY, '-m', 'module.config.config_updater'])


def main():
    # 把 spec 拖到 bat 图标上直接验证，省得进菜单再选一次
    if len(sys.argv) > 1:
        path = clean_path(sys.argv[1])
        if os.path.isfile(path):
            save_last(path)

    while True:
        print('')
        print('=' * 58)
        print(' ALAS 工具箱')
        print('=' * 58)
        print(' 页面卡 → 代码')
        print('   1) 实机验证链条（只看分数，不点击）')
        print('   2) 实机跑链条（真点击）')
        print('   3) 生成代码（只看会生成什么）')
        print('   4) 生成代码（写入并注册任务）')
        print('   5) 打开页面编辑器')
        print(' 任务')
        print('   6) 运行已注册的任务')
        print('   7) 生成 GUI 配置（config_updater）')
        print('   0) 退出')

        choice = ask('选一个 > ')
        if choice == '1':
            do_live(click=False)
        elif choice == '2':
            do_live(click=True)
        elif choice == '3':
            do_build(write=False)
        elif choice == '4':
            do_build(write=True)
        elif choice == '5':
            do_editor()
        elif choice == '6':
            do_task()
        elif choice == '7':
            do_config()
        elif choice == '0':
            return
        else:
            print('  没这个编号')


if __name__ == '__main__':
    main()
