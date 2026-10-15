from std.origin import MutUntrackedOrigin
from filelock_mojo import FileLock, ScopedFileLock


def escape() raises -> ScopedFileLock[MutUntrackedOrigin]:
    var lock = FileLock("unused.lock")
    return lock.hold()


def main() raises:
    var dangling = escape()
