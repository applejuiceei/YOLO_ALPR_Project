# YOLO ALPR Project — source release

This branch is the lightweight source release for the Windows and RK3588 ALPR work.
It contains first-party Python/C++/shell sources, PP-OCR research tooling, configuration,
and project documentation.

Large assets are intentionally excluded: models, checkpoints, datasets, videos, generated
runs, captured evidence, offline dependency bundles, archives, and third-party source copies.
Those assets must be distributed separately and must not be committed directly to this branch.

## Large-file guard

The repository enforces a 95 MiB per-blob safety limit, below GitHub's 100 MiB hard limit.
Install the versioned local hooks after cloning or creating a worktree:

```powershell
python tools/install_git_hooks.py
```

Manual checks:

```powershell
python tools/check_git_blob_sizes.py --staged
python tools/check_git_blob_sizes.py --revisions HEAD
```

The pre-commit hook checks staged blobs, the pre-push hook checks every new reachable blob,
and GitHub Actions checks the pushed branch again. The guard rejects oversized blobs; it does
not automatically migrate files to Git LFS.

## Runtime assets

Model and data paths remain configurable in the existing scripts. Supply compatible assets
locally according to the project handoff documents; do not commit credentials or machine-local
secrets.

