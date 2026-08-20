"""Versioned Faryo application and private-venv installation."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
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
MAX_EXTRACTED_SOURCE_BYTES = 128 * 1024 * 1024


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
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    extracted_bytes = 0
    try:
        handle = tarfile.open(archive, "r:*")
    except (OSError, tarfile.TarError) as exc:
        raise OperationError("source archive is unreadable") from exc
    try:
        with handle:
            for member in handle.getmembers():
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                    raise OperationError("source archive escapes its destination")
                target = (destination / Path(*relative.parts)).resolve()
                if root not in target.parents and target != root:
                    raise OperationError("source archive escapes its destination")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    target.chmod(0o755)
                    continue
                if not member.isreg():
                    raise OperationError("source archive contains an unsupported entry")
                extracted_bytes += member.size
                if extracted_bytes > MAX_EXTRACTED_SOURCE_BYTES:
                    raise OperationError("source archive is too large after extraction")
                source = handle.extractfile(member)
                if source is None:
                    raise OperationError("source archive entry is unreadable")
                target.parent.mkdir(parents=True, exist_ok=True)
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    except OperationError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise OperationError("source archive extraction failed") from exc


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


def remove_incomplete_version(path: Path, versions: Path) -> None:
    if path.parent != versions or not VERSION_RE.fullmatch(path.name):
        raise OperationError("refusing to remove an unbounded version path")
    if not (path / ".installing").is_file():
        raise OperationError("refusing to remove a version without its installation marker")
    if path.exists():
        shutil.rmtree(path)


def prepared_version_is_healthy(path: Path) -> bool:
    if not (path / "app/apps/owner/RELEASE").is_file():
        return False
    if not (path / "install-manifest.json").is_file() or (path / ".installing").exists():
        return False
    cli = venv_cli(path)
    if not cli.is_file():
        return False
    return run_binary([str(cli), "--version"], timeout=15).returncode == 0


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
    if prepared_version_is_healthy(final):
        return final
    program.versions.mkdir(parents=True, exist_ok=True)
    if final.exists():
        raise OperationError("incomplete version directory already exists")
    final.mkdir(mode=0o700)
    atomic_write(final / ".installing", "preparing\n", 0o600)
    try:
        revision = copy_source(selected.source_root, final / "app")
        # Virtual-environment entry points contain absolute interpreter paths.
        # Build in the immutable final version directory and atomically expose
        # only the `current` symlink after preparation succeeds.
        create_private_venv(final, select_bootstrap_python(bootstrap_python))
        manifest = {
            "schemaVersion": 1,
            "version": name,
            "sourceRevision": revision,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "createdAt": int(time.time()),
        }
        atomic_write(final / "install-manifest.json", json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", 0o600)
        (final / ".installing").unlink()
        if not prepared_version_is_healthy(final):
            raise OperationError("prepared Faryo version failed its final-path check")
        return final
    except Exception:
        remove_incomplete_version(final, program.versions)
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
    if previous is not None and previous != version_dir:
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


def private_install_paths(layout: Layout) -> tuple[Path, ...]:
    return (
        layout.owner_env,
        layout.gateway_env,
        layout.gateway_auth,
        layout.gateway_env.parent / "initial-password",
        layout.faryo_home / "gateway/state/gateway-cookie-secret",
    )


def snapshot_private_files(paths: tuple[Path, ...]) -> dict[Path, bytes | None]:
    result: dict[Path, bytes | None] = {}
    for path in paths:
        try:
            result[path] = path.read_bytes()
        except FileNotFoundError:
            result[path] = None
        except OSError as exc:
            raise OperationError("private runtime config is unreadable") from exc
    return result


def restore_private_files(snapshot: dict[Path, bytes | None]) -> None:
    for path, body in snapshot.items():
        if body is None:
            path.unlink(missing_ok=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o600)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def initialize_private_config(
    layout: Layout,
    version_dir: Path,
    *,
    workspace: str | None = None,
) -> bool:
    required = (layout.owner_env, layout.gateway_env, layout.gateway_auth)
    if all(path.is_file() for path in required):
        return False
    from faryo_cli.diagnostics import read_env, resolve_codex

    requested_workspace = Path(workspace).expanduser() if workspace else Path.cwd()
    try:
        selected_workspace = requested_workspace.resolve(strict=True)
    except OSError as exc:
        raise OperationError("initial workspace does not exist") from exc
    if not selected_workspace.is_dir():
        raise OperationError("initial workspace is not a directory")
    owner_values = read_env(layout.owner_env)
    codex = resolve_codex(owner_values.get("FARYO_CODEX_BIN") or "", layout.home)
    if not codex:
        raise OperationError("Codex CLI was not found for the initial Owner config")
    bash = shutil.which("bash")
    if not bash:
        raise OperationError("bash is required to initialize Faryo config")
    environment = dict(os.environ)
    environment.update(
        {
            "HOME": str(layout.home),
            "FARYO_HOME": str(layout.faryo_home),
            "FARYO_OWNER_ENV": str(layout.owner_env),
            "FARYO_GATEWAY_ENV": str(layout.gateway_env),
            "GATEWAY_AUTH_CONFIG": str(layout.gateway_auth),
            "FARYO_PYTHON": str(venv_python(version_dir)),
            "FARYO_CODEX_BIN": codex,
            "FARYO_START_DIRECTORY_ROOTS": str(selected_workspace),
            "FARYO_GATEWAY_WORKSPACE_ROOT": str(selected_workspace),
            "FARYO_GATEWAY_ROUTE": "txy",
            "FARYO_GATEWAY_RESET_AUTH": "0",
            "FARYO_OWNER_TOKEN_ROTATE": "0",
        }
    )
    app = version_dir / "app"
    scripts = (
        app / "apps/owner/scripts/init-owner-env.sh",
        app / "apps/gateway/scripts/init-local-gateway.sh",
    )
    for script in scripts:
        if not script.is_file():
            raise OperationError("Faryo configuration initializer is unavailable")
        try:
            result = subprocess.run(
                [bash, str(script)],
                cwd=selected_workspace,
                env=environment,
                check=False,
                capture_output=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OperationError("Faryo configuration initialization failed") from exc
        if result.returncode != 0:
            raise OperationError("Faryo configuration initialization failed")
    for directory in (
        layout.faryo_home,
        layout.owner_env.parent,
        layout.faryo_home / "owner/data",
        layout.gateway_env.parent,
        layout.faryo_home / "gateway/state",
    ):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
    for path in required:
        if not path.is_file():
            raise OperationError("Faryo configuration initialization was incomplete")
        path.chmod(0o600)
    return True


def install_versioned_application(
    layout: Layout | None = None,
    *,
    bootstrap_python: str | None = None,
    dry_run: bool = False,
    no_start: bool = False,
    migrate_owner: bool = False,
    workspace: str | None = None,
    version: str | None = None,
) -> str:
    from faryo_cli.installer import install_services

    selected = layout or Layout.from_environment()
    if selected.source_root is None:
        raise OperationError("Faryo source application is unavailable")
    requested_version = version or version_name()
    if not VERSION_RE.fullmatch(requested_version):
        raise OperationError("Faryo application version is invalid")
    if dry_run:
        if (selected.source_root / ".git").exists() and not source_is_clean(selected.source_root):
            raise OperationError("source checkout has uncommitted changes")
        return f"{requested_version} dry-run"

    version_dir = prepare_version(selected, bootstrap_python=bootstrap_python, version=requested_version)
    private_snapshot = snapshot_private_files(private_install_paths(selected))
    try:
        initialize_private_config(selected, version_dir, workspace=workspace)
    except Exception:
        restore_private_files(private_snapshot)
        raise
    previous = activate_version(version_dir, selected)
    python = str(venv_python(version_dir))
    version_layout = replace(selected, source_root=version_dir / "app")
    try:
        for path in (selected.owner_env, selected.gateway_env):
            replace_env_value(path, "FARYO_PYTHON", python)
        install_services(
            version_layout,
            python=python,
            no_start=no_start,
            migrate_owner=migrate_owner,
        )
    except Exception:
        restore_private_files(private_snapshot)
        restore_activation(previous, selected)
        raise
    return version_dir.name
