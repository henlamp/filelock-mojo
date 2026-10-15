"""Coordinate cache generation from any cooperating Mojo/Python process."""
from std.sys import argv
from filelock_mojo import atomic_write


def main() raises:
    var args = argv()
    if len(args) != 2:
        raise Error("Usage: locked_cache.mojo OUTPUT_PATH")
    atomic_write(args[1], "Generated while holding a native inter-process lock.\n")
    print("Cache generation completed")
