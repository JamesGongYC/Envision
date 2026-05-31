#!/usr/bin/env python3
"""Sync repo skill directories to flat Hermes runtime (~/.hermes/skills/).

Walks agent/skills/ for directories containing SKILL.md and rsyncs each to
~/.hermes/skills/<skill_id>/.

Default is dry-run. Use --apply to copy; --prune with --apply removes
runtime skill dirs not present in the repo.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / "agent" / "skills"
AGENT_LIB = REPO_ROOT / "agent" / "lib"
RUNTIME_ROOT = Path(os.path.expanduser("~/.hermes/skills"))

RSYNC_EXCLUDES = [
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    ".DS_Store",
]


def discover_repo_skills() -> dict[str, Path]:
    """Map skill_id -> repo directory path. Abort on duplicate skill_id."""
    found: dict[str, Path] = {}
    collisions: list[tuple[str, Path, Path]] = []

    if not SKILLS_ROOT.is_dir():
        print(f"Skills root not found: {SKILLS_ROOT}", file=sys.stderr)
        sys.exit(1)

    for skill_md in SKILLS_ROOT.rglob("SKILL.md"):
        skill_dir = skill_md.parent
        skill_id = skill_dir.name
        if skill_id in found:
            collisions.append((skill_id, found[skill_id], skill_dir))
        else:
            found[skill_id] = skill_dir

    if collisions:
        print("ERROR: duplicate skill_id in repo:", file=sys.stderr)
        for skill_id, a, b in collisions:
            print(f"  {skill_id}:", file=sys.stderr)
            print(f"    {a}", file=sys.stderr)
            print(f"    {b}", file=sys.stderr)
        sys.exit(1)

    return found


def list_runtime_skills() -> set[str]:
    if not RUNTIME_ROOT.is_dir():
        return set()
    return {p.name for p in RUNTIME_ROOT.iterdir() if p.is_dir()}


def rsync_available() -> bool:
    return shutil.which("rsync") is not None


def should_exclude(rel: Path) -> bool:
    if rel.name == ".DS_Store" or rel.suffix == ".pyc":
        return True
    return any(part in ("__pycache__", ".pytest_cache") for part in rel.parts)


def iter_skill_files(src: Path) -> list[Path]:
    files: list[Path] = []
    for path in src.rglob("*"):
        if path.is_file():
            rel = path.relative_to(src)
            if not should_exclude(rel):
                files.append(rel)
    return sorted(files)


def shutil_sync_skill(src: Path, dst: Path, *, dry_run: bool) -> None:
    """Fallback when rsync is unavailable (e.g. Windows without Git rsync)."""
    src_files = {rel: src / rel for rel in iter_skill_files(src)}
    dst_files: dict[Path, Path] = {}
    if dst.is_dir():
        for rel in iter_skill_files(dst):
            dst_files[rel] = dst / rel

    for rel in sorted(set(src_files) | set(dst_files)):
        s = src_files.get(rel)
        d = dst_files.get(rel)
        if s and not d:
            print(f"      + {rel}")
            if not dry_run:
                target = dst / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, target)
        elif s and d:
            if s.stat().st_size != d.stat().st_size or int(s.stat().st_mtime) != int(d.stat().st_mtime):
                print(f"      ~ {rel}")
                if not dry_run:
                    shutil.copy2(s, d)
        elif d and not s:
            print(f"      - {rel}")
            if not dry_run:
                d.unlink()


def is_detect_skill(src: Path) -> bool:
    try:
        src.relative_to(SKILLS_ROOT)
    except ValueError:
        return False
    return "detect" in src.parts


def copy_trace_builder(dst: Path, *, dry_run: bool) -> None:
    """Copy agent/lib/trace_builder.py into skill scripts/ for Hermes runtime."""
    lib_file = AGENT_LIB / "trace_builder.py"
    if not lib_file.is_file():
        print(f"      ! trace_builder.py missing at {lib_file}", file=sys.stderr)
        return
    scripts = dst / "scripts"
    if not scripts.is_dir():
        return
    target = scripts / "trace_builder.py"
    rel = Path("scripts") / "trace_builder.py"
    if dry_run:
        print(f"      + {rel} (from agent/lib)")
        return
    shutil.copy2(lib_file, target)


def rsync_skill(src: Path, dst: Path, *, dry_run: bool) -> subprocess.CompletedProcess:
    cmd = ["rsync", "-av", "--delete"]
    for exc in RSYNC_EXCLUDES:
        cmd.extend(["--exclude", exc])
    if dry_run:
        cmd.append("--dry-run")
    cmd.extend([str(src) + "/", str(dst) + "/"])
    return subprocess.run(cmd, capture_output=True, text=True)


def sync_skills(*, apply: bool, prune: bool) -> int:
    repo_skills = discover_repo_skills()
    runtime_skills = list_runtime_skills()
    dry_run = not apply

    mode = "DRY RUN" if dry_run else "APPLY"
    print(f"sync_skills.py — {mode}")
    print(f"  repo:    {SKILLS_ROOT}")
    print(f"  runtime: {RUNTIME_ROOT}")
    print()

    if not repo_skills:
        print("No skills found in repo.")
        return 0

    use_rsync = rsync_available()
    if not use_rsync:
        print("NOTE: rsync not on PATH; using Python shutil fallback.", file=sys.stderr)
        print()

    for skill_id in sorted(repo_skills):
        src = repo_skills[skill_id]
        dst = RUNTIME_ROOT / skill_id
        action = "would sync" if dry_run else "syncing"
        print(f"  {action}: {skill_id}")
        print(f"    {src} -> {dst}")
        if use_rsync:
            result = rsync_skill(src, dst, dry_run=dry_run)
            if result.stdout.strip():
                for line in result.stdout.strip().splitlines():
                    print(f"      {line}")
            if result.returncode != 0:
                print(result.stderr, file=sys.stderr)
                return result.returncode
            if is_detect_skill(src):
                copy_trace_builder(dst, dry_run=dry_run)
        else:
            if not dry_run:
                dst.mkdir(parents=True, exist_ok=True)
            shutil_sync_skill(src, dst, dry_run=dry_run)
            # Remove dst files not in src (--delete)
            if dst.is_dir():
                for rel in iter_skill_files(dst):
                    if rel not in {r for r in iter_skill_files(src)}:
                        print(f"      - {rel}")
                        if not dry_run:
                            (dst / rel).unlink()

        if is_detect_skill(src):
            copy_trace_builder(dst, dry_run=dry_run)

    orphans = sorted(runtime_skills - set(repo_skills.keys()))
    if orphans:
        print()
        print("Runtime orphans (not in repo):")
        for skill_id in orphans:
            print(f"  {skill_id}  ({RUNTIME_ROOT / skill_id})")
        if prune and apply:
            print()
            print("Pruning orphans:")
            for skill_id in orphans:
                path = RUNTIME_ROOT / skill_id
                print(f"  removing {path}")
                shutil.rmtree(path)
        elif prune and not apply:
            print("  (use --apply --prune to delete)")
    else:
        print()
        print("No runtime orphans.")

    print()
    if dry_run:
        print("Dry run complete. Re-run with --apply to sync.")
    else:
        print("Sync complete.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync agent/skills to ~/.hermes/skills/")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform sync (default is dry-run)",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="With --apply, delete runtime skill dirs not in repo",
    )
    args = parser.parse_args()
    if args.prune and not args.apply:
        print("WARNING: --prune has no effect without --apply", file=sys.stderr)
    return sync_skills(apply=args.apply, prune=args.prune)


if __name__ == "__main__":
    sys.exit(main())
