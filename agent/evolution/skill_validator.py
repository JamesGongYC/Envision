"""Seven-stage validation for mutated detection skill source."""
from __future__ import annotations

import ast
import os
import re
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import psycopg
from psycopg import Connection

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_LIB = REPO_ROOT / "agent" / "lib"
for p in (str(REPO_ROOT), str(AGENT_LIB)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent.evolution.backtest_connection import BacktestConnection  # noqa: E402
from agent.evolution.backtest_harness import _blocked_execute  # noqa: E402
from agent.evolution.skill_loader import load_run_from_source  # noqa: E402

SPAM_MULTIPLIER = 5
SPAM_ABSOLUTE_CAP = 50
_BACKTEST_ENV = "ENVISION_BACKTEST"

_BANNED_IMPORT_ROOTS = frozenset({
    "subprocess",
    "socket",
    "ctypes",
    "pickle",
    "http",
    "urllib",
    "ftplib",
    "telnetlib",
})

_BANNED_CALLS = frozenset({
    "eval",
    "exec",
    "__import__",
    "compile",
    "open",
    "input",
})

_BANNED_ATTR_CALLS = frozenset({
    "emit_forecasts",
    "system",
    "popen",
})

_ALLOWED_IMPORT_ROOTS = frozenset({
    "ast",
    "argparse",
    "collections",
    "dataclasses",
    "datetime",
    "json",
    "math",
    "os",
    "pathlib",
    "re",
    "sys",
    "typing",
    "uuid",
    "psycopg",
    "shapely",
    "sklearn",
    "numpy",
    "trace_builder",
    "reasoning_llm",
    "reasoning_prompts",
    "forecast_model",
    "forecast_writer",
    "signal_temporal",
    "agent",
})

_WRITE_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE)\s+INTO\b",
    re.IGNORECASE,
)

_SOURCE_EQ = re.compile(
    r"""source\s*=\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
_SIGNAL_TYPE_EQ = re.compile(
    r"""signal_type\s*=\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
_SOURCE_LIKE = re.compile(
    r"""source\s+LIKE\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)


@dataclass
class ValidationReport:
    accepted: bool
    stages: list[dict[str, Any]] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    sandbox_traceback: str | None = None


def _stage(
    report: ValidationReport,
    name: str,
    *,
    passed: bool,
    detail: str = "",
    reason: str | None = None,
) -> bool:
    report.stages.append({"stage": name, "passed": passed, "detail": detail})
    if not passed and reason:
        report.rejection_reasons.append(reason)
    return passed


def validate_python(source: str) -> tuple[bool, list[str]]:
    try:
        ast.parse(source)
        return True, []
    except SyntaxError as e:
        return False, [str(e)]


def _strip_docstrings(node: ast.AST) -> ast.AST:
    for child in ast.walk(node):
        if isinstance(
            child,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module),
        ):
            child.body = [
                n
                for n in child.body
                if not (
                    isinstance(n, ast.Expr)
                    and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str)
                )
            ]
    return node


def normalized_ast_dump(source: str) -> str:
    tree = ast.parse(source)
    tree = _strip_docstrings(tree)
    return ast.dump(tree, annotate_fields=False)


def is_no_op(parent: str, candidate: str) -> bool:
    if parent.strip() == candidate.strip():
        return True
    try:
        return normalized_ast_dump(parent) == normalized_ast_dump(candidate)
    except SyntaxError:
        return parent.strip() == candidate.strip()


def check_signature_lock(source: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return False, str(e)

    run_def = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            run_def = node
            break

    if run_def is None:
        return False, "missing top-level run(now, db)"

    if len(run_def.args.args) != 2:
        return False, "run() must have exactly two parameters (now, db)"

    param_names = [a.arg for a in run_def.args.args]
    if param_names != ["now", "db"]:
        return False, f"run() parameters must be (now, db), got {param_names}"

    ret = run_def.returns
    if ret is None:
        return False, "run() missing return annotation"

    ret_src = ast.unparse(ret) if hasattr(ast, "unparse") else ""
    if "Forecast" not in ret_src and "list" not in ret_src.lower():
        return False, f"run() return must be list[Forecast], got {ret_src!r}"

    return True, ""


def check_no_persistence(source: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return False, str(e)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr

            if name in _BANNED_ATTR_CALLS:
                return False, f"banned call: {name}()"

            if name == "execute" or name == "executemany":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if _WRITE_SQL.search(arg.value):
                            return False, "SQL write in execute()"
                for kw in node.keywords:
                    if kw.arg == "query" and isinstance(kw.value, ast.Constant):
                        if isinstance(kw.value.value, str) and _WRITE_SQL.search(
                            kw.value.value
                        ):
                            return False, "SQL write in execute(query=...)"

    if re.search(r"\bemit_forecasts\s*\(", source):
        return False, "emit_forecasts() not allowed in skill"
    if re.search(r"\bforecast_writer\b", source) and "import" in source:
        if "from forecast_writer" in source or "import forecast_writer" in source:
            if "emit_forecasts" in source:
                return False, "forecast_writer persistence not allowed"

    return True, ""


def _inventory_pairs(
    inventory: set[tuple[str, str]],
) -> tuple[set[tuple[str, str]], bool]:
    has_firms = any(src.startswith("firms") for src, _ in inventory)
    return inventory, has_firms


def check_signal_catalog(
    source: str,
    inventory: set[tuple[str, str]],
) -> tuple[bool, str]:
    inv, has_firms = _inventory_pairs(inventory)
    sources = set(_SOURCE_EQ.findall(source))
    sources.update(m.group(1).rstrip("%") for m in _SOURCE_LIKE.finditer(source))
    types = set(_SIGNAL_TYPE_EQ.findall(source))

    for src in sources:
        if src.endswith("%") or "%" in src:
            prefix = src.replace("%", "")
            if prefix == "firms" and has_firms:
                continue
            if not any(s.startswith(prefix) for s, _ in inv):
                return False, f"unknown source pattern: {src!r}"
            continue
        if not any(s == src or s.startswith(src) for s, _ in inv):
            return False, f"unknown source: {src!r}"

    for sig_type in types:
        if not any(t == sig_type for _, t in inv):
            return False, f"unknown signal_type: {sig_type!r}"

    return True, ""


def check_import_allowlist(source: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return False, str(e)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _BANNED_IMPORT_ROOTS:
                    return False, f"banned import: {alias.name}"
                if root not in _ALLOWED_IMPORT_ROOTS and not root.startswith(
                    ("agent",)
                ):
                    return False, f"import not allowlisted: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in _BANNED_IMPORT_ROOTS:
                    return False, f"banned import from: {node.module}"
                if root not in _ALLOWED_IMPORT_ROOTS and not root.startswith(
                    ("agent",)
                ):
                    return False, f"import not allowlisted: {node.module}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in _BANNED_CALLS:
                    return False, f"banned call: {node.func.id}()"
            if isinstance(node.func, ast.Attribute) and node.func.attr == "system":
                return False, "os.system() not allowed"

    if re.search(r"^\s*import\s+subprocess\b", source, re.MULTILINE):
        return False, "import subprocess"
    if re.search(r"^\s*from\s+subprocess\b", source, re.MULTILINE):
        return False, "from subprocess"

    return True, ""


def _pick_smoke_time(db: Connection, now: datetime) -> datetime:
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT MAX(timestamp) FROM signals
            WHERE timestamp <= %s
              AND timestamp > %s - interval '24 hours'
            """,
            (now, now),
        )
        row = cur.fetchone()
    if row and row[0]:
        ts = row[0]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    return now - timedelta(hours=1)


def _looks_like_forecast(obj: Any) -> bool:
    return hasattr(obj, "probability") and hasattr(obj, "geometry")


def sandbox_smoke_run(
    parent_source: str,
    candidate_source: str,
    skill_id: str,
    db: Connection,
    now: datetime,
) -> tuple[bool, str, str | None]:
    t = _pick_smoke_time(db, now)
    prev_bt = os.environ.get(_BACKTEST_ENV)
    os.environ[_BACKTEST_ENV] = "1"
    tb: str | None = None
    try:
        parent_run = load_run_from_source(parent_source, f"{skill_id}_parent")
        candidate_run = load_run_from_source(candidate_source, skill_id)

        with patch.object(psycopg.Cursor, "execute", _blocked_execute):
            db_parent = BacktestConnection(db, skill_id, t)
            db_cand = BacktestConnection(db, skill_id, t)
            parent_out = parent_run(t, db_parent)
            parent_n = len(parent_out) if parent_out else 0
            candidate_out = candidate_run(t, db_cand)

        if not isinstance(candidate_out, list):
            return False, "run() must return a list", None

        for item in candidate_out:
            if not _looks_like_forecast(item):
                return False, "forecast items need probability and geometry", None

        cap = max(SPAM_ABSOLUTE_CAP, SPAM_MULTIPLIER * max(1, parent_n))
        if len(candidate_out) > cap:
            return (
                False,
                f"forecast spam: {len(candidate_out)} > {cap} "
                f"(parent emitted {parent_n})",
                None,
            )
        return True, f"emitted {len(candidate_out)} at t={t.isoformat()}", None
    except Exception:
        tb = traceback.format_exc()
        return False, "runtime error in sandbox", tb
    finally:
        if prev_bt is None:
            os.environ.pop(_BACKTEST_ENV, None)
        else:
            os.environ[_BACKTEST_ENV] = prev_bt


def validate_candidate(
    candidate_source: str,
    parent_source: str,
    skill_id: str,
    inventory: set[tuple[str, str]],
    db: Connection,
    now: datetime,
    *,
    run_sandbox: bool = True,
) -> ValidationReport:
    """Run stages 1–7 in cost order; stop at first failure."""
    report = ValidationReport(accepted=False)

    ok, errs = validate_python(candidate_source)
    if not _stage(
        report,
        "ast_parse",
        passed=ok,
        detail="; ".join(errs) if errs else "ok",
        reason=f"ast_parse: {errs[0]}" if errs else None,
    ):
        return report

    ok, detail = check_signature_lock(candidate_source)
    if not _stage(
        report,
        "signature_lock",
        passed=ok,
        detail=detail or "ok",
        reason=f"signature_lock: {detail}" if not ok else None,
    ):
        return report

    if is_no_op(parent_source, candidate_source):
        _stage(
            report,
            "no_op",
            passed=False,
            detail="candidate identical to parent",
            reason="no_op: candidate identical to parent",
        )
        return report
    _stage(report, "no_op", passed=True, detail="differs from parent")

    ok, detail = check_no_persistence(candidate_source)
    if not _stage(
        report,
        "no_persistence",
        passed=ok,
        detail=detail or "ok",
        reason=f"no_persistence: {detail}" if not ok else None,
    ):
        return report

    ok, detail = check_signal_catalog(candidate_source, inventory)
    if not _stage(
        report,
        "signal_catalog",
        passed=ok,
        detail=detail or "ok",
        reason=f"signal_catalog: {detail}" if not ok else None,
    ):
        return report

    ok, detail = check_import_allowlist(candidate_source)
    if not _stage(
        report,
        "import_allowlist",
        passed=ok,
        detail=detail or "ok",
        reason=f"import_allowlist: {detail}" if not ok else None,
    ):
        return report

    if not run_sandbox:
        report.accepted = True
        return report

    ok, detail, tb = sandbox_smoke_run(
        parent_source, candidate_source, skill_id, db, now
    )
    report.sandbox_traceback = tb
    if not _stage(
        report,
        "sandbox",
        passed=ok,
        detail=detail if ok else (tb or detail),
        reason=f"sandbox: {detail}" if not ok else None,
    ):
        return report

    report.accepted = True
    return report
