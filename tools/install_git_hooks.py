from __future__ import annotations

import subprocess
from pathlib import Path


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def main() -> None:
    repository = Path(git("rev-parse", "--show-toplevel")).resolve()
    hooks = repository / ".githooks"
    if not hooks.is_dir():
        raise RuntimeError(f"versioned hooks directory is missing: {hooks}")

    git_dir = Path(git("rev-parse", "--git-dir")).resolve()
    common_dir = Path(git("rev-parse", "--git-common-dir")).resolve()
    if git_dir != common_dir:
        for key in ("core.bare", "core.worktree"):
            value = subprocess.run(
                ["git", "config", "--local", "--get", key],
                check=False,
                stdout=subprocess.PIPE,
                text=True,
            ).stdout.strip()
            blocks_worktree_config = (
                key == "core.worktree" and bool(value)
            ) or (
                key == "core.bare" and value.lower() in {"true", "yes", "on", "1"}
            )
            if blocks_worktree_config:
                raise RuntimeError(
                    f"cannot enable worktree-specific hooks while common config contains {key}"
                )
        git("config", "extensions.worktreeConfig", "true")
        git("config", "--worktree", "core.hooksPath", ".githooks")
        scope = "this worktree"
    else:
        git("config", "--local", "core.hooksPath", ".githooks")
        scope = "this repository"

    print(f"Installed .githooks for {scope}: {repository}")


if __name__ == "__main__":
    main()
