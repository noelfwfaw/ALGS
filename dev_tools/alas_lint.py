"""
Static checker of the ALAS iron rules (R1 ~ R21).

The skill lists the rules a task module has to follow, but "read the rules and
follow them" ends up with the same handful of violations over and over, because
they are all habits of writing a normal script instead of a state machine. This
turns the habits into mechanical checks, so a rewrite has something objective to
be measured against.

Usage:
    ./toolkit/python.exe -m dev_tools.alas_lint                 # whole repo
    ./toolkit/python.exe -m dev_tools.alas_lint module/lostsword # one package
    ./toolkit/python.exe -m dev_tools.alas_lint --severity high

Severity:
    high    Breaks the state machine, or is known to break on a slow device.
    medium  Works, but drifts away from the framework and will rot.
    low     Style.
"""
import argparse
import ast
import io
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Packages that hold game tasks. The framework itself is allowed to do things a
# task module is not, e.g. sleeping while polling a device.
TASK_PACKAGES = ('module/hazeworld', 'module/lostsword', 'module/browndust')

SEVERITY_ORDER = {'high': 0, 'medium': 1, 'low': 2}

HIGH, MEDIUM, LOW = 'high', 'medium', 'low'

# Both limits are calibrated on the upstream tree rather than guessed, so that
# "like ALAS" means the same thing on both sides of the comparison:
#   7140 functions, median 6 lines, p99 77, 0.8% over 80
#   1824 files, median 84 lines, 2.6% over 500
MAX_METHOD_LINES = 80
MAX_FILE_LINES = 500


def _name(node):
    """Dotted name of a Call/Attribute chain, e.g. `self.device.click`."""
    if isinstance(node, ast.Call):
        return _name(node.func)
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return '%s.%s' % (base, node.attr) if base else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ''


def _kwargs(call):
    out = {}
    for kw in call.keywords:
        out[kw.arg] = kw.value
    return out


def _const(node):
    """
    Value of a literal node, on both AST generations.

    Python 3.8 unified every literal under `ast.Constant`, but this project runs
    on the bundled 3.7 interpreter, where `1`, `'x'` and `True` are still
    `ast.Num`, `ast.Str` and `ast.NameConstant`. Reading only `ast.Constant`
    silently turns the rule into a no-op - `while 1:` never flagged, and an
    `adb_shell(['shell', 'input', 'tap', ...])` never recognised - which is
    worse than not having the rule at all, because the report says "clean".
    """
    if isinstance(node, ast.Constant):
        return node.value
    for cls, attr in (('Num', 'n'), ('Str', 's'), ('NameConstant', 'value')):
        klass = getattr(ast, cls, None)
        if klass is not None and isinstance(node, klass):
            return getattr(node, attr)
    return None


def _const_str(node):
    value = _const(node)
    if isinstance(value, str):
        return value
    return None


def _is_appear_test(test):
    """
    Whether a condition read the screen, so that acting inside its `if` block is
    a judgment. Bounded waits count: `wait_until_appear(..., timeout=n)` polls
    before answering, which is the stronger form of the same judgment.
    """
    for node in ast.walk(test):
        if not isinstance(node, ast.Call):
            continue
        name = _name(node)
        if any(name.endswith(x) for x in (
                '.appear', '.appear_then_click', '.match_template_color',
                '.wait_until_appear', '.wait_until_settled', '.wait_until_still',
                '.ui_page_appear', '.is_in_main', '.image_color_count',
                '.image_color_button', '.ui_loading_appear',
        )):
            return True
        if '.handle_' in name:
            return True
    return False


def _is_raw_appear(test):
    """
    Whether a condition is a single-frame template/colour read.

    Only these are dangerous to negate: on a transition frame nothing matches,
    so `not appear(x)` is true while the screen is merely unknown. A bounded
    wait does not have that problem, which is the whole point of using one.
    """
    for node in ast.walk(test):
        if not isinstance(node, ast.Call):
            continue
        name = _name(node)
        if any(name.endswith(x) for x in (
                '.appear', '.appear_then_click', '.match_template_color',
                '.ui_page_appear', '.is_in_main', '.image_color_count',
                '.image_color_button', '.ui_loading_appear',
        )):
            return True
    return False


def _is_screenshot_call(node):
    return isinstance(node, ast.Call) and _name(node).endswith('.screenshot')


def _is_sleep_call(node):
    return isinstance(node, ast.Call) and _name(node).endswith('.sleep')


def _is_click_call(node):
    return isinstance(node, ast.Call) and _name(node) in (
        'self.device.click', 'device.click', 'self.device.multi_click')


class FunctionChecker:
    """Checks one function/method."""

    def __init__(self, path, func, cls=None):
        self.path = path
        self.func = func
        self.cls = cls
        self.issues = []
        self.name = func.name

    def add(self, severity, rule, line, message):
        self.issues.append((severity, rule, line, message))

    # -- R1 sleep ---------------------------------------------------------
    def check_sleep(self):
        """sleep followed by a screenshot, or sleep between clicks."""
        # Statements of the function, in order, with their enclosing loop.
        flat = []
        in_loop = set()

        def walk(stmts, loop=None):
            for stmt in stmts:
                flat.append(stmt)
                if isinstance(stmt, (ast.While, ast.For)):
                    walk(stmt.body, stmt)
                    walk(stmt.orelse, stmt)
                    if loop:
                        in_loop.add(id(stmt))
                elif isinstance(stmt, ast.If):
                    walk(stmt.body, loop)
                    walk(stmt.orelse, loop)
                elif isinstance(stmt, (ast.Try,)):
                    walk(stmt.body, loop)
                    walk(stmt.orelse, loop)
                    walk(stmt.finalbody, loop)
                if loop is not None:
                    in_loop.add(id(stmt))

        walk(self.func.body)

        for i, stmt in enumerate(flat):
            for node in ast.walk(stmt):
                if not _is_sleep_call(node):
                    continue
                line = node.lineno
                following = flat[i + 1:i + 3]
                # A sleep right before a screenshot is the "wait, then look"
                # habit that state loops exist to remove.
                if any(any(_is_screenshot_call(s) for s in ast.walk(f)) for f in following):
                    self.add(HIGH, 'R1', line,
                             'sleep() then screenshot() - wait on a state instead')
                elif any(any(_is_click_call(s) for s in ast.walk(f)) for f in following):
                    self.add(HIGH, 'R1', line,
                             'sleep() then click() - the click has no judgment')
                elif id(stmt) in in_loop:
                    self.add(MEDIUM, 'R1', line,
                             'sleep() inside a loop - the loop already polls, use a Timer')
                else:
                    self.add(MEDIUM, 'R1', line,
                             'sleep() - make sure nothing on screen can be waited on')

    # -- R2/R3 while 1 ----------------------------------------------------
    def check_while(self):
        for node in ast.walk(self.func):
            if isinstance(node, ast.While):
                if _const(node.test) not in (1, True):
                    continue
                # `while 1:` is how ALAS itself writes a wait: 336 of them
                # upstream, in 4.7% of all functions, and 58% carry no timer at
                # all - the bound is the screen, not the clock. So this is a
                # hint, not a violation. What would be a bug is a loop that
                # never reads the screen, and that is reported below.
                if not self._loop_reads_screen(node):
                    self.add(HIGH, 'R2', node.lineno,
                             'while 1: whose body calls nothing - no frame can '
                             'change, so the loop spins on the last screenshot '
                             'until the whole task is killed')
                else:
                    self.add(LOW, 'R2', node.lineno,
                             'hint: `while 1:` is fine for a popup drain; use '
                             '`for _ in self.loop(timeout=...)` when the wait has '
                             'a clock behind it')

    @staticmethod
    def _loop_reads_screen(node):
        """
        Whether the loop can see the screen at all.

        The loop body almost always delegates the read to a task method
        (`exercise_start()` screenshots on its own), so a literal search for
        `screenshot` is too narrow. What is certainly a bug is a loop that calls
        nothing: `while 1: pass` or a counter that no frame can change.
        """
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                return True
        return False

    # -- R5 negative condition --------------------------------------------
    def check_negative(self):
        for node in ast.walk(self.func):
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
                if isinstance(node.operand, ast.Call) and _is_raw_appear(node.operand):
                    self.add(HIGH, 'R5', node.lineno,
                             'negative condition - a transition frame matches nothing, '
                             'so `not appear` is true whenever the screen is unknown')

    # -- R6 operation as exit ---------------------------------------------
    def check_exit(self):
        # `return True` inside a `handle_xxx()` handler is the contract with the
        # caller (`if self.handle_x(): continue`), not a loop exit, so these
        # rules only apply to functions that own a loop.
        if not any(isinstance(n, (ast.While, ast.For)) for n in ast.walk(self.func)):
            return

        for node in ast.walk(self.func):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if not (isinstance(test, ast.Call) and _is_appear_test(test)):
                continue
            name = _name(test)
            breaks = any(isinstance(s, (ast.Break, ast.Return)) for s in node.body)
            if not breaks:
                continue
            if name.endswith('.appear_then_click'):
                self.add(HIGH, 'R6', node.lineno,
                         'exit on appear_then_click() - the click itself is outside '
                         'the loop and is never retried')
            elif '.handle_' in name:
                self.add(HIGH, 'R6', node.lineno,
                         'exit on handle_xxx() - same, handle it then `continue`')
            kw = _kwargs(test)
            if 'interval' in kw:
                self.add(HIGH, 'R4', node.lineno,
                         'exit condition has interval= - interval returns False while '
                         'cooling down, so the loop never exits')

    # -- R4/R13 clicks ----------------------------------------------------
    def check_clicks(self):
        """Every click needs a judgment, and every appear_then_click an interval."""
        guarded = set()
        for node in ast.walk(self.func):
            if isinstance(node, ast.If) and _is_appear_test(node.test):
                for s in ast.walk(node):
                    guarded.add(id(s))

        for node in ast.walk(self.func):
            if isinstance(node, ast.Call) and _name(node).endswith('.appear_then_click'):
                kw = _kwargs(node)
                if 'interval' not in kw:
                    self.add(HIGH, 'R4', node.lineno,
                             'appear_then_click() without interval - it would fire on '
                             'every frame')
            if _is_click_call(node):
                if id(node) not in guarded:
                    self.add(HIGH, 'R13', node.lineno,
                             'device.click() with no appear() guard - the click is '
                             'never retried and never verified')

    # -- R12 hardcoded coordinates ----------------------------------------
    def check_hardcode(self):
        for node in ast.walk(self.func):
            if isinstance(node, ast.Call) and _name(node).endswith('.adb_shell'):
                for arg in node.args:
                    text = ''
                    if isinstance(arg, ast.List):
                        text = ' '.join(str(_const_str(e)) for e in arg.elts)
                    if 'tap' in text:
                        self.add(HIGH, 'R12', node.lineno,
                                 'adb_shell input tap - put the point into assets.py '
                                 'and click the Button')
            if isinstance(node, ast.Call) and _name(node) in ('Button', 'ClickButton'):
                # Building a button from a point computed at runtime is how the
                # framework itself clicks a matched position, so only the module
                # level constants below are flagged.
                pass

    # -- R7 nested loops ---------------------------------------------------
    def check_nested(self):
        def depth(node, d=0):
            best = d
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.While, ast.For)):
                    best = max(best, depth(child, d + 1))
                else:
                    best = max(best, depth(child, d))
            return best

        loops = [n for n in ast.walk(self.func) if isinstance(n, (ast.While, ast.For))]
        for loop in loops:
            if depth(loop) >= 2:
                self.add(MEDIUM, 'R7', loop.lineno,
                         'nested loop - the inner loop swallows the state of the outer one')
                break

    # -- R10 size / docstring ---------------------------------------------
    def check_doc(self):
        if self.name.startswith('__'):
            return
        doc = ast.get_docstring(self.func)
        start = self.func.lineno
        end = getattr(self.func, 'end_lineno', None)
        if end is None:
            # python 3.7 has no end_lineno, take the deepest line of the body
            end = max([start] + [n.lineno for n in ast.walk(self.func)
                                 if hasattr(n, 'lineno')])
        length = end - start
        # Calibrated on the upstream tree: 7140 functions, median 6 lines, p99
        # 77, and only 0.8% go past 80. A method longer than 80 lines is as rare
        # there as it should be here, so that is the limit - not "one screen",
        # which would be stricter than the codebase this project imitates.
        if length > MAX_METHOD_LINES:
            self.add(MEDIUM, 'R10', start,
                     'method is %d lines, keep it under %d' % (length, MAX_METHOD_LINES))
        if doc is None:
            self.add(LOW, 'R10', self.func.lineno, 'missing docstring')
            return
        # A state loop should say which page it starts and ends on.
        if any(isinstance(n, (ast.While, ast.For)) for n in ast.walk(self.func)):
            if 'Pages:' not in doc and self.name != 'run':
                self.add(LOW, 'R10', self.func.lineno,
                         'hint: a loop that walks from one page to another reads '
                         'better with `Pages: in/out`')

    def run(self):
        self.check_sleep()
        self.check_while()
        self.check_negative()
        self.check_exit()
        self.check_clicks()
        self.check_hardcode()
        self.check_nested()
        self.check_doc()
        return self.issues


class FileChecker:
    def __init__(self, path, is_task_package):
        self.path = path
        self.is_task_package = is_task_package
        self.issues = []
        with io.open(path, encoding='utf-8') as f:
            self.source = f.read()
        self.tree = ast.parse(self.source, filename=path)
        self.lines = self.source.split('\n')

    def suppressed(self, lineno):
        """
        A rule may be waived on one line with a trailing `# alas-lint: allow`
        and a comment saying why. The point is that a sleep which really has
        nothing to wait on is a rare, argued exception, not a habit.

        The marker is looked for on the whole statement, not on the reported
        line: a call that wraps its arguments puts the closing bracket - and
        therefore the only place a comment can go - one or two lines below the
        name `adb_shell(...)` the violation is reported against.
        """
        if not (1 <= lineno <= len(self.lines)):
            return False
        for line in self.lines[lineno - 1:self._statement_end(lineno)]:
            if 'alas-lint: allow' in line:
                return True
        return False

    def _statement_end(self, lineno):
        """Last line of the statement starting at `lineno`, by bracket depth."""
        depth = 0
        for index in range(lineno - 1, len(self.lines)):
            for char in self.lines[index]:
                if char in '([{':
                    depth += 1
                elif char in ')]}':
                    depth -= 1
            continued = self.lines[index].rstrip().endswith(('\\', ',', '(', '[', '{'))
            if depth <= 0 and not continued:
                return index + 2
        return len(self.lines)

    def check_size(self):
        lines = self.source.count('\n') + 1
        if self.is_task_package and lines > MAX_FILE_LINES:
            self.issues.append((MEDIUM, 'R10', 1,
                                'file is %d lines, split it at %d' % (lines, MAX_FILE_LINES)))

    def check_run_task_delay(self):
        """A task entry point has to schedule itself, or the scheduler loops on it."""
        if not self.is_task_package:
            return
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for func in node.body:
                if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if func.name != 'run':
                    continue
                scheduled = False
                for sub in ast.walk(func):
                    if isinstance(sub, ast.Call):
                        name = _name(sub)
                        if name.endswith(('.task_delay', '.task_stop', '.task_call')):
                            scheduled = True
                            break
                        # This project puts the delay of every task into a
                        # `<task>_delay()` helper, because the interval often
                        # depends on what the run found. Following the helper is
                        # enough - what matters is that the task reschedules.
                        if name.endswith('_delay') and not name.endswith('.task_delay'):
                            scheduled = True
                            break
                if scheduled:
                    continue
                self.issues.append((MEDIUM, 'R8.2', func.lineno,
                                    'run() does not schedule itself with task_delay()'))

    def check_module_button(self):
        """
        A module level `Button(...)` is a hand written asset.

        assets.py is generated from the screenshots by button_extract, so a
        button declared next to the task drifts away from the picture as soon
        as the game is patched, and nothing regenerates it.
        """
        # assets.py is where the generated buttons live, that is the point.
        if os.path.basename(self.path) == 'assets.py':
            return

        for node in self.tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for value in ast.walk(node.value):
                if isinstance(value, ast.Call) and _name(value) in ('Button', 'ClickButton'):
                    self.issues.append((HIGH, 'R9', node.lineno,
                                        'Button(...) declared in code - assets.py is '
                                        'generated, add the asset and run button_extract'))

    def check_chinese(self):
        """One line per file: a translated file has no Chinese left."""
        hits = []
        for i, line in enumerate(self.lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            if any('\u4e00' <= ch <= '\u9fff' for ch in stripped):
                if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
                    hits.append(i)
        if hits:
            self.issues.append((LOW, 'R10', hits[0],
                                'hint: %d line(s) of Chinese in comments - fine where it '
                                'carries a measured game observation, worth translating '
                                'where it only restates the code (first at L%d)'
                                % (len(hits), hits[0])))

    def run(self):
        self.check_size()
        self.check_module_button()
        self.check_run_task_delay()
        if self.is_task_package:
            self.check_chinese()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                for func in node.body:
                    if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.issues.extend(FunctionChecker(self.path, func, node).run())
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.issues.extend(FunctionChecker(self.path, node).run())

        self.issues = [x for x in self.issues if not self.suppressed(x[2])]
        seen = set()
        unique = []
        for issue in self.issues:
            key = (issue[0], issue[1], issue[2], issue[3])
            if key in seen:
                continue
            seen.add(key)
            unique.append(issue)
        return unique


def iter_python_files(targets):
    for target in targets:
        target = os.path.normpath(target)
        if os.path.isfile(target):
            if target.endswith('.py'):
                yield target
            continue
        for root, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', 'toolkit', 'submodule')]
            for f in files:
                if f.endswith('.py'):
                    yield os.path.join(root, f)


def main():
    parser = argparse.ArgumentParser(description='ALAS iron rule checker')
    parser.add_argument('targets', nargs='*', default=None,
                        help='Files or directories, defaults to the game packages')
    parser.add_argument('--severity', default='low', choices=['high', 'medium', 'low'])
    parser.add_argument('--all', action='store_true', help='Check the whole repo')
    args = parser.parse_args()

    if args.targets:
        targets = args.targets
    elif args.all:
        targets = ['module']
    else:
        targets = list(TASK_PACKAGES)

    files = sorted(iter_python_files(targets))
    if not files:
        print('No python file matched')
        return 1

    limit = SEVERITY_ORDER[args.severity]
    all_issues = {}
    counts = {HIGH: 0, MEDIUM: 0, LOW: 0}
    for path in files:
        rel = os.path.relpath(path, ROOT).replace('\\', '/')
        is_task = any(rel.startswith(p) for p in TASK_PACKAGES)
        checker = FileChecker(path, is_task)
        issues = [x for x in checker.run() if SEVERITY_ORDER[x[0]] <= limit]
        if issues:
            all_issues[rel] = sorted(issues, key=lambda x: (SEVERITY_ORDER[x[0]], x[2]))
            for sev, _, _, _ in issues:
                counts[sev] += 1

    for rel in sorted(all_issues):
        print('\n%s' % rel)
        for sev, rule, line, msg in all_issues[rel]:
            print('  %-6s %-5s L%-5d %s' % (sev, rule, line, msg))

    print('\n%d file(s), %d high, %d medium, %d low'
          % (len(all_issues), counts[HIGH], counts[MEDIUM], counts[LOW]))
    print('  high   = bites at runtime, fails the check\n'
          '  medium = structure or docstring of a task entry point\n'
          '  low    = hints, ignored by the exit code')
    return 1 if counts[HIGH] else 0


if __name__ == '__main__':
    sys.exit(main())
