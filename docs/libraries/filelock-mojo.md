# filelock_mojo

Shared/exclusive Unix process locks with a move-only owner and a borrowed context
guard. The native implementation uses the system C ABI for `open`, `flock`,
`close`, errno and process identity. Python filelock is a development interop
peer; lock operations make no Python runtime calls.

```mojo
from filelock_mojo import FileLock


def main() raises:
    with FileLock("cache.lock", timeout=5):
        with open("cache.txt", "w") as output:
            output.write("generated under a native lock")
```

For repeated use, create `var lock = FileLock(path)` and use
`with lock.hold()` or `with lock.hold(timeout=0)`. `with lock^` consumes an owner;
implicit copying is rejected. Guard origins prevent the owner from moving or
being destroyed while borrowed.

## Contract

- `try_acquire()` makes one nonblocking attempt. Contention/interruption returns
  False; filesystem/unsupported-operation failures raise. Opening uses
  `O_NONBLOCK`, so a FIFO marker without a peer cannot stall acquisition.
- `acquire()` uses the configured timeout; an explicit `timeout=` overrides it.
  Zero means immediate attempt, -1 indefinite wait, and positive finite values
  are seconds. Finite deadlines use a monotonic counter; immediate and indefinite waits
  perform no clock reads. This is not a real-time bound
  on filesystem calls or scheduling.
- `mode=.exclusive` is the default. `mode=.shared` allows simultaneous readers
  and excludes exclusive owners. Shared acquisition opens the marker read-only,
  so an existing read-only marker can be used. Mode is fixed for the owner;
  `mode()` returns a value copy. No in-place upgrade or downgrade is provided.
- Same-owner reacquisition increments `lock_count()`. `release()` decrements it
  and unlocks at zero. Separate owners contend. Releasing an unheld owner and
  entering the same active guard twice are errors. Exiting an inactive guard
  raises without releasing another acquisition. Direct acquisition/release
  APIs raise typed `LockError` with public `kind` and `errno` fields.
- Scoped error/return/break/continue paths release the lock. Manual acquisition
  requires a later release; use a guard because Mojo can destroy a value after
  its last use before the end of the lexical scope.
- Process termination releases native locks. Descriptors are close-on-exec.
  Inherited owner objects reject child-process acquisition/release after fork;
  child fallback cleanup closes its descriptor without unlocking the parent's
  shared open-file description. Create new owners after fork.
- New markers use 0600 subject to umask. Existing contents and permissions are
  preserved. Empty/NUL paths, invalid timing values and a final-component symlink
  are rejected. Parent directories must exist.

Use a marker in a trusted directory and agree on one stable, separate inode
across cooperating processes. Symlink rejection covers the final pathname
component; it does not protect against replaced parent directories or markers. FIFO markers without peers must return or report the same unsupported
operation as the host kernel, rather than wait for a reader or writer.
Its existence does not mean the kernel lock is held. Never unlink or replace a
live marker: another process could lock a different inode at the same pathname.
One owner belongs to one process and is not shared concurrently across threads.
Exclusion does not provide atomic file replacement or rollback.

Constructors and direct acquisition/release APIs use Mojo 1.1 typed
`LockError`. `LockErrorKind` distinguishes invalid path/time/mode, timeout,
not-held, forked ownership, recursion limits, system errors and read/write
mode conflicts. System errors retain the original native errno. Context
entry/exit and read/write guard builders use ordinary `Error`, allowing file
I/O and body failures in the guarded block. Mojo requires separate `try` blocks
for different typed errors; a bare-`raises` helper can erase the type at an
application boundary when needed. Failed explicit unlock retains
held state for retry; a post-unlock close error does not restore it. Fallback
deinitializers perform best-effort cleanup.

## Platform and verification

macOS and Linux use their native flags/errno. The variadic `open` call sets
`num_fixed_args=2`, including ARM64 macOS ABI handling. Executed host evidence is
in the matching acceptance reports; shared/network filesystem semantics are
outside these local claims. Windows, soft markers/leases, async cancellation,
fairness guarantees and cross-host locking are outside this native core.

Additional process checks run two shared readers, exclude writers until both
readers release, exclude readers during an exclusive lock, and preserve read-only
markers.

Tests exercise bidirectional Python/Mojo contention, four workers making 480
updates, a deterministic unprotected lost-update control, timeout, 2,000 blocked
attempts under a descriptor limit, SIGKILL/fork/exec cleanup, marker identity,
invalid inputs and compile-time copying/lifetime rejection. The example also
imports a fresh `.mojoc`. Run `uv run python tools/check_filelock.py`.

```mojo
from filelock_mojo import FileLock


def main() raises:
    var reader = FileLock("dataset.lock", mode=.shared, timeout=1)
    with reader.hold():
        print("reader acquired")
```

## Read/write ownership

`ReadWriteLock(path, timeout=..., poll_interval=...)` uses the same kernel
backend. `read()` and `write()` return borrowed context guards; `timeout=`
overrides the configured wait. Release a read hold before requesting a write
hold, then recheck the protected state after acquiring the writer.

```mojo
from filelock_mojo import ReadWriteLock


def main() raises:
    var lock = ReadWriteLock("cache.lock", timeout=1)
    with lock.read():
        print("shared read")
    with lock.write():
        print("exclusive update")
```

Manual `acquire_read`, `acquire_write`, `try_acquire_read` and
`try_acquire_write` mirror FileLock's timeout/contention rules. Same-mode
reacquisition increments `lock_count()`; `release()` drops one level. A held
owner rejects upgrades and downgrades with `LockErrorKind.mode_conflict`,
retaining its original hold. `is_read_locked()` and `is_write_locked()` report
this owner's mode. The owner remains move-only and process-bound; its guards
cannot escape its lifetime. Two real native readers and a writer test exclusion
in both directions. The kernel provides no writer preference or fairness bound.

```mojo
from filelock_mojo import FileLock, LockErrorKind


def main() raises:
    var owner = FileLock("typed-errors.lock", timeout=0)
    owner.acquire()
    var contender = FileLock("typed-errors.lock", timeout=0)
    try:
        contender.acquire()
    except error:
        if error.kind == LockErrorKind.timeout:
            print("busy")
        else:
            raise error^
    owner.release()
```

## Acquired guards and nonblocking attempts

`try_hold()` returns `Optional[HeldFileLock]`: it acquires immediately, or returns
None after one contended/interrupted attempt. Filesystem and ownership errors
remain typed `LockError`. The guard owns exactly one recursion level; entering
its context performs no further acquisition. `ReadWriteLock.try_read()` and
`try_write()` provide the corresponding shared/exclusive attempts.

```mojo
from filelock_mojo import FileLock


def main() raises:
    var lock = FileLock("optional.lock", timeout=1)
    var attempted = lock.try_hold()
    if attempted:
        with attempted.take():
            print("protected work")
    else:
        print("busy")
```

`Optional.take()` moves the guard out and empties the optional. Check presence
before extraction. `acquire_guard()` and `acquire_guard(timeout=...)` instead
wait using the configured/explicit timeout and return an acquired guard. These
context builders expose ordinary `Error` so body file-I/O failures compose with
acquisition. Direct acquisition, guard construction, `try_hold()` and explicit
`HeldFileLock.release()` retain typed errors.

Use `with lock.acquire_guard():` for the immediate result, or `with guard^:`
for a stored move-only guard. `is_active()` reports whether it still owns a
hold in this process. Context exit and explicit release drop its level once;
repeated release, repeated entry and exit before entry are rejected. Deinitialization
provides the same best-effort fallback as the existing scoped guard. An owner
must not manually release levels belonging to its live guards. Mojo may destroy
an unused value before the lexical scope ends; a with-block keeps the guard
alive through protected work.

## Atomic text checkpoints

`atomic_write(path, content, timeout=5)` uses the stable marker `path + ".lock"`,
an exclusive process lock and a unique private temporary in the same directory.
It writes UTF-8 bytes, syncs and closes the temporary, then publishes by atomic
rename. Failures before rename leave the previous file intact. Destination
permissions become 0600; existing permissions are not copied. A killed writer
can leave an orphan temporary, which future writes never reuse. Do not delete
the stable lock marker. The API does not sync the directory or promise recovery
after power loss. Other writers must use the same marker and protocol.

`locked_read(path, max_bytes=1048576, timeout=5)` takes a shared lock and returns
owned text, rejecting files beyond the limit. Limits range from zero to 64 MiB.
These convenience operations raise the context manager's general `Error`;
direct `FileLock` operations retain their typed `LockError` contract.

```mojo
from filelock_mojo import atomic_write, locked_read


def main() raises:
    atomic_write("checkpoint.txt", "completed\n")
    print(locked_read("checkpoint.txt", max_bytes=64))
```
