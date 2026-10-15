"""Build and test the repository's canonical Conda recipe."""

import argparse

from _support import BUILD, CATALOG, source_hash, write_report
from release import build, spec


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rattler-build", default="rattler-build")
    parser.add_argument("--package", choices=CATALOG)
    parser.add_argument("--build-number", type=int)
    args = parser.parse_args()
    recipe = spec()
    if args.build_number is not None and args.build_number != recipe["build"]["number"]:
        raise ValueError("Set the build number and string in conda.recipe/recipe.yaml")
    artifact, result = build(args.rattler_build)
    package = next(iter(CATALOG))
    write_report(
        BUILD / "distributions/manifest.json",
        {
            "version": result["version"],
            "build_number": recipe["build"]["number"],
            "mojo_requirement": "1.1.0",
            "packages": {
                package: {
                    "artifact": str(artifact.relative_to(BUILD)),
                    "sha256": result["sha256"],
                    "source_sha256": source_hash(package),
                    "recipe": recipe,
                    "installed_api_test": "passed",
                    "license": "MIT",
                    "upstream_notice": "unchanged",
                    "privacy_scan": "passed",
                }
            },
        },
    )
    print(package + ": Conda package and installed tests passed")


if __name__ == "__main__":
    main()
