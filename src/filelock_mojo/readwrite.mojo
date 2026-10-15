# SPDX-FileCopyrightText: 2026 henlamp
# SPDX-License-Identifier: MIT

"""One recursive owner that selects a read or write hold between acquisitions."""

from std.collections import Optional
from .locking import FileLock, LockMode, LockError, ScopedFileLock, HeldFileLock


struct ReadWriteLock(Movable):
    """Coordinate readers and writers on one stable Unix marker inode.

    Recursive holds keep their mode. Upgrades and downgrades are rejected.
    This owner belongs to one process and must not be shared between threads.
    """

    var _lock: FileLock

    def __init__(
        out self,
        path: String,
        *,
        timeout: Float64 = -1,
        poll_interval: Float64 = 0.01,
    ) raises LockError:
        """Configure the marker and wait policy for subsequent read/write holds.
        """
        self._lock = FileLock(
            path, timeout=timeout, poll_interval=poll_interval
        )

    def path(self) -> String:
        """Return the stable marker path."""
        return self._lock.path()

    def is_locked(self) -> Bool:
        """Whether this owner holds either mode in the current process."""
        return self._lock.is_locked()

    def is_read_locked(self) -> Bool:
        """Whether this owner holds a shared read lock."""
        return self.is_locked() and self._lock.mode() == .shared

    def is_write_locked(self) -> Bool:
        """Whether this owner holds an exclusive write lock."""
        return self.is_locked() and self._lock.mode() == .exclusive

    def lock_count(self) -> Int:
        """Return the current same-mode recursion depth."""
        return self._lock.lock_count()

    def _select(mut self, mode: LockMode) raises LockError:
        self._lock._check_owner()
        if self._lock._depth > 0 and self._lock._mode != mode:
            raise LockError(.mode_conflict, 0)
        self._lock._mode = mode

    def try_acquire_read(mut self) raises LockError -> Bool:
        """Try one shared acquisition; contention/interruption returns False."""
        self._select(.shared)
        return self._lock.try_acquire()

    def try_acquire_write(mut self) raises LockError -> Bool:
        """Try one exclusive acquisition; contention/interruption returns False.
        """
        self._select(.exclusive)
        return self._lock.try_acquire()

    def acquire_read(mut self) raises LockError:
        """Acquire a shared hold using the configured wait policy."""
        self._select(.shared)
        self._lock.acquire()

    def acquire_read(mut self, *, timeout: Float64) raises LockError:
        """Acquire a shared hold with an explicit wait timeout."""
        self._select(.shared)
        self._lock.acquire(timeout=timeout)

    def acquire_write(mut self) raises LockError:
        """Acquire an exclusive hold using the configured wait policy."""
        self._select(.exclusive)
        self._lock.acquire()

    def acquire_write(mut self, *, timeout: Float64) raises LockError:
        """Acquire an exclusive hold with an explicit wait timeout."""
        self._select(.exclusive)
        self._lock.acquire(timeout=timeout)

    def release(mut self) raises LockError:
        """Drop one recursion level and unlock when the depth reaches zero."""
        self._lock.release()

    def try_read(
        mut self,
    ) raises LockError -> Optional[HeldFileLock[origin_of(self._lock)]]:
        """Try a shared hold and return its acquired guard, or None on contention.
        """
        self._select(.shared)
        return self._lock.try_hold()

    def try_write(
        mut self,
    ) raises LockError -> Optional[HeldFileLock[origin_of(self._lock)]]:
        """Try an exclusive hold and return its acquired guard, or None on contention.
        """
        self._select(.exclusive)
        return self._lock.try_hold()

    def read(mut self) raises -> ScopedFileLock[origin_of(self._lock)]:
        """Borrow a read context guard with the configured wait policy."""
        self._select(.shared)
        return self._lock.hold()

    def read(
        mut self, *, timeout: Float64
    ) raises -> ScopedFileLock[origin_of(self._lock)]:
        """Borrow a read context guard with an explicit timeout."""
        self._select(.shared)
        return self._lock.hold(timeout=timeout)

    def write(mut self) raises -> ScopedFileLock[origin_of(self._lock)]:
        """Borrow a write context guard with the configured wait policy."""
        self._select(.exclusive)
        return self._lock.hold()

    def write(
        mut self, *, timeout: Float64
    ) raises -> ScopedFileLock[origin_of(self._lock)]:
        """Borrow a write context guard with an explicit timeout."""
        self._select(.exclusive)
        return self._lock.hold(timeout=timeout)
