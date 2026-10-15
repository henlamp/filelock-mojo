from filelock_mojo import FileLock


def main() raises:
    var lock = FileLock("unused.lock")
    var duplicate = lock.copy()
