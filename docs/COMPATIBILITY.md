# Compatibility

The source API targets FileLock on Mojo 1.1.0, macOS ARM64
and experimental Linux x86-64. The compiler version is an exact dependency. A `.mojoc`
artifact belongs to the compiler that built it; another compiler needs a rebuild
and its own acceptance run.

## FileLock

The contract covers local Unix kernel locks with fixed shared/exclusive modes,
finite/nonblocking/indefinite acquisition, per-owner recursion, move-only owners,
lazy/eager borrowed guards and selectable read/write ownership. Guards own one
recursion level and borrow the owner. Direct operations raise LockError with a
condition and errno; context boundaries use Error as documented.

A lock marker has a stable inode in a trusted directory. Do not unlink or replace
it while clients may hold it. An owner belongs to one process and is not used
concurrently across threads. New owners are required after fork. Native process
termination releases the kernel lock; inherited child cleanup must not unlock
its parent's open-file description. Filesystem calls and scheduling have no
real-time deadline guarantee. Windows, leases, cross-host exclusion, async
cancellation and fairness are outside this contract.

Atomic text publication uses a unique private temporary and atomic rename
under the destination marker lock. Shared reads enforce caller byte limits.
Directory sync and power-loss durability are outside this API.

## Compatibility

Patch releases fix documented behavior without changing signatures, ownership,
error categories or accepted inputs. Minor releases add compatible public APIs;
during 0.x development, breaking changes require a new minor version and
migration instructions. Within 0.1.x, the reviewed contract remains compatible.
Security fixes may require a compatibility change; publish its impact and migration instructions. Undocumented
implementation details and internal symbols carry no compatibility promise.

`tests/api` records public declarations and exports. `check_api.py` rejects drift;
baseline changes require a compatibility review.
