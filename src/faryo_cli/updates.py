"""Verified release download and atomic Faryo update orchestration."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import hmac
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from faryo_cli import __version__
from faryo_cli.application import ProgramLayout, VERSION_RE, install_versioned_application, safe_extract, symlink_target
from faryo_cli.diagnostics import Layout
from faryo_cli.operations import OperationError


DEFAULT_REPOSITORY = "SongJunguo/faryo-codex-web-ui"
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}")


def normalize_version(value: str) -> str:
    version = value.strip()
    if not version.startswith("v"):
        version = f"v{version}"
    if not VERSION_RE.fullmatch(version):
        raise OperationError("Faryo release version is invalid")
    return version


def trusted_release_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (hostname == "github.com" or hostname == "api.github.com" or hostname.endswith(".githubusercontent.com"))


def fetch_bytes(url: str, *, maximum: int) -> bytes:
    if not trusted_release_url(url):
        raise OperationError("release URL is not an approved HTTPS endpoint")
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": f"Faryo/{__version__}"})
    try:
        with urlopen(request, timeout=30) as response:
            final_url = response.geturl()
            if not trusted_release_url(final_url):
                raise OperationError("release download redirected outside approved HTTPS endpoints")
            length = response.headers.get("Content-Length")
            if length and int(length) > maximum:
                raise OperationError("release download exceeds its size limit")
            body = response.read(maximum + 1)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise OperationError("release download failed") from exc
    if len(body) > maximum:
        raise OperationError("release download exceeds its size limit")
    return body


def latest_release_version(repository: str = DEFAULT_REPOSITORY) -> str:
    body = fetch_bytes(f"https://api.github.com/repos/{repository}/releases/latest", maximum=MAX_METADATA_BYTES)
    try:
        payload: Any = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperationError("latest release metadata is invalid") from exc
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        raise OperationError("latest stable Faryo release is unavailable")
    return normalize_version(str(payload.get("tag_name") or ""))


def release_asset_names(version: str) -> tuple[str, str]:
    normalized = normalize_version(version)
    archive = f"faryo-{normalized}.tar.gz"
    return archive, f"{archive}.sha256"


def release_asset_url(version: str, name: str, repository: str = DEFAULT_REPOSITORY) -> str:
    normalized = normalize_version(version)
    if name not in release_asset_names(normalized):
        raise OperationError("unsupported Faryo release asset")
    return f"https://github.com/{repository}/releases/download/{normalized}/{name}"


def parse_checksum(body: str, archive_name: str) -> str:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if len(lines) != 1:
        raise OperationError("release checksum manifest is invalid")
    match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?([^/\\\s]+)", lines[0])
    if not match or match.group(2) != archive_name:
        raise OperationError("release checksum manifest is invalid")
    return match.group(1).lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise OperationError("release archive is unreadable") from exc
    return digest.hexdigest()


def verify_archive(path: Path, expected: str) -> None:
    if not SHA256_RE.fullmatch(expected.lower()):
        raise OperationError("release checksum is invalid")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise OperationError("release archive is unavailable") from exc
    if size <= 0 or size > MAX_ARCHIVE_BYTES:
        raise OperationError("release archive has an invalid size")
    if not hmac.compare_digest(sha256_file(path), expected.lower()):
        raise OperationError("release archive checksum mismatch")


def release_source_root(extracted: Path, version: str) -> Path:
    entries = [path for path in extracted.iterdir() if path.name not in {".", ".."}]
    if len(entries) != 1 or not entries[0].is_dir():
        raise OperationError("release archive must contain one application root")
    root = entries[0]
    release = root / "apps/owner/RELEASE"
    pyproject = root / "pyproject.toml"
    try:
        release_values = dict(
            line.split("=", 1) for line in release.read_text(encoding="utf-8").splitlines() if "=" in line
        )
        expected = normalize_version(version)
        if release_values.get("version") != expected:
            raise OperationError("release archive version does not match its tag")
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib
        metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        if f"v{metadata['project']['version']}" != expected:
            raise OperationError("release package metadata does not match its tag")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, OperationError):
            raise
        raise OperationError("release archive metadata is invalid") from exc
    return root


def update_application(
    layout: Layout | None = None,
    *,
    version: str | None = None,
    archive: str | None = None,
    checksum: str | None = None,
    bootstrap_python: str | None = None,
) -> str:
    selected = layout or Layout.from_environment()
    requested = normalize_version(version) if version else latest_release_version()
    program = ProgramLayout.from_layout(selected)
    current = symlink_target(program.current)
    if current is not None and current.name == requested:
        raise OperationError("requested Faryo version is already active")
    archive_name, checksum_name = release_asset_names(requested)
    with tempfile.TemporaryDirectory(prefix="faryo-update-") as temporary_name:
        temporary = Path(temporary_name)
        local_archive = temporary / archive_name
        if archive:
            source = Path(archive).expanduser()
            try:
                shutil.copyfile(source, local_archive)
            except OSError as exc:
                raise OperationError("local release archive is unavailable") from exc
            if not checksum:
                raise OperationError("a checksum is required for a local release archive")
            checksum_path = Path(checksum).expanduser()
            if checksum_path.is_file():
                try:
                    checksum_body = checksum_path.read_text(encoding="utf-8")
                except OSError as exc:
                    raise OperationError("local checksum manifest is unreadable") from exc
                expected = parse_checksum(checksum_body, archive_name)
            else:
                expected = checksum.lower()
        else:
            local_archive.write_bytes(fetch_bytes(release_asset_url(requested, archive_name), maximum=MAX_ARCHIVE_BYTES))
            try:
                checksum_body = fetch_bytes(release_asset_url(requested, checksum_name), maximum=4096).decode("ascii")
            except UnicodeDecodeError as exc:
                raise OperationError("release checksum manifest is invalid") from exc
            expected = parse_checksum(checksum_body, archive_name)
        verify_archive(local_archive, expected)
        extracted = temporary / "source"
        safe_extract(local_archive, extracted)
        source_root = release_source_root(extracted, requested)
        release_layout = replace(selected, source_root=source_root)
        return install_versioned_application(
            release_layout,
            bootstrap_python=bootstrap_python,
            version=requested,
        )
