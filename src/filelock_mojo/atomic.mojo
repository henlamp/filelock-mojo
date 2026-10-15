# SPDX-FileCopyrightText: 2026 henlamp
# SPDX-License-Identifier: MIT
"""Atomic text publication under a stable cooperating-process lock.

The temporary file is private and on the destination filesystem. Readers see
the old file until rename succeeds. The directory is not synced: this API does
not promise persistence across power failure. Use a trusted local directory.
"""
from std.collections import List
from std.ffi import c_int, c_ssize_t, external_call
from .locking import FileLock, _errno


def _path_bytes(path: String) raises -> List[UInt8]:
    if path.byte_length() == 0:
        raise Error("Atomic file path must not be empty")
    var data = List[UInt8](length=path.byte_length() + 1, fill=0)
    var i = 0
    for byte in path.bytes():
        if byte == 0:
            raise Error("Atomic file path must not contain NUL")
        data[i] = byte
        i += 1
    return data^


struct _Temporary(Movable):
    var _name: List[UInt8]
    var _fd: c_int
    var _published: Bool

    def __init__(out self, path: String) raises:
        self._name = _path_bytes(String(path, ".tmp-XXXXXX"))
        self._fd = -1
        self._published = False
        self._fd = external_call["mkstemp", c_int](self._name.unsafe_ptr())
        if self._fd < 0:
            raise Error(
                String("Cannot create atomic temporary: errno=", _errno())
            )
        if (
            external_call["fcntl", c_int, num_fixed_args=2](
                self._fd, c_int(2), c_int(1)
            )
            < 0
        ):
            raise Error(String("Cannot set close-on-exec: errno=", _errno()))

    def __deinit__(deinit self):
        if self._fd >= 0:
            _ = external_call["close", c_int](self._fd)
        if not self._published:
            _ = external_call["unlink", c_int](self._name.unsafe_ptr())

    def publish(mut self, path: String, content: String) raises:
        var bytes = content.as_bytes()
        var offset = 0
        while offset < len(bytes):
            var count = external_call["write", c_ssize_t](
                Int(self._fd),
                bytes.unsafe_ptr().unsafe_offset(offset),
                len(bytes) - offset,
            )
            if count < 0 and _errno() == 4:
                continue
            if count <= 0:
                raise Error(
                    String("Cannot write atomic temporary: errno=", _errno())
                )
            offset += Int(count)
        if external_call["fsync", c_int](self._fd) != 0:
            raise Error(
                String("Cannot sync atomic temporary: errno=", _errno())
            )
        var fd = self._fd
        self._fd = -1
        if external_call["close", c_int](fd) != 0:
            raise Error(
                String("Cannot close atomic temporary: errno=", _errno())
            )
        var destination = _path_bytes(path)
        if (
            external_call["rename", c_int](
                self._name.unsafe_ptr(), destination.unsafe_ptr()
            )
            != 0
        ):
            raise Error(String("Cannot publish atomic file: errno=", _errno()))
        self._published = True


def atomic_write(path: String, content: String, timeout: Float64 = 5) raises:
    """Replace UTF-8 text under path+'.lock'; publication is one atomic rename.

    A pre-publication failure preserves the previous file. A killed writer may
    leave an unreferenced temporary; other writers never reuse it. The lock marker
    must not be deleted. Publication replaces permissions with mode 0600.
    """
    _ = _path_bytes(path)
    with FileLock(String(path, ".lock"), timeout=timeout):
        var temporary = _Temporary(path)
        temporary.publish(path, content)


def locked_read(
    path: String, max_bytes: Int = 1048576, timeout: Float64 = 5
) raises -> String:
    """Read bounded UTF-8 text under the matching shared lock.

    Cooperating writers use atomic_write. A read beyond max_bytes fails; returned
    text owns its storage. Limits must be between zero and 64 MiB.
    """
    _ = _path_bytes(path)
    if max_bytes < 0 or max_bytes > 67108864:
        raise Error("Atomic read limit must be between zero and 64 MiB")
    with FileLock(String(path, ".lock"), mode=.shared, timeout=timeout):
        with open(path, "r") as source:
            var text = source.read(max_bytes + 1)
            if text.byte_length() > max_bytes:
                raise Error("Atomic file exceeds read limit")
            return text^
