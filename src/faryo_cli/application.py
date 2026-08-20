"""Versioned Faryo application and private-venv installation."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

from faryo_cli import __version__
from faryo_cli.diagnostics import Layout
from faryo_cli.installer import atomic_write
from faryo_cli.operations import OperationError


BUILD_REQUIREMENTS = ("setuptools==83.0.0", "wheel==0.47.0")
VERSION_RE = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:\.(?:dev|rc)[0-9]+)?$")


@dataclass(frozen=True)
class ProgramLayout:
    root: Path
    versions: Path
    current: Path
    state: Path
    bin_path: Path

    @classmethod
    def from_layout(cls, layout: Layout) -> "ProgramLayout":
        root = Path(os.environ.get("FARYO_PROGRAM_HOME") or layout.home / ".local/share/faryo").expanduser()
        return cls(
            root=root,
            versions=root / "versions",
            current=root / "current",
            state=root / "state",
            bin_path=layout.home / ".local/bin/faryo",
        )


def version_name() -> str:
    value = f"v{__version__}"
    if not VERSION_RE.fullmatch(value):
        raise OperationError("Faryo application version is invalid")
    return value


def usable_bootstrap_python(executable: str) -> bool:
    result = run_binary(
        [
            executable,
            "-c",
            "import sys,venv; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)",
        ],
        timeout=10,
    )
    return result.returncode == 0


def select_bootstrap_python(configured: str | None = None) -> str:
    explicit = configured or os.environ.get("FARYO_BOOTSTRAP_PYTHON") or ""
    candidates = [explicit] if explicit else ["/usr/bin/python3", sys.executable]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        absolute = os.path.abspath(candidate)
        if absolute in seen:
            continue
        seen.add(absolute)
        if Path(absolute).is_file() and os.access(absolute, os.X_OK) and usable_bootstrap_python(absolute):
            return absolute
        if explicit:
            break
    raise OperationError("Python 3.10+ with the venv module was not found")


def run_binary(argv: list[str], *, cwd: Path | None = None, timeout: float = 300) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(argv, cwd=cwd, check=False, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OperationError("application preparation command failed") from exc


def git_revision(source: Path) -> str:
    result = run_binary(["git", "-C", str(source), "rev-parse", "HEAD"], timeout=10)
    return result.stdout.decode("ascii", errors="ignore").strip() if result.returncode == 0 else ""


def source_is_clean(source: Path) -> bool:
    result = run_binary(["git", "-C", str(source), "status", "--porcelain=v1"], timeout=10)
    return result.returncode == 0 and not result.stdout.strip()


def safe_extract(archive: Path, destination: Path) -> None:
    root = destination.resolve()
    with tarfile.open(archive, "r:") as handle:
        for member in handle.getmembers():
            target = (destination / member.name).resolve()
            if root not in target.parents and target != root:
                raise OperationError("source archive escapes its destination")
            if member.issym() or member.islnk():
                link = Path(member.linkname)
                if link.is_absolute() or ".." in link.parts:
                    raise OperationError("source archive contains an unsafe link")
        handle.extractall(destination, filter="data")


def copy_source(source: Path, destination: Path) -> str:
    if (source / ".git").exists():
        if not source_is_clean(source):
            raise OperationError("source checkout has uncommitted changes")
        revision = git_revision(source)
        descriptor, archive_name = tempfile.mkstemp(prefix=".faryo-source-", suffix=".tar", dir=destination.parent)
        os.close(descriptor)
        archive = Path(archive_name)
        try:
            result = run_binary(["git", "-C", str(source), "archive", "--format=tar", "-o", str(archive), "HEAD"], timeout=30)
            if result.returncode != 0:
                raise OperationError("source archive could not be created")
            destination.mkdir(parents=True)
            safe_extract(archive, destination)
        finally:
            archive.unlink(missing_ok=True)
        return revision
    ignored = shutil.ignore_patterns(".git", ".faryo", "node_modules", "build", "dist", "__pycache__", "*.pyc", "*.egg-info")
    shutil.copytree(source, destination, ignore=ignored)
    return "release-archive"


def venv_python(version_dir: Path) -> Path:
    return version_dir / ".venv/bin/python"


def venv_cli(version_dir: Path) -> Path:
    return version_dir / ".venv/bin/faryo"


def create_private_venv(version_dir: Path, bootstrap_python: str) -> None:
    result = run_binary([bootstrap_python, "-m", "venv", str(version_dir / ".venv")], timeout=120)
    if result.returncode != 0:
        raise OperationError("private venv creation failed")
    python = venv_python(version_dir)
    for command in (
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", *BUILD_REQUIREMENTS],
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(version_dir / "app/apps/gateway/requirements.txt")],
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", "--no-build-isolation", str(version_dir / "app")],
    ):
        result = run_binary(command, timeout=300)
        if result.returncode != 0:
            raise OperationError("private venv dependency installation failed")
    result = run_binary([str(venv_cli(version_dir)), "--version"], timeout=15)
    if result.returncode != 0:
        raise OperationError("installed Faryo CLI failed its version check")


def remove_staging(path: Path, versions: Path) -> None:
    if path.parent != versions or not path.name.startswith(".stage-"):
        raise OperationError("refusing to remove an unbounded staging path")
    if path.exists():
        shutil.rmtree(path)


def prepare_version(
    layout: Layout | None = None,
    *,
    bootstrap_python: str | None = None,
    version: str | None = None,
) -> Path:
    selected = layout or Layout.from_environment()
    if selected.source_root is None:
        raise OperationError("Faryo source application is unavailable")
    program = ProgramLayout.from_layout(selected)
    name = version or version_name()
    if not VERSION_RE.fullmatch(name):
        raise OperationError("Faryo application version is invalid")
    final = program.versions / name
    if venv_cli(final).is_file() and (final / "app/apps/owner/RELEASE").is_file():
        return final
    program.versions.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".stage-{name}-", dir=program.versions))
    try:
        revision = copy_source(selected.source_root, stage / "app")
        create_private_venv(stage, select_bootstrap_python(bootstrap_python))
        manifest = {
            "schemaVersion": 1,
            "version": name,
            "sourceRevision": revision,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "createdAt": int(time.time()),
        }
        atomic_write(stage / "install-manifest.json", json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", 0o600)
        if final.exists():
            raise OperationError("incomplete version directory already exists")
        stage.replace(final)
        return final
    except Exception:
        remove_staging(stage, program.versions)
        raise


def symlink_target(path: Path) -> Path | None:
    if not path.is_symlink():
        return None
    try:
        return path.resolve(strict=True)
    except OSError:
        return None


def atomic_symlink(path: Path, target: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    temporary.replace(path)


def activate_version(version_dir: Path, layout: Layout | None = None) -> Path | None:
    selected = layout or Layout.from_environment()
    program = ProgramLayout.from_layout(selected)
    if version_dir.parent != program.versions or not venv_cli(version_dir).is_file():
        raise OperationError("prepared version is invalid")
    previous = symlink_target(program.current)
    program.state.mkdir(parents=True, exist_ok=True)
    program.state.chmod(0o700)
    if previous is not None:
        atomic_write(program.state / "previous-version", previous.name + "\n", 0o600)
    relative = os.path.relpath(version_dir, program.current.parent)
    atomic_symlink(program.current, relative)
    cli_target = os.path.relpath(program.current / ".venv/bin/faryo", program.bin_path.parent)
    atomic_symlink(program.bin_path, cli_target)
    return previous


def restore_activation(previous: Path | None, layout: Layout | None = None) -> None:
    selected = layout or Layout.from_environment()
    program = ProgramLayout.from_layout(selected)
    if previous is None:
        program.current.unlink(missing_ok=True)
        program.bin_path.unlink(missing_ok=True)
        return
    if previous.parent != program.versions or not venv_cli(previous).is_file():
        raise OperationError("previous Faryo version is unavailable")
    atomic_symlink(program.current, os.path.relpath(previous, program.current.parent))
    atomic_symlink(program.bin_path, os.path.relpath(program.current / ".venv/bin/faryo", program.bin_path.parent))


def replace_env_value(path: Path, key: str, value: str) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise OperationError("private runtime config is unavailable") from exc
    rendered = f"{key}={shlex.quote(value)}"
    updated: list[str] = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{key}="):
            updated.append(rendered)
            found = True
        else:
            updated.append(line)
    if not found:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append(rendered)
    atomic_write(path, "\n".join(updated).rstrip() + "\n", 0o600)


def install_versioned_application(
    layout: Layout | None = None,
    *,
    bootstrap_python: str | None = None,
    dry_run: bool = False,
    no_start: bool = False,
    migrate_owner: bool = False,
) -> str:
    from faryo_cli.installer import install_services

    selected = layout or Layout.from_environment()
    if selected.source_root is None:
        raise OperationError("Faryo source application is unavailable")
    if dry_run:
        if (selected.source_root / ".git").exists() and not source_is_clean(selected.source_root):
            raise OperationError("source checkout has uncommitted changes")
        return f"{version_name()} dry-run"

    original_configs: dict[Path, str] = {}
    for path in (selected.owner_env, selected.gateway_env):
        try:
            original_configs[path] = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise OperationError("private runtime config is unavailable") from exc
    version_dir = prepare_version(selected, bootstrap_python=bootstrap_python)
    previous = activate_version(version_dir, selected)
    python = str(venv_python(version_dir))
    version_layout = replace(selected, source_root=version_dir / "app")
    try:
        for path in original_configs:
            replace_env_value(path, "FARYO_PYTHON", python)
        install_services(
            version_layout,
            python=python,
            no_start=no_start,
            migrate_owner=migrate_owner,
        )
    except Exception:
        for path, body in original_configs.items():
            atomic_write(path, body, 0o600)
        restore_activation(previous, selected)
        raise
    return version_dir.name
