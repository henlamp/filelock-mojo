"""Build each standalone Mojo package and record its source identity."""

from __future__ import annotations

import hashlib

from _support import (
    BUILD,
    MOJO,
    PACKAGE_NAMES,
    PACKAGES,
    ROOT,
    run,
    source_hash,
    source_manifest,
    write_report,
)


def main():
    PACKAGES.mkdir(parents=True, exist_ok=True)
    report = {"mojo": run([MOJO, "--version"], "packages-version"), "packages": {}}
    for name in PACKAGE_NAMES:
        output = PACKAGES / (name + ".mojoc")
        run(
            [MOJO, "precompile", "--Werror", ROOT / "src" / name, "-o", output],
            name + "-precompile",
        )
        report["packages"][name] = {
            "source_sha256": source_hash(name),
            "files": source_manifest(name),
            "package_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        }
        print(f"{name}: built", flush=True)
    write_report(BUILD / "packages/manifest.json", report)


if __name__ == "__main__":
    main()
