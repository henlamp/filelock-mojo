# filelock-mojo

[![CodeQL](https://github.com/henlamp/filelock-mojo/actions/workflows/codeql.yml/badge.svg)](https://github.com/henlamp/filelock-mojo/actions/workflows/codeql.yml)

Shared/exclusive Unix process locks, atomic UTF-8 writes and bounded locked reads
in native Mojo. Owners are move-only; guards borrow them.

## Install

With [Pixi](https://pixi.sh):

```sh
pixi init my-project
cd my-project
pixi workspace channel add https://repo.prefix.dev/modular-community https://conda.modular.com/max
pixi add filelock-mojo
```

Save as `example.mojo`, then run `pixi run mojo run example.mojo`:

```mojo
from filelock_mojo import atomic_write, locked_read

def main() raises:
    atomic_write("checkpoint.txt", "step=42\n")
    print(locked_read("checkpoint.txt", max_bytes=4096))
```

Use a trusted local filesystem and the same stable lock file in every process.
Do not unlink or replace the lock file, or share an owner across threads.
Atomic writes preserve the old file if publication fails; they do not promise
power-loss durability. Windows and cross-host locking are unsupported.

Version 0.1.0 packages use Mojo 1.1.0 on macOS ARM64. Source checks also cover
1.2.0.dev2026100905; Linux is experimental.

[API](docs/libraries/filelock-mojo.md) · [Compatibility](docs/COMPATIBILITY.md) ·
[Checks](docs/VALIDATION.md). Run `uv run python tools/check_all.py` to verify the checkout.

[MIT](LICENSE). Inspired by Python filelock; see [notices](THIRD_PARTY_NOTICES.md)
and its unchanged [license](UPSTREAM_LICENSE).
