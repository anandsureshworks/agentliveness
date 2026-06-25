"""Static scan for the never-restored-accumulator failure class.

The bug this whole library exists to catch, found *before* it ships: an
attribute seeded as an empty accumulator in ``__init__`` (a counter at ``0``, an
empty ``list``/``dict``/``set``), mutated across calls, but never restored from
persistence. In a long-lived process it works. Under a scheduler — launchd, cron,
a k8s CronJob — **every run is a fresh process**, ``__init__`` runs again, and the
accumulator silently resets every run. The code reads correctly; in-process tests
pass; production is dead and nothing says so.

This is pure static analysis (stdlib ``ast`` only, zero dependencies). It is
advisory: every finding is a *candidate* — review it, then either restore it from
disk (see :class:`agentliveness.PersistentState`) or confirm it's intentionally
per-run.

    agentliveness audit <path>          # scan a file or directory
    agentliveness audit <path> --json   # machine-readable (feeds an empirical scan)
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

# Method calls that grow a container in place.
_MUTATORS = {"append", "add", "update", "extend", "insert", "appendleft", "setdefault"}
# Names/attrs that signal the value was loaded back from persistence.
_LOAD_ATTRS = {"load", "loads", "read", "read_text", "read_bytes"}
_PERSIST_NAMES = {"PersistentState", "json", "pickle", "shelve"}
_SKIP_DIRS = {".venv", "venv", "node_modules", ".git", "__pycache__", "build", ".tox", "dist"}


@dataclass
class Finding:
    file: str
    line: int
    cls: str
    attr: str
    kind: str               # counter | list | dict | set
    accumulated_at: List[int]
    why: str


def _self_attr(node: ast.AST) -> Optional[str]:
    """Return ``X`` if ``node`` is ``self.X``, else None."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
        return node.attr
    return None


def _accum_seed_kind(node: ast.AST) -> Optional[str]:
    """Return the accumulator kind if ``node`` is an empty-accumulator seed."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and not isinstance(node.value, bool) and node.value == 0:
        return "counter"
    if isinstance(node, ast.List) and not node.elts:
        return "list"
    if isinstance(node, ast.Dict) and not node.keys:
        return "dict"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and not node.args and not node.keywords:
        if node.func.id == "set":
            return "set"
        if node.func.id == "list":
            return "list"
        if node.func.id in {"dict", "Counter", "defaultdict", "OrderedDict"}:
            return "dict"
    return None


def _looks_restored(value: ast.AST) -> bool:
    """True if the expression loads state back (json/pickle/PersistentState/.load/.read)."""
    for sub in ast.walk(value):
        if isinstance(sub, ast.Name) and sub.id in _PERSIST_NAMES:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in _LOAD_ATTRS:
            return True
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in _LOAD_ATTRS:
            return True
    return False


def _analyze_class(cls: ast.ClassDef, filename: str, out: List[Finding]) -> None:
    seeds = {}        # attr -> (line, kind)  seeded in __init__
    accum = {}        # attr -> [lines]       grown across the class
    restored = set()  # attr restored from persistence somewhere

    for item in cls.body:
        if isinstance(item, ast.FunctionDef) and item.name == "__init__":
            for n in ast.walk(item):
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        a = _self_attr(t)
                        if a:
                            kind = _accum_seed_kind(n.value)
                            if kind:
                                seeds[a] = (n.lineno, kind)

    for n in ast.walk(cls):
        if isinstance(n, ast.AugAssign):                      # self.X += ...
            a = _self_attr(n.target)
            if a:
                accum.setdefault(a, []).append(n.lineno)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _MUTATORS:
            a = _self_attr(n.func.value)                      # self.X.append(...) etc.
            if a:
                accum.setdefault(a, []).append(n.lineno)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                a = _self_attr(t)
                if a and _looks_restored(n.value):            # self.X = json.load(...) etc.
                    restored.add(a)
                elif a and any(_self_attr(s) == a for s in ast.walk(n.value)):
                    accum.setdefault(a, []).append(n.lineno)  # self.X = self.X + ...
                if isinstance(t, ast.Subscript):              # self.X[k] = v
                    a2 = _self_attr(t.value)
                    if a2:
                        accum.setdefault(a2, []).append(n.lineno)

    for attr, (line, kind) in seeds.items():
        if attr in accum and attr not in restored:
            lines = sorted(set(accum[attr]))
            out.append(Finding(
                file=filename, line=line, cls=cls.name, attr=attr, kind=kind, accumulated_at=lines,
                why=(f"self.{attr} is seeded as an empty {kind} in __init__ and accumulated "
                     f"(line{'s' if len(lines) > 1 else ''} {', '.join(map(str, lines))}), but never "
                     f"restored from persistence. Under a scheduler every run is a fresh process, so it "
                     f"resets to its seed value on every run — the accumulation never persists."),
            ))


def audit_source(source: str, filename: str = "<source>") -> List[Finding]:
    out: List[Finding] = []
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            _analyze_class(node, filename, out)
    return out


def audit_path(path) -> List[Finding]:
    p = Path(path)
    if p.is_file():
        files = [p]
    else:
        files = [f for f in p.rglob("*.py") if not _SKIP_DIRS.intersection(f.parts)]
    out: List[Finding] = []
    for f in files:
        try:
            out += audit_source(f.read_text(encoding="utf-8"), str(f))
        except (OSError, UnicodeDecodeError):
            continue
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="agentliveness",
                                 description="agentliveness — reliability tooling for scheduled/autonomous agents")
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("audit", help="scan for the never-restored-accumulator failure class")
    a.add_argument("path", help="a .py file or a directory to scan")
    a.add_argument("--json", action="store_true", help="machine-readable output")
    a.add_argument("--exit-zero", action="store_true", help="always exit 0 (report only; don't fail CI)")
    args = ap.parse_args(argv)

    if args.cmd != "audit":
        ap.print_help()
        return 2

    findings = audit_path(args.path)
    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
    elif not findings:
        print("✓ no never-restored-accumulator patterns found")
    else:
        for f in findings:
            print(f"\n⚠ {f.file}:{f.line}  {f.cls}.{f.attr}  ({f.kind})")
            print(f"  {f.why}")
        print(f"\n{len(findings)} finding(s) — each is state that looks alive but resets every run. "
              f"Restore it from disk (agentliveness.PersistentState), or confirm it's intentionally per-run.")
    return 0 if (not findings or args.exit_zero) else 1


if __name__ == "__main__":
    sys.exit(main())
