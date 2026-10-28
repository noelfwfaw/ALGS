"""
Guard against appearance checks on a Button that has no template on disk.

`appear()`, `appear_then_click()` and the `wait_until_appear/disappear()` family
all end in `Button.match()`, which needs `Button.file`:

    self.image = load_image(self.file, self.area)

A Button declared with plain coordinates and no `file=` (`Button(area=...,
color=(0, 0, 0), button=..., name='TASK_TAB_DAILY')`) therefore dies with

    AttributeError: 'NoneType' object has no attribute 'read'

the moment the check runs - not at import time, and not in any compile or lint
step, because the attribute is only touched when the template is loaded.

That is what killed `LostswordTask` on 2026-10-28 12:54 and stopped the whole
scheduler: the three task panel tabs had been turned into coordinate-only
buttons during a refactor, and the loop still asked `appear(tab, offset=20)`.

Such buttons are legitimate - `device.click()` needs no template at all - so
this check does not forbid them. It only fails when one of them is handed to a
function that has to load an image.

Usage:
    ./toolkit/python.exe -m dev_tools.check_button_templates
    ./toolkit/python.exe -m dev_tools.check_button_templates module/lostsword

Pages:
    none
"""
import ast
import io
import os
import sys

# Importable both as `-m dev_tools.check_button_templates` and as a plain script.
if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Functions of `module/base/base.py` that load `Button.file`. They all take the
# button as their first argument, and all end in `Button.match_template()`.
# `wait_until_still()` is not here on purpose: it compares two screenshots and
# takes a plain area, so it never opens a template.
APPEAR_FUNCS = {
    'appear',
    'appear_then_click',
    'wait_until_appear',
    'wait_until_appear_then_click',
    'wait_until_disappear',
}

# Names whose value is a Button, one level of indirection deep - enough for
# `for name, tab in TASK_TABS:` and for `BOSS_BTN = TABS[0]`-style aliases is
# not attempted: the loop variable is resolved through the container's members.


def iter_py_files(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', 'log')]
        for name in sorted(files):
            if name.endswith('.py'):
                yield os.path.join(base, name)


def button_has_file(node):
    """Whether a `Button(...)` call passes a template, and its name."""
    has_file = False
    name = None
    for keyword in node.keywords:
        if keyword.arg == 'file':
            has_file = keyword.value is not None and not (
                isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
        elif keyword.arg == 'name':
            if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                name = keyword.value.value
    return has_file, name


def collect_buttons(tree, into, containers):
    """
    Record every module level `X = Button(...)` and every container of them.

    Args:
        tree (ast.Module): Parsed file.
        into (dict): name -> has_file, filled in place.
        containers (dict): name -> list of Button names, filled in place.
    """
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) \
                    and value.func.id == 'Button':
                has_file, name = button_has_file(value)
                into[name or target.id] = into.get(name or target.id, True) and has_file
            elif isinstance(value, (ast.Tuple, ast.List)):
                members = []
                for item in value.elts:
                    # ('daily', TASK_TAB_DAILY) or a bare Button(...)
                    if isinstance(item, ast.Name):
                        members.append(item.id)
                    elif isinstance(item, (ast.Tuple, ast.List)):
                        for sub in item.elts:
                            if isinstance(sub, ast.Name):
                                members.append(sub.id)
                            elif isinstance(sub, ast.Call):
                                has_file, name = button_has_file(sub)
                                if name:
                                    into[name] = into.get(name, True) and has_file
                                members.append(name or 'Button')
                if members:
                    containers[target.id] = members


def scan_file(path, buttons, containers):
    """
    Report appearance checks whose argument has no template.

    Args:
        path (str): File to scan.
        buttons (dict): name -> has_file.
        containers (dict): name -> list of Button names.

    Returns:
        list: (lineno, message) pairs.
    """
    try:
        tree = ast.parse(io.open(path, encoding='utf-8').read(), filename=path)
    except SyntaxError as e:
        return [(e.lineno or 0, f'syntax error: {e.msg}')]

    problems = []

    def judge(node, lineno, local):
        if not isinstance(node, ast.Name):
            return
        name = node.id
        candidates = [name]
        if name in local:
            candidates = local[name]
        for candidate in candidates:
            if buttons.get(candidate) is False:
                problems.append((lineno, f'appear*/match* on {candidate} '
                                        f'which has no template file'))
                return

    def judge_call(call, local):
        func = call.func
        name = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else None)
        if name not in APPEAR_FUNCS:
            return
        if not call.args:
            return
        judge(call.args[0], call.lineno, local)

    for node in ast.walk(tree):
        # `for name, tab in TASK_TABS:` binds tab to every member of the tuple.
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Name) \
                and node.iter.id in containers:
            members = containers[node.iter.id]
            targets = node.target.elts if isinstance(node.target, ast.Tuple) else [node.target]
            local = {}
            for target in targets:
                if isinstance(target, ast.Name):
                    local[target.id] = members
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    judge_call(child, local)

        elif isinstance(node, ast.Call):
            judge_call(node, {})

    return problems


def main(argv):
    targets = argv[1:] or [os.path.join('module', d) for d in os.listdir('module')
                           if os.path.isfile(os.path.join('module', d, 'assets.py'))]

    buttons = {}
    containers = {}
    parsed = []
    for target in targets:
        for path in iter_py_files(target):
            try:
                tree = ast.parse(io.open(path, encoding='utf-8').read(), filename=path)
            except SyntaxError as e:
                print(f'FAIL  {path}:{e.lineno} syntax error: {e.msg}')
                continue
            parsed.append((path, tree))
            collect_buttons(tree, buttons, containers)

    nameless = sorted(name for name, has_file in buttons.items() if not has_file)
    print(f'Buttons without a template: {len(nameless)}')
    for name in nameless:
        print(f'      {name}')

    failed = 0
    print('\nAppearance checks on them:')
    for path, _ in parsed:
        for lineno, message in scan_file(path, buttons, containers):
            print(f'FAIL  {path}:{lineno} {message}')
            failed += 1
    if failed == 0:
        print('OK    every appear*/match* call resolves to a button with a template')

    print(f'\n{"PASS" if failed == 0 else "FAILED"}  {failed} problem(s)')
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
