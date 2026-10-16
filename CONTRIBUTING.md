# Contributing

Develop on `development`; merge tested changes into `main` through focused pull
requests. Publish new versions from `main` and preserve published release files.
Development pushes do not start Actions; run local checks before requesting CI.

Run `uv sync --locked` and `uv run python tools/check_all.py`.
Native process workloads live in `tests/*.mojo`; Python checks kernel behavior
and interoperability with Python-filelock.
Behavior changes need an independent reference or a regression test.
Document public APIs and preserve ownership and platform contracts.
Contributions use the repository's MIT license.

Releases use `conda.recipe/recipe.yaml` and `.github/workflows/release.yml`.
The `release` environment publishes through prefix.dev Repository Access.
For changed builds of the same version, increment both recipe build fields.
`python tools/release.py community --output DIR` exports a pinned community recipe.
Community builds start at zero; use `--build-number N` for subsequent rebuilds.
CodeQL runs when the repository is public; private analysis requires GitHub Code Security.
