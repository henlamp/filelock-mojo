# Validation

Native macOS ARM64 and Linux x86-64 checks cover Mojo 1.1.0 and
1.2.0.dev2026100905. Development 0.2.0 also builds Conda packages and runs fresh
Pixi consumers on both platforms: [native checks](https://github.com/henlamp/filelock-mojo/actions/runs/38909416942).

Checks exercise process contention, Python parity, fork/exec, killed writers and ownership.
Executable examples and installed consumers are checked separately.
Exact source identities, compiler versions and reports: [CI artifacts](https://github.com/henlamp/filelock-mojo/actions/workflows/checks.yml).
