# SPDX-FileCopyrightText: 2026 henlamp
# SPDX-License-Identifier: MIT
"""Exercise real atomic publication and shared reads from separate processes."""
from std.sys import argv
from filelock_mojo import atomic_write, locked_read


def main() raises:
    var args = argv()
    if len(args) < 3:
        raise Error("atomic_worker MODE PATH [CONTENT]")
    var mode = args[1]
    var path = args[2]
    if mode == "write":
        atomic_write(path, args[3])
    elif mode == "read":
        print(locked_read(path, Int(args[3])))
    elif mode == "large":
        var text = String()
        var block = String()
        for _ in range(4096):
            block += "x"
        for _ in range(16384):
            text += block
        atomic_write(path, text)
    else:
        raise Error("Unknown atomic worker mode")
