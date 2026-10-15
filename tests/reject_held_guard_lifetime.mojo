from std.origin import MutUntrackedOrigin
from filelock_mojo import FileLock, HeldFileLock

def escape() raises -> HeldFileLock[MutUntrackedOrigin]:
    var owner = FileLock("unused.lock",timeout=0)
    return owner.acquire_guard()

def main() raises:
    _ = escape()
