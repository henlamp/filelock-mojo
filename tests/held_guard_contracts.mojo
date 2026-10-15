"""Eager guard ownership, optional extraction, recursion and rejected transitions."""
from std.sys import argv
from std.testing import assert_equal, assert_true
from filelock_mojo import FileLock, ReadWriteLock


def attempt(mut lock: FileLock) raises -> Bool:
    return lock.try_acquire()


def return_early(mut lock: FileLock) raises -> Int:
    with lock.acquire_guard():
        return 7


def main() raises:
    var path = argv()[1]
    var owner = FileLock(path, timeout=0)
    var rival = FileLock(path, timeout=0)
    var held = owner.try_hold()
    assert_true(Bool(held))
    assert_equal(owner.lock_count(), 1)
    with held.take():
        assert_equal(owner.lock_count(), 1)
        assert_true(not attempt(rival))
        var blocked = rival.try_hold()
        assert_true(not blocked)
    assert_true(not held)
    assert_equal(owner.lock_count(), 0)
    owner.acquire()
    with owner.acquire_guard():
        assert_equal(owner.lock_count(), 2)
        assert_true(not attempt(rival))
    assert_equal(owner.lock_count(), 1)
    owner.release()
    assert_equal(return_early(owner), 7)
    assert_true(not owner.is_locked())
    try:
        with owner.acquire_guard():
            raise Error("body failure")
    except e:
        assert_equal(String(e), String("body failure"))
    assert_true(not owner.is_locked())
    for i in range(2):
        with owner.acquire_guard():
            if i == 0:
                continue
            break
    assert_true(not owner.is_locked())
    var guard = owner.acquire_guard()
    guard.__enter__()
    var rejected = False
    try:
        guard.__enter__()
    except:
        rejected = True
    assert_true(rejected)
    assert_equal(owner.lock_count(), 1)
    guard.__exit__()
    assert_true(not guard.is_active())
    rejected = False
    try:
        guard.release()
    except e:
        rejected = e.kind == .invalid_guard_state
    assert_true(rejected)
    var unused = owner.acquire_guard()
    rejected = False
    try:
        unused.__exit__()
    except:
        rejected = True
    assert_true(rejected and unused.is_active())
    (unused^).__deinit__()
    assert_true(attempt(rival))
    rival.release()
    var rw = ReadWriteLock(path, timeout=0)
    var reading = rw.try_read()
    with reading.take():
        assert_true(rw.is_read_locked())
        rejected = False
        try:
            var forbidden = rw.try_write()
        except e:
            rejected = e.kind == .mode_conflict
        assert_true(rejected and rw.is_read_locked())
    var writing = rw.try_write()
    with writing.take():
        assert_true(rw.is_write_locked())
        assert_true(not attempt(rival))
    assert_true(not rw.is_locked())
    var nonexistent = FileLock(path + "/missing", timeout=0)
    rejected = False
    try:
        var failure = nonexistent.try_hold()
    except e:
        rejected = e.kind == .system and e.errno != 0
    assert_true(rejected)
    print(
        "PASS: eager optional/moved guards, single recursion level, scope"
        " exits, rejected transitions and system errors"
    )
