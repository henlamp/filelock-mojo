# SPDX-FileCopyrightText: 2026 henlamp
# SPDX-License-Identifier: MIT

"""Unix shared/exclusive locks with scoped, move-only ownership.

Every cooperating process must use the same stable lock inode. Do not unlink or
replace a live lock file. One object belongs to one process and is not shared
concurrently between threads. Use `with FileLock(path):` for a protected region.
"""
from std.collections import Optional
from std.ffi import c_int, external_call
from std.io import Writer
from std.math import isfinite
from std.memory import Pointer
from std.origin import MutOrigin, MutUntrackedOrigin
from std.sys import CompilationTarget
from std.time import perf_counter, sleep


comptime _O_RDWR = 2
comptime _LOCK_SH = 1
comptime _LOCK_EX = 2
comptime _LOCK_NB = 4
comptime _LOCK_UN = 8
comptime _EINTR = 4
comptime _EWOULDBLOCK = 35 if CompilationTarget.is_macos() else 11


@fieldwise_init
struct LockMode(Equatable, ImplicitlyCopyable, Writable):
    """Shared readers or one exclusive writer on the same marker inode."""

    var _code: Int
    comptime shared = Self(_LOCK_SH)
    comptime exclusive = Self(_LOCK_EX)

    def write_to(self, mut writer: Some[Writer]):
        """Render a mode name, retaining the code for unsupported values."""
        if self == .shared:
            writer.write("shared")
        elif self == .exclusive:
            writer.write("exclusive")
        else:
            writer.write("LockMode(", self._code, ")")

    def _valid(self) -> Bool:
        return self == .shared or self == .exclusive


@fieldwise_init
struct LockErrorKind(Equatable, ImplicitlyCopyable):
    """Distinguish argument, contention, ownership and operating-system failures.
    """

    var _code: Int
    comptime invalid_path = Self(0)
    comptime invalid_time = Self(1)
    comptime timeout = Self(2)
    comptime system = Self(3)
    comptime not_held = Self(4)
    comptime forked = Self(5)
    comptime recursion_limit = Self(6)
    comptime invalid_mode = Self(7)
    comptime mode_conflict = Self(8)
    comptime invalid_guard_state = Self(9)


@fieldwise_init
struct LockError(ImplicitlyCopyable, Writable):
    """Native error with a condition and the original errno for system failures.
    """

    var kind: LockErrorKind
    var errno: Int

    def write_to(self, mut writer: Some[Writer]):
        """Render the condition and captured errno."""
        var label = String("system")
        if self.kind == .invalid_path:
            label = "invalid path"
        elif self.kind == .invalid_time:
            label = "invalid timeout/poll interval"
        elif self.kind == .timeout:
            label = "timeout"
        elif self.kind == .not_held:
            label = "not held"
        elif self.kind == .forked:
            label = "object used in another process"
        elif self.kind == .recursion_limit:
            label = "recursion limit"
        elif self.kind == .invalid_mode:
            label = "Invalid file lock mode"
        elif self.kind == .mode_conflict:
            label = "cannot change a held lock mode"
        elif self.kind == .invalid_guard_state:
            label = "invalid guard state"
        writer.write("FileLock ", label, " (errno=", self.errno, ")")


def _errno() -> Int:
    comptime if CompilationTarget.is_macos():
        var address = external_call[
            "__error", Pointer[c_int, MutUntrackedOrigin]
        ]()
        return Int(address.unsafe_load())
    else:
        var address = external_call[
            "__errno_location", Pointer[c_int, MutUntrackedOrigin]
        ]()
        return Int(address.unsafe_load())


def _pid() -> Int:
    return Int(external_call["getpid", c_int]())


def _open_flags() -> Int:
    comptime if CompilationTarget.is_macos():
        comptime o_creat = 0x200
        comptime o_nonblock = 0x4
        comptime o_cloexec = 0x01000000
        comptime o_nofollow = 0x100
        return o_creat | o_nonblock | o_cloexec | o_nofollow
    elif CompilationTarget.is_linux():
        comptime o_creat = 64
        comptime o_nonblock = 2048
        comptime o_cloexec = 524288
        # Linux ARM uses a different O_NOFOLLOW bit from x86-64.
        comptime o_nofollow = 32768 if CompilationTarget.is_arm() else 131072
        return o_creat | o_nonblock | o_cloexec | o_nofollow
    else:
        return 0


def _validate_time(timeout: Float64, poll_interval: Float64) raises LockError:
    if not isfinite(timeout) or (timeout < 0 and timeout != -1):
        raise LockError(.invalid_time, 0)
    if not isfinite(poll_interval) or poll_interval <= 0:
        raise LockError(.invalid_time, 0)


struct FileLock(Movable):
    """Own a recursive Unix flock in one process; scope it with hold()."""

    var _path: String
    var _fd: c_int
    var _depth: Int
    var _owner_pid: Int
    var _timeout: Float64
    var _poll_interval: Float64
    var _mode: LockMode

    def __init__(
        out self,
        path: String,
        *,
        timeout: Float64 = -1,
        poll_interval: Float64 = 0.01,
        mode: LockMode = .exclusive,
    ) raises LockError:
        """Set a stable marker path and finite timing policy without opening it.
        """
        comptime assert (
            CompilationTarget.is_macos() or CompilationTarget.is_linux()
        ), "FileLock supports macOS and Linux"
        if path.byte_length() == 0:
            raise LockError(.invalid_path, 0)
        for byte in path.bytes():
            if byte == 0:
                raise LockError(.invalid_path, 0)
        if not mode._valid():
            raise LockError(.invalid_mode, 0)
        _validate_time(timeout, poll_interval)
        self._path = path
        self._fd = -1
        self._depth = 0
        self._owner_pid = _pid()
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._mode = mode

    def __init__(out self, *, deinit move: Self):
        self._path = move._path^
        self._fd = move._fd
        self._depth = move._depth
        self._owner_pid = move._owner_pid
        self._timeout = move._timeout
        self._poll_interval = move._poll_interval
        self._mode = move._mode

    def __deinit__(deinit self):
        # Never issue LOCK_UN from a forked child's destructor: it can unlock
        # the parent's shared open-file description. Closing only drops this fd.
        if self._fd >= 0:
            _ = external_call["close", c_int](self._fd)

    def path(self) -> String:
        """Return the marker pathname; its inode must remain stable while held.
        """
        return self._path

    def is_locked(self) -> Bool:
        """Whether this owner currently holds the lock in this process."""
        return self._depth > 0 and self._owner_pid == _pid()

    def mode(self) -> LockMode:
        """Return the acquisition mode, fixed for this owner's lifetime."""
        return self._mode

    def lock_count(self) -> Int:
        """Current same-owner recursion depth, or zero in a forked child."""
        return self._depth if self._owner_pid == _pid() else 0

    def _check_owner(self) raises LockError:
        if self._owner_pid != _pid():
            raise LockError(.forked, 0)

    def try_acquire(mut self) raises LockError -> Bool:
        """One nonblocking attempt; contention/interruption returns False."""
        self._check_owner()
        if self._depth > 0:
            if self._depth == 9223372036854775807:
                raise LockError(.recursion_limit, 0)
            self._depth += 1
            return True
        var flags = _open_flags()
        if self._mode == .exclusive:
            flags |= _O_RDWR
        var fd = external_call["open", c_int, num_fixed_args=2](
            self._path.as_c_string_span(), c_int(flags), c_int(0o600)
        )
        if fd < 0:
            raise LockError(.system, _errno())
        var rc = external_call["flock", c_int](
            fd, c_int(self._mode._code | _LOCK_NB)
        )
        if rc != 0:
            var cause = _errno()
            _ = external_call["close", c_int](fd)
            if cause == _EWOULDBLOCK or cause == _EINTR:
                return False
            raise LockError(.system, cause)
        self._fd = fd
        self._depth = 1
        return True

    def acquire(mut self) raises LockError:
        """Acquire using the configured timeout, incrementing same-owner depth.
        """
        self.acquire(timeout=self._timeout)

    def acquire(mut self, *, timeout: Float64) raises LockError:
        """Override the wait: zero tries once, -1 waits indefinitely."""
        _validate_time(timeout, self._poll_interval)
        var start = perf_counter() if timeout > 0 else Float64(0)
        while not self.try_acquire():
            if timeout == 0:
                raise LockError(.timeout, 0)
            var delay = self._poll_interval
            if timeout > 0:
                var remaining = timeout - (perf_counter() - start)
                if remaining <= 0:
                    raise LockError(.timeout, 0)
                delay = min(delay, remaining)
            sleep(delay)

    def release(mut self) raises LockError:
        """Drop one recursion level; unlock and close when it reaches zero."""
        self._check_owner()
        if self._depth == 0:
            raise LockError(.not_held, 0)
        if self._depth > 1:
            self._depth -= 1
            return
        # Keep held state after failed unlock, so an explicit caller can retry.
        if external_call["flock", c_int](self._fd, c_int(_LOCK_UN)) != 0:
            raise LockError(.system, _errno())
        var fd = self._fd
        self._fd = -1
        self._depth = 0
        # close errors must not restore a lock that has already been unlocked.
        if external_call["close", c_int](fd) != 0:
            raise LockError(.system, _errno())

    def hold(mut self) -> ScopedFileLock[origin_of(self)]:
        """Borrow a context guard using this owner's configured timeout."""
        return ScopedFileLock(self, self._timeout)

    def hold(mut self, *, timeout: Float64) -> ScopedFileLock[origin_of(self)]:
        """Borrow a guard with an explicit acquisition timeout."""
        return ScopedFileLock(self, timeout)

    def try_hold(
        mut self,
    ) raises LockError -> Optional[HeldFileLock[origin_of(self)]]:
        """Try once and return an acquired guard, or None on contention/interruption.
        """
        try:
            return Optional(HeldFileLock(self, timeout=0))
        except e:
            if e.kind == .timeout:
                return None
            raise e

    def acquire_guard(
        mut self,
    ) raises -> HeldFileLock[origin_of(self)]:
        """Acquire now and return a guard owning exactly one recursion level."""
        return self.acquire_guard(timeout=self._timeout)

    def acquire_guard(
        mut self, *, timeout: Float64
    ) raises -> HeldFileLock[origin_of(self)]:
        """Acquire now with an explicit timeout and return its guard."""
        try:
            return HeldFileLock(self, timeout=timeout)
        except e:
            raise Error(String(e))

    def __enter__(mut self) raises:
        self.acquire()

    def __exit__(mut self) raises:
        self.release()


struct ScopedFileLock[origin: MutOrigin](Movable):
    """Borrowed context guard: its owner cannot move or die while it is live."""

    var _lock: Pointer[FileLock, Self.origin]
    var _timeout: Float64
    var _active: Bool

    def __init__(out self, ref[Self.origin] lock: FileLock, timeout: Float64):
        self._lock = Pointer(to=lock)
        self._timeout = timeout
        self._active = False

    def __deinit__(deinit self):
        if self._active:
            try:
                self._lock[].release()
            except:
                pass  # The owner still owns the descriptor; its cleanup is a fallback.

    def __enter__(mut self) raises:
        if self._active:
            raise Error("A ScopedFileLock cannot be entered twice")
        self._lock[].acquire(timeout=self._timeout)
        self._active = True

    def __exit__(mut self) raises:
        if not self._active:
            raise Error("A ScopedFileLock must be entered before exit")
        self._lock[].release()
        self._active = False


struct HeldFileLock[origin: MutOrigin](Movable):
    """An acquired, borrowed lock level; context entry performs no acquisition.

    Use it in a with-block to retain ownership through the protected work.
    Explicit release or context exit consumes its level once.
    """

    var _lock: Pointer[FileLock, Self.origin]
    var _active: Bool
    var _entered: Bool

    def __init__(
        out self, ref[Self.origin] lock: FileLock, *, timeout: Float64
    ) raises LockError:
        """Acquire one owner level now, borrowing its lifetime for this guard.
        """
        lock.acquire(timeout=timeout)
        self._lock = Pointer(to=lock)
        self._active = True
        self._entered = False

    def __deinit__(deinit self):
        if self._active:
            try:
                self._lock[].release()
            except:
                pass

    def is_active(self) -> Bool:
        """Whether this guard still owns its acquisition in the current process.
        """
        return self._active and self._lock[].is_locked()

    def release(mut self) raises LockError:
        """Release this guard's level; repeated release is an inactive-guard error.
        """
        if not self._active:
            raise LockError(.invalid_guard_state, 0)
        try:
            self._lock[].release()
        except e:
            if not self._lock[].is_locked():
                self._active = False
            raise e
        self._active = False

    def __enter__(mut self) raises:
        if not self._active or self._entered:
            raise LockError(.invalid_guard_state, 0)
        self._lock[]._check_owner()
        self._entered = True

    def __exit__(mut self) raises:
        if not self._entered:
            raise LockError(.invalid_guard_state, 0)
        self.release()
        self._entered = False
