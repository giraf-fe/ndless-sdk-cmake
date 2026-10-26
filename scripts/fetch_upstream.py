#!/usr/bin/env python3
"""
fetch_upstream.py — Explicitly fetch pinned upstream Ndless sources.

CMake itself never downloads anything over the network. This script reads
`upstream.lock.json`, clones the upstream Ndless repository into `upstream/Ndless`
(or a user-supplied `--destination`), checks out the exact pinned commit in
detached-HEAD mode, and initializes only the submodules required to build the SDK.
"""

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any, Dict


def git(*arguments: Any, cwd: Path | None = None) -> None:
    """Run a Git command and raise CalledProcessError if it fails."""
    subprocess.run(["git", *map(str, arguments)], cwd=cwd, check=True)


def load_lockfile(repo_root: Path) -> Dict[str, Any]:
    """Read and parse the upstream repository lockfile (`upstream.lock.json`)."""
    lock_path = repo_root / "upstream.lock.json"
    return json.loads(lock_path.read_text(encoding="utf-8"))


def main() -> None:
    # --------------------------------------------------------------------------
    # Step 1: Parse command-line arguments
    # --------------------------------------------------------------------------
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination",
        type=Path,
        default=repo_root / "upstream" / "Ndless",
        help="Directory where the pinned upstream Ndless checkout will be created",
    )
    args = parser.parse_args()
    destination = args.destination.resolve()

    # --------------------------------------------------------------------------
    # Step 2: Read lockfile and guard against overwriting an existing checkout
    # --------------------------------------------------------------------------
    lock = load_lockfile(repo_root)
    if destination.exists():
        parser.error(
            f"Refusing to overwrite {destination}; "
            "pass a new --destination or use NDLESS_SOURCE_DIR"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------------------
    # Step 3: Clone repository and check out the pinned commit
    # --------------------------------------------------------------------------
    git("clone", "--no-checkout", lock["repository"], destination)
    git("checkout", "--detach", lock["commit"], cwd=destination)

    # --------------------------------------------------------------------------
    # Step 4: Initialize only the required SDK submodules (nspire-io, zlib)
    # --------------------------------------------------------------------------
    git(
        "submodule",
        "update",
        "--init",
        "--recursive",
        "--",
        *lock["submodules"],
        cwd=destination,
    )
    print(f"Pinned upstream ready at {destination}")


if __name__ == "__main__":
    main()
