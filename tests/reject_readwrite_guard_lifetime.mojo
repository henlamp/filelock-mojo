from std.origin import MutUntrackedOrigin
from filelock_mojo import ReadWriteLock, ScopedFileLock

def dangling() raises -> ScopedFileLock[MutUntrackedOrigin]:
    var lock = ReadWriteLock("borrowed.lock")
    return lock.read()

def main() raises:
    _ = dangling()
