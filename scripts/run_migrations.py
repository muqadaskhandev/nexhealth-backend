#!/usr/bin/env python3
"""Apply Alembic migrations, recovering from unknown alembic_version stamps.

If the DB was migrated on another branch (e.g. milestones-4 → 0048_review_responses)
and this image's migration history differs, Alembic fails with
\"Can't locate revision identified by ...\". In that case we purge the version
table, stamp to this image's head, then upgrade.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, text=True, capture_output=True)


def main() -> int:
    versions = Path("alembic/versions")
    print("Migration files present:", flush=True)
    if versions.is_dir():
        for p in sorted(versions.glob("*.py")):
            print(f"  - {p.name}", flush=True)
    else:
        print("  (alembic/versions missing!)", flush=True)

    heads = run(["alembic", "heads"])
    sys.stdout.write(heads.stdout)
    sys.stderr.write(heads.stderr)

    upgrade = run(["alembic", "upgrade", "head"])
    sys.stdout.write(upgrade.stdout)
    sys.stderr.write(upgrade.stderr)
    if upgrade.returncode == 0:
        return 0

    err = (upgrade.stdout or "") + (upgrade.stderr or "")
    if "Can't locate revision identified by" not in err:
        return upgrade.returncode

    print(
        "WARNING: DB alembic_version points at a revision not shipped in this image. "
        "Recovering with: alembic stamp --purge head && alembic upgrade head",
        flush=True,
    )
    stamp = run(["alembic", "stamp", "--purge", "head"])
    sys.stdout.write(stamp.stdout)
    sys.stderr.write(stamp.stderr)
    if stamp.returncode != 0:
        return stamp.returncode

    upgrade2 = run(["alembic", "upgrade", "head"])
    sys.stdout.write(upgrade2.stdout)
    sys.stderr.write(upgrade2.stderr)
    return upgrade2.returncode


if __name__ == "__main__":
    raise SystemExit(main())
