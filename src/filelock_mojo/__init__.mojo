# SPDX-FileCopyrightText: 2026 henlamp
# SPDX-License-Identifier: MIT

"""Native kernel-backed inter-process locks for Mojo 1.1."""
from .locking import (
    FileLock,
    ScopedFileLock,
    HeldFileLock,
    LockMode,
    LockError,
    LockErrorKind,
)
from .readwrite import ReadWriteLock
from .atomic import atomic_write, locked_read
