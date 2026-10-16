"""Build, check and publish this repository's Conda package."""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".build/distributions"
RECIPE = ROOT / "conda.recipe/recipe.yaml"
CHANNELS = ["https://conda.modular.com/max", "conda-forge"]


def native_subdir():
    host = (platform.system(), platform.machine().lower())
    if host == ("Darwin", "arm64"):
        return "osx-arm64"
    if host[0] == "Linux" and host[1] in {"x86_64", "amd64"}:
        return "linux-64"
    raise ValueError("Supported package hosts are macOS ARM64 and Linux x86-64")


def run(command, **kwargs):
    return subprocess.check_output(
        [str(arg) for arg in command], text=True, **kwargs
    ).strip()


def spec():
    return json.loads(RECIPE.read_text())


def head():
    return run(["git", "rev-parse", "HEAD"], cwd=ROOT)


def check_tag(tag):
    recipe = spec()
    expected = "v" + recipe["package"]["version"]
    if tag != expected or not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError(f"Expected release tag {expected}")
    if run(["git", "rev-parse", f"refs/tags/{tag}^{{commit}}"], cwd=ROOT) != head():
        raise ValueError("Release tag does not identify this checkout")
    return recipe


def checked_artifact(tag=None):
    recipe = check_tag(tag) if tag else spec()
    report = json.loads((OUTPUT / "release.json").read_text())
    if (
        report["source_commit"] != head()
        or report["recipe_sha256"] != hashlib.sha256(RECIPE.read_bytes()).hexdigest()
    ):
        raise ValueError("Package source or recipe differs from this checkout")
    name = report["artifact"]
    if Path(name).name != name or not name.endswith(".conda"):
        raise ValueError("Invalid package filename")
    subdir = report["subdir"]
    if subdir != native_subdir():
        raise ValueError("Package platform differs from this host")
    artifact = OUTPUT / subdir / name
    if (
        artifact.is_symlink()
        or hashlib.sha256(artifact.read_bytes()).hexdigest() != report["sha256"]
    ):
        raise ValueError("Package checksum mismatch")
    if (
        report["name"] != recipe["package"]["name"]
        or report["version"] != recipe["package"]["version"]
    ):
        raise ValueError("Package name or version mismatch")
    return artifact, report


def inspect(artifact, rattler, destination):
    subprocess.run(
        [rattler, "package", "extract", str(artifact), "--dest", str(destination)],
        check=True,
    )
    metadata = json.loads((destination / "info/index.json").read_text())
    recipe = spec()
    if (metadata["name"], metadata["version"], metadata["subdir"]) != (
        recipe["package"]["name"],
        recipe["package"]["version"],
        native_subdir(),
    ):
        raise ValueError("Unexpected package metadata")
    if (
        "mojo-compiler ==1.1.0" not in metadata["depends"]
        or metadata["license"] != "MIT"
    ):
        raise ValueError("Compiler or license metadata mismatch")
    for filename in recipe["about"]["license_file"]:
        if (destination / "info/licenses" / filename).read_bytes() != (
            ROOT / filename
        ).read_bytes():
            raise ValueError("License or notice changed: " + filename)
    for path in destination.rglob("*"):
        if path.is_file() and re.search(
            rb"/(?:Users|home)/[A-Za-z0-9_.-]+/|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----",
            path.read_bytes(),
        ):
            raise ValueError(
                "Private path or credential in package: "
                + str(path.relative_to(destination))
            )
    return metadata


def build(rattler="rattler-build", tag=None):
    recipe = check_tag(tag) if tag else spec()
    subdir = native_subdir()
    if run(["git", "status", "--porcelain"], cwd=ROOT):
        raise ValueError("Build requires a clean committed source tree")
    if run([rattler, "--version"]) != "rattler-build 0.76.1":
        raise ValueError("Use rattler-build 0.76.1")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mojo-release-", dir="/tmp") as directory:
        work = Path(directory)
        source = work / "source"
        source.mkdir()
        archive = work / "source.tar"
        subprocess.run(
            ["git", "archive", "--format=tar", f"--output={archive}", "HEAD"],
            cwd=ROOT,
            check=True,
        )
        with tarfile.open(archive) as snapshot:
            snapshot.extractall(source, filter="data")
        command = [
            rattler,
            "build",
            "--no-config",
            "--recipe",
            str(source / "conda.recipe/recipe.yaml"),
            "--output-dir",
            str(work / "output"),
            "--color",
            "never",
        ]
        for channel in CHANNELS:
            command += ["-c", channel]
        with (OUTPUT / "build.log").open("w") as log:
            result = subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT, check=False
            )
        if result.returncode:
            raise RuntimeError(
                "Package build or installed tests failed; see .build/distributions/build.log"
            )
        candidates = list(
            (work / "output" / subdir).glob(recipe["package"]["name"] + "-*.conda")
        )
        if len(candidates) != 1:
            raise ValueError("Expected exactly one package")
        metadata = inspect(candidates[0], rattler, work / "inspected")
        target = OUTPUT / subdir / candidates[0].name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(candidates[0], target)
    report = {
        "name": metadata["name"],
        "version": metadata["version"],
        "subdir": metadata["subdir"],
        "source_commit": head(),
        "recipe_sha256": hashlib.sha256(RECIPE.read_bytes()).hexdigest(),
        "artifact": target.name,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "installed_tests": "passed",
        "privacy_scan": "passed",
        "licenses": "unchanged",
        "depends": metadata["depends"],
    }
    (OUTPUT / "release.json").write_text(json.dumps(report, indent=2) + "\n")
    record = dict(metadata, sha256=report["sha256"], size=target.stat().st_size)
    for channel_subdir in (subdir, "noarch"):
        directory = OUTPUT / channel_subdir
        directory.mkdir(exist_ok=True)
        index = {
            "info": {"subdir": channel_subdir},
            "packages": {},
            "packages.conda": {target.name: record} if channel_subdir == subdir else {},
            "repodata_version": 1,
        }
        (directory / "repodata.json").write_text(json.dumps(index) + "\n")
    return target, report


def installed(channel, pixi="pixi", tag=None):
    _, report = checked_artifact(tag)
    with tempfile.TemporaryDirectory(prefix="mojo-consumer-", dir="/tmp") as directory:
        project = Path(directory)
        commands = [
            [pixi, "init", "--format", "pixi", "."],
            [pixi, "workspace", "channel", "add", "--prepend", channel, *CHANNELS],
        ]
        for command in commands:
            subprocess.run(command, cwd=project, check=True)
        package = (
            report["name"] + "==" + report["version"] + "=" + spec()["build"]["string"]
        )
        for attempt in range(6):
            install_env = os.environ.copy()
            install_env["PIXI_CACHE_DIR"] = str(project / f"cache-{attempt}" / "pixi")
            install_env["RATTLER_CACHE_DIR"] = str(
                project / f"cache-{attempt}" / "rattler"
            )
            installed = subprocess.run(
                [pixi, "add", package], cwd=project, env=install_env, check=False
            )
            if installed.returncode == 0:
                break
            if attempt == 5:
                raise RuntimeError(
                    "Published build was not installable after six attempts"
                )
            print(
                "Published build not yet installable; retrying with fresh index metadata",
                flush=True,
            )
            time.sleep(min(20, 5 * (attempt + 1)))
        for path in (ROOT / "conda.recipe").iterdir():
            if path.suffix in {".mojo", ".usda"}:
                shutil.copy2(path, project / path.name)
        records = [
            json.loads(path.read_text())
            for path in (project / ".pixi/envs/default/conda-meta").glob("*.json")
        ]
        actual = next(row for row in records if row["name"] == report["name"])
        if actual["sha256"] != report["sha256"]:
            raise ValueError("Installed package differs from the checked artifact")
        for command in spec()["tests"][0]["script"]:
            subprocess.run(
                [pixi, "run", *command.split()],
                cwd=project,
                env=install_env,
                check=True,
            )
    (OUTPUT / "installed.json").write_text(
        json.dumps(
            {"status": "passed", "channel": channel, "sha256": report["sha256"]},
            indent=2,
        )
        + "\n"
    )


def community(destination, commit=None, build_number=0):
    if build_number < 0:
        raise ValueError("Community build number must be nonnegative")
    commit = commit or head()
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Community source needs an immutable commit SHA")
    recipe = spec()
    recipe["source"] = {"git": recipe["about"]["repository"], "rev": commit}
    recipe["build"]["number"] = build_number
    recipe["build"]["string"] = (
        recipe["build"]["string"].rsplit("_", 1)[0] + f"_{build_number}"
    )
    destination.mkdir(parents=True, exist_ok=True)
    for path in (ROOT / "conda.recipe").iterdir():
        if path.is_file() and path.name != "recipe.yaml":
            shutil.copy2(path, destination / path.name)
    (destination / "recipe.yaml").write_text(json.dumps(recipe, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["build", "verify", "publish", "installed", "community"]
    )
    parser.add_argument("--tag")
    parser.add_argument("--rattler-build", default="rattler-build")
    parser.add_argument("--pixi", default="pixi")
    parser.add_argument("--channel")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--build-number", type=int, default=0)
    args = parser.parse_args()
    if args.command == "build":
        artifact, _ = build(args.rattler_build, args.tag)
        print(artifact)
    elif args.command == "community":
        if args.output is None:
            parser.error("community requires --output")
        community(args.output, build_number=args.build_number)
    elif args.command == "installed":
        if args.channel is None:
            parser.error("installed requires --channel")
        installed(args.channel, args.pixi, args.tag)
    else:
        artifact, report = checked_artifact(args.tag)
        if args.command == "publish":
            if (
                args.tag is None
                or os.environ.get("GITHUB_REPOSITORY") != "henlamp/" + report["name"]
            ):
                raise ValueError(
                    "Publishing requires the matching henlamp release workflow"
                )
            subprocess.run(
                [
                    args.rattler_build,
                    "upload",
                    "prefix",
                    "--skip-existing",
                    "--channel",
                    "henlamp/mojo",
                    str(artifact),
                ],
                check=True,
            )
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
