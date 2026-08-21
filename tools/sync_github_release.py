from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


EXPECTED_RELEASE_BRANCH = "codex/github-release"
MAX_FILE_SIZE_MIB = 95
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MIB * 1024 * 1024

ALLOWED_SUFFIXES = {
    ".c",
    ".cmake",
    ".cpp",
    ".h",
    ".hpp",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".svg",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

FORBIDDEN_DIRECTORY_NAMES = {
    ".git",
    ".idea",
    ".venv",
    "__pycache__",
    "_publish",
    "blur models",
    "dataset",
    "lpdgan",
    "my_models",
    "offline_bundle",
    "paddlecache",
    "python_deps",
    "python_deps_ocr",
    "third_party",
    "ultralytics",
    "venv",
    "测试图",
}

FORBIDDEN_DIRECTORY_PREFIXES = (
    "captures",
    "python_deps",
    "report_assets",
    "report_render",
    "runs",
)

SENSITIVE_FILE_NAMES = {
    ".env",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "secrets.json",
}

SENSITIVE_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}

SECRET_PATTERNS = (
    ("private key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "credential assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|client[_-]?secret|password|secret|token)\b"
            r"\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{20,}"
        ),
    ),
    (
        "credential in URL",
        re.compile(r"https?://[^\s/:@]+:[^\s/@]+@[^\s]+", re.IGNORECASE),
    ),
)


@dataclass(frozen=True)
class PlannedFile:
    relative_path: Path
    source_path: Path
    destination_path: Path
    size: int
    action: str


def build_parser() -> argparse.ArgumentParser:
    source_root = Path(__file__).resolve().parents[1]
    default_destination = source_root.parent / f"{source_root.name}_GitHubRelease"
    parser = argparse.ArgumentParser(
        description=(
            "按 release_manifest.txt 的白名单，把一方源码安全同步到 "
            "codex/github-release 工作区。默认只预览。"
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="执行复制；不指定时只显示计划，不写入文件。",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=default_destination,
        help=f"发布工作区路径（默认：{default_destination}）。",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=source_root / "release_manifest.txt",
        help="白名单文件路径。",
    )
    return parser


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def normalize_pattern(raw_pattern: str, line_number: int) -> str:
    pattern = raw_pattern.strip().replace("\\", "/")
    if not pattern or pattern.startswith("#"):
        return ""
    if Path(pattern).is_absolute() or re.match(r"^[A-Za-z]:", pattern):
        raise ValueError(f"白名单第 {line_number} 行不能使用绝对路径：{raw_pattern!r}")
    if ".." in Path(pattern).parts:
        raise ValueError(f"白名单第 {line_number} 行不能包含 '..'：{raw_pattern!r}")
    return pattern


def load_manifest(manifest_path: Path, source_root: Path) -> list[str]:
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_file():
        raise FileNotFoundError(f"找不到白名单：{manifest_path}")
    if not is_relative_to(manifest_path, source_root):
        raise ValueError(f"白名单必须位于源项目内：{manifest_path}")

    patterns: list[str] = []
    for line_number, line in enumerate(manifest_path.read_text(encoding="utf-8-sig").splitlines(), 1):
        pattern = normalize_pattern(line, line_number)
        if pattern:
            patterns.append(pattern)
    if not patterns:
        raise ValueError("白名单中没有任何有效规则。")
    return patterns


def path_is_forbidden(relative_path: Path) -> bool:
    lowered_parts = [part.casefold() for part in relative_path.parts[:-1]]
    for part in lowered_parts:
        if part in FORBIDDEN_DIRECTORY_NAMES:
            return True
        if any(part.startswith(prefix) for prefix in FORBIDDEN_DIRECTORY_PREFIXES):
            return True
    return False


def validate_file_path(relative_path: Path, source_path: Path) -> None:
    if source_path.is_symlink():
        raise ValueError(f"不允许同步符号链接：{relative_path.as_posix()}")
    if not source_path.is_file():
        raise ValueError(f"白名单匹配项不是普通文件：{relative_path.as_posix()}")
    if path_is_forbidden(relative_path):
        raise ValueError(f"白名单命中了禁止目录：{relative_path.as_posix()}")

    lowered_name = relative_path.name.casefold()
    lowered_suffix = relative_path.suffix.casefold()
    if (
        lowered_name in SENSITIVE_FILE_NAMES
        or lowered_name.startswith(".env.")
        or lowered_suffix in SENSITIVE_SUFFIXES
        or "credential" in lowered_name
        or "secret" in lowered_name
    ):
        raise ValueError(f"白名单命中了敏感文件名：{relative_path.as_posix()}")
    if lowered_suffix not in ALLOWED_SUFFIXES:
        raise ValueError(
            f"不允许的发布文件类型 {lowered_suffix or '<无扩展名>'}："
            f"{relative_path.as_posix()}"
        )


def scan_for_secrets(relative_path: Path, source_path: Path) -> None:
    raw = source_path.read_bytes()
    if b"\x00" in raw:
        raise ValueError(f"文件疑似二进制，拒绝同步：{relative_path.as_posix()}")
    text = raw.decode("utf-8-sig", errors="replace")
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise ValueError(
                f"敏感信息扫描命中 {label}：{relative_path.as_posix()}；"
                "请人工确认并移除真实凭据。"
            )


def collect_files(source_root: Path, patterns: list[str]) -> list[tuple[Path, Path]]:
    selected: dict[str, tuple[Path, Path]] = {}
    display_by_casefold: dict[str, str] = {}

    for pattern in patterns:
        matches = sorted(source_root.glob(pattern), key=lambda item: item.as_posix().casefold())
        file_matches = [path for path in matches if path.is_file() or path.is_symlink()]
        if not file_matches:
            print(f"[WARN] 白名单规则当前没有匹配文件：{pattern}")
            continue
        for source_path in file_matches:
            resolved_source = source_path.resolve()
            if not is_relative_to(resolved_source, source_root):
                raise ValueError(f"匹配项越出源项目：{source_path}")
            relative_path = source_path.relative_to(source_root)
            validate_file_path(relative_path, source_path)
            key = relative_path.as_posix().casefold()
            previous = display_by_casefold.get(key)
            if previous is not None and previous != relative_path.as_posix():
                raise ValueError(
                    f"Windows 路径大小写冲突：{previous!r} 与 {relative_path.as_posix()!r}"
                )
            display_by_casefold[key] = relative_path.as_posix()
            selected[key] = (relative_path, source_path)

    if not selected:
        raise ValueError("白名单没有匹配到可同步文件。")
    return [selected[key] for key in sorted(selected)]


def git(destination: Path, *args: str) -> str:
    safe_directory = destination.resolve().as_posix()
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={safe_directory}",
            "-C",
            str(destination),
            *args,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} 失败：{message}")
    return completed.stdout.strip()


def validate_destination(destination: Path, source_root: Path, *, require_clean: bool) -> Path:
    destination = destination.resolve()
    if not destination.is_dir():
        raise FileNotFoundError(
            f"发布工作区不存在：{destination}\n"
            "请先用 git worktree add 创建 codex/github-release 工作区。"
        )
    if destination == source_root or is_relative_to(destination, source_root):
        raise ValueError("发布工作区必须独立于原项目目录，不能位于原项目内部。")

    top_level = Path(git(destination, "rev-parse", "--show-toplevel")).resolve()
    if top_level != destination:
        raise ValueError(f"目标不是独立 Git 工作区根目录：{destination}")
    branch = git(destination, "branch", "--show-current")
    if branch != EXPECTED_RELEASE_BRANCH:
        raise ValueError(
            f"目标分支是 {branch or '<detached>'}，要求为 {EXPECTED_RELEASE_BRANCH}；拒绝同步。"
        )
    if require_clean:
        status = git(destination, "status", "--porcelain=v1", "--untracked-files=all")
        if status:
            raise RuntimeError(
                "发布工作区存在未提交更改，拒绝覆盖。请先在 VS Code 中检查、提交或处理：\n"
                f"{status}"
            )
    return destination


def normalized_text_bytes(path: Path) -> bytes:
    """Match the release branch's LF policy without changing source files."""
    raw = path.read_bytes()
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def payload_for_destination(source_path: Path, destination_path: Path) -> bytes:
    normalized = normalized_text_bytes(source_path)
    if destination_path.is_file() and b"\r\n" in destination_path.read_bytes():
        return normalized.replace(b"\n", b"\r\n")
    return normalized


def build_plan(
    source_root: Path,
    destination: Path,
    selected_files: list[tuple[Path, Path]],
) -> list[PlannedFile]:
    plan: list[PlannedFile] = []
    for relative_path, source_path in selected_files:
        size = source_path.stat().st_size
        if size >= MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"文件达到或超过 {MAX_FILE_SIZE_MIB} MiB，拒绝同步："
                f"{relative_path.as_posix()} ({size / (1024 * 1024):.2f} MiB)"
            )
        scan_for_secrets(relative_path, source_path)
        destination_path = (destination / relative_path).resolve()
        if not is_relative_to(destination_path, destination):
            raise ValueError(f"目标路径越出发布工作区：{relative_path.as_posix()}")
        if not destination_path.exists():
            action = "ADD"
        elif not destination_path.is_file() or destination_path.is_symlink():
            raise ValueError(f"目标已有非普通文件，拒绝覆盖：{relative_path.as_posix()}")
        elif normalized_text_bytes(source_path) == normalized_text_bytes(destination_path):
            action = "SAME"
        else:
            action = "UPDATE"
        plan.append(
            PlannedFile(
                relative_path=relative_path,
                source_path=source_path,
                destination_path=destination_path,
                size=size,
                action=action,
            )
        )
    return plan


def print_plan(plan: list[PlannedFile], destination: Path, *, applying: bool) -> None:
    changed = [item for item in plan if item.action != "SAME"]
    total_bytes = sum(item.size for item in plan)
    print(f"源文件：{len(plan)} 个，共 {total_bytes / (1024 * 1024):.2f} MiB")
    print(f"发布工作区：{destination}")
    print(f"目标分支：{EXPECTED_RELEASE_BRANCH}")
    print(f"变更：新增 {sum(item.action == 'ADD' for item in plan)}，"
          f"更新 {sum(item.action == 'UPDATE' for item in plan)}，"
          f"不变 {sum(item.action == 'SAME' for item in plan)}")
    for item in changed:
        print(f"  [{item.action:<6}] {item.relative_path.as_posix()} ({item.size} bytes)")
    if not changed:
        print("没有需要同步的文件。")
    elif not applying:
        print("当前是预览模式；确认后运行同一命令并加 --apply。")


def apply_plan(plan: list[PlannedFile]) -> int:
    changed = [item for item in plan if item.action != "SAME"]
    for item in changed:
        item.destination_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = item.destination_path.with_name(
            f".{item.destination_path.name}.sync-{os.getpid()}.tmp"
        )
        try:
            temporary_path.write_bytes(
                payload_for_destination(item.source_path, item.destination_path)
            )
            shutil.copystat(item.source_path, temporary_path)
            os.replace(temporary_path, item.destination_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
    return len(changed)


def main() -> int:
    args = build_parser().parse_args()
    source_root = Path(__file__).resolve().parents[1]
    try:
        patterns = load_manifest(args.manifest, source_root)
        selected_files = collect_files(source_root, patterns)
        destination = validate_destination(
            args.destination,
            source_root,
            require_clean=args.apply,
        )
        plan = build_plan(source_root, destination, selected_files)
        print_plan(plan, destination, applying=args.apply)
        if not args.apply:
            return 0
        changed_count = apply_plan(plan)
        print(f"同步完成：写入 {changed_count} 个文件；未删除、未暂存、未提交、未推送。")
        if changed_count:
            print(f"下一步请在 VS Code 打开 {destination}，检查源代码管理中的差异后提交。")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
