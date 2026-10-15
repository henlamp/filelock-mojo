from filelock_mojo import ReadWriteLock

def main() raises:
    var lock = ReadWriteLock("borrowed.lock")
    var copied = lock
    print(copied.path(), lock.path())
