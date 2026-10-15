"""Same-mode recursion, typed errors and native read/write scope ownership."""
from std.sys import argv
from std.testing import assert_equal, assert_true
from filelock_mojo import FileLock, ReadWriteLock, LockErrorKind


def can_read(mut lock: ReadWriteLock) raises -> Bool:
    return lock.try_acquire_read()


def can_write(mut lock: ReadWriteLock) raises -> Bool:
    return lock.try_acquire_write()


def return_early(mut lock: ReadWriteLock) raises -> Int:
    with lock.write(timeout=0):
        return 7


def main() raises:
    var path = argv()[1]
    var owner = ReadWriteLock(path, timeout=0)
    var rival = ReadWriteLock(path, timeout=0)
    owner.acquire_read()
    owner.acquire_read()
    assert_equal(owner.lock_count(), 2)
    assert_true(owner.is_read_locked() and not owner.is_write_locked())
    assert_true(can_read(rival))
    rival.release()
    var rejected = False
    try:
        owner.acquire_write()
    except e:
        rejected = e.kind == .mode_conflict and e.errno == 0
    assert_true(rejected and owner.lock_count() == 2)
    rejected = False
    try:
        rival.acquire_write()
    except e:
        rejected = e.kind == .timeout and e.errno == 0
    assert_true(rejected and not rival.is_locked())
    owner.release()
    assert_true(not can_write(rival))
    owner.release()
    assert_true(can_write(rival))
    assert_true(rival.is_write_locked() and not rival.is_read_locked())
    rejected = False
    try:
        rival.acquire_read()
    except e:
        rejected = e.kind == .mode_conflict
    assert_true(rejected)
    rival.release()
    with owner.read():
        assert_true(can_read(rival))
        rival.release()
        assert_true(not can_write(rival))
    with owner.write():
        assert_true(not can_read(rival))
    try:
        with owner.write():
            raise Error("body failure")
    except e:
        rejected = String(e) == "body failure"
    assert_true(rejected and not owner.is_locked())
    assert_equal(return_early(owner), 7)
    var moved = owner^
    assert_true(can_write(moved))
    moved.release()
    rejected = False
    try:
        moved.release()
    except e:
        rejected = e.kind == LockErrorKind.not_held
    assert_true(rejected)
    rejected = False
    try:
        var invalid = FileLock("")
    except e:
        rejected = e.kind == .invalid_path and e.errno == 0
    assert_true(rejected)
    var missing = FileLock(path + "/missing")
    rejected = False
    try:
        missing.acquire()
    except e:
        rejected = e.kind == .system and e.errno != 0
    assert_true(rejected)
    print(
        "PASS: typed lock failures, read/write recursion, rejected"
        " upgrades/downgrades, scopes and moving"
    )
