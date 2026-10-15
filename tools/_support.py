"""Shared paths, bounded diagnostics, and source identities for local checks."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".build"
FIXTURES = BUILD / "fixtures"
PACKAGES = BUILD / "packages"
MOJO = Path(sys.executable).parent / "mojo"
PACKAGE_CONFIG = tomllib.loads((ROOT / "packages.toml").read_text())
CATALOG = PACKAGE_CONFIG["packages"]
RELEASE_NAMES = tuple(PACKAGE_CONFIG["release"]["packages"])
PACKAGE_NAMES = tuple(CATALOG)


def source_manifest(package: str, *, root: Path = ROOT) -> list[dict]:
    files = sorted((root / "src" / package).rglob("*.mojo"))
    if not files:
        raise ValueError(f"No source files for {package}")
    return [
        {
            "path": str(path.relative_to(root)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files
    ]


def source_hash(package: str, *, root: Path = ROOT) -> str:
    manifest = json.dumps(
        source_manifest(package, root=root), separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(manifest.encode()).hexdigest()


def verification_manifest() -> list[dict]:
    paths = set()
    for directory, pattern in [
        ("src", "*.mojo"),
        ("tests", "*.mojo"),
        ("examples", "*.mojo"),
        ("tests/api", "*.json"),
        ("tools", "*.py"),
        ("integrations", "*.mojo"),
        ("integrations", "*.ts"),
        ("docs/libraries", "*.md"),
    ]:
        paths.update((ROOT / directory).rglob(pattern))
    paths.update(
        ROOT / name
        for name in [
            "pyproject.toml",
            "packages.toml",
            "uv.lock",
            ".python-version",
            "THIRD_PARTY_NOTICES.md",
            "README.md",
            "docs/COMPATIBILITY.md",
            "LICENSE",
        ]
    )
    paths.update((ROOT / ".github/workflows").glob("*.yml"))
    paths.update(p for p in (ROOT / "conda.recipe").rglob("*") if p.is_file())
    paths.update(
        ROOT / item["license_file"]
        for item in CATALOG.values()
        if "license_file" in item
    )
    paths.update((ROOT / "docs/upstream-licenses").glob("*"))
    for package in CATALOG:
        paths.update((ROOT / "src" / package).glob("*LICENSE*"))
    return [
        {
            "path": str(p.relative_to(ROOT)),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in sorted(paths)
    ]


def run(command, label: str, *, timeout: int = 600, cwd: Path = ROOT) -> str:
    BUILD.mkdir(exist_ok=True)
    try:
        result = subprocess.run(
            [str(arg) for arg in command],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        parts = [
            part.decode(errors="replace") if isinstance(part, bytes) else part or ""
            for part in (error.stdout, error.stderr)
        ]
        (BUILD / (label + ".log")).write_text("".join(parts))
        raise RuntimeError(
            f"{label} timed out after {timeout}s; partial diagnostic in .build/{label}.log"
        ) from error
    diagnostic = result.stdout + result.stderr
    (BUILD / (label + ".log")).write_text(diagnostic)
    if result.returncode:
        raise RuntimeError(
            f"{label} failed (exit {result.returncode}); diagnostic in .build/{label}.log\n"
            + diagnostic[:5000]
        )
    return result.stdout.strip()


def reject(fixture: str, expected: str) -> None:
    result = subprocess.run(
        [
            str(MOJO),
            "build",
            "--Werror",
            "-I",
            str(ROOT / "src"),
            str(ROOT / "tests" / fixture),
            "-o",
            str(BUILD / "must-not-build"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    diagnostic = result.stdout + result.stderr
    (BUILD / (fixture + ".log")).write_text(diagnostic)
    if result.returncode == 0 or expected not in diagnostic:
        raise RuntimeError(
            f"Expected rejection missing for {fixture}\n" + diagnostic[:5000]
        )


def write_report(path: Path, report: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(path)
