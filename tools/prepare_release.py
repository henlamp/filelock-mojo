"""Create a reviewable source candidate from an explicit file allowlist."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import tarfile
import tomllib
from pathlib import Path

from _support import (
    BUILD,
    CATALOG,
    PACKAGE_NAMES,
    ROOT,
    source_hash,
    verification_manifest,
    write_report,
)

DIRECTORIES = [
    "src",
    "tools",
    "tests",
    "examples",
    "docs",
    "benchmarks",
    ".github",
    "conda.recipe",
]
FILES = [
    "README.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "THIRD_PARTY_NOTICES.md",
    "LICENSE",
    "UPSTREAM_LICENSE",
    "SECURITY.md",
    "pyproject.toml",
    "packages.toml",
    "uv.lock",
    ".python-version",
    ".gitignore",
]
EXCLUDED_PARTS = {
    "__pycache__",
    ".venv",
    ".local",
    ".build",
    ".toolchains",
    "__mojocache__",
}
PRIVATE_MARKERS = [
    r"/(?:Users|home)/[A-Za-z0-9_.-]+/",
    r"OneDrive[ /-]",
    r"gh[pousr]_[A-Za-z0-9]{20,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
]


def main():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--acceptance-report", type=Path, action="append", required=True
    )
    args = parser.parse_args()
    acceptance_paths = [path.resolve() for path in args.acceptance_report]
    for path in acceptance_paths:
        acceptance = json.loads(path.read_text())
        if acceptance.get("status") != "passed":
            raise RuntimeError(f"Successful acceptance is required: {path.name}")
        if acceptance.get("verified_inputs") != verification_manifest():
            raise RuntimeError(f"Stale code/config/check acceptance: {path.name}")
        for name in PACKAGE_NAMES:
            if acceptance["packages"][name]["source_sha256"] != source_hash(name):
                raise RuntimeError(f"Stale source acceptance: {path.name}: {name}")
    paths = [ROOT / name for name in FILES]
    for directory in DIRECTORIES:
        paths.extend(
            path
            for path in (ROOT / directory).rglob("*")
            if path.is_file()
            and not any(part in EXCLUDED_PARTS for part in path.parts)
            and path.suffix not in {".tmp", ".pyc"}
            and not (path.parent == ROOT / "tests" and path.suffix == ".json")
        )
    paths = sorted(set(paths))
    manifest = []
    for path in paths:
        if path.is_symlink():
            raise RuntimeError(f"Symlinks are excluded: {path}")
        contents = path.read_bytes()
        try:
            text = contents.decode("utf-8")
        except UnicodeDecodeError:
            raise RuntimeError(f"Unexpected binary source file: {path}") from None
        for marker in PRIVATE_MARKERS:
            if re.search(marker, text):
                raise RuntimeError(
                    f"Private path or credential pattern in {path.relative_to(ROOT)}"
                )
        manifest.append(
            {
                "path": str(path.relative_to(ROOT)),
                "size": len(contents),
                "sha256": hashlib.sha256(contents).hexdigest(),
            }
        )
    folder = BUILD / "release"
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f"filelock-mojo-{version}-source.tar.gz"
    with archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as output:
                for path in paths:
                    info = output.gettarinfo(
                        str(path), arcname=str(path.relative_to(ROOT))
                    )
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    with path.open("rb") as source:
                        output.addfile(info, source)
    report = {
        "version": version,
        "state": "unpublished source candidate",
        "licenses": {
            name: CATALOG[name].get("license", "LicenseRef-Unreleased")
            for name in PACKAGE_NAMES
        },
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "files": manifest,
        "packages": {name: source_hash(name) for name in PACKAGE_NAMES},
        "acceptance_reports": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in acceptance_paths
        },
        "privacy_scan": "passed",
        "excluded": [
            "private local notes/data",
            "toolchains/venvs",
            "compiled binaries",
            "build logs",
            "git metadata",
        ],
    }
    write_report(folder / "manifest.json", report)
    print(f"Prepared {len(paths)} source files: {archive}")


if __name__ == "__main__":
    main()
