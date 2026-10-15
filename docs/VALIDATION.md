# Validation

Native macOS ARM64 and Linux x86-64 checks cover Mojo 1.1.0 and
1.2.0.dev2026100905. Prebuilt packages currently target macOS ARM64.

Checks exercise process contention, Python parity, fork/exec, killed writers and ownership.
Executable examples and installed consumers are checked separately.
Exact source identities, compiler versions and reports: [CI artifacts](https://github.com/henlamp/filelock-mojo/actions/workflows/checks.yml).
