from filelock_mojo import FileLock

def main() raises:
    var owner = FileLock("unused.lock",timeout=0)
    var guard = owner.acquire_guard()
    var copy = guard
    print(guard.is_active(),copy.is_active())
