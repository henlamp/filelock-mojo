# SPDX-License-Identifier: MIT
"""Bounded concurrent counter and deterministic lost-update control."""
from std.collections import List, Optional
from std.ffi import external_call, c_int, CStringSpan
from std.origin import ImmutAnyOrigin
from std.os.process import Process
from std.os.path import exists
from std.sys import argv
from std.time import perf_counter, sleep
from std.testing import assert_equal, assert_true


struct Workers(Movable):
    var children: List[Process]

    def __init__(out self):
        self.children = List[Process]()

    def __deinit__(deinit self):
        for i in range(len(self.children)):
            try:
                if not self.children[i].poll().has_exited():
                    _ = self.children[i].kill()
                _ = self.children[i].wait()
            except:
                pass

    def spawn(mut self, var executable: String, var args: List[String]) raises:
        # Keep each C string alive; the child calls only execv or _exit.
        var path = executable.as_c_string_span()
        var pointers = List[Optional[CStringSpan[ImmutAnyOrigin]]](
            length=len(args) + 2, fill={}
        )
        pointers[0] = rebind[CStringSpan[ImmutAnyOrigin]](path)
        for i in range(len(args)):
            pointers[i + 1] = rebind[CStringSpan[ImmutAnyOrigin]](
                args[i].as_c_string_span()
            )
        var pid = external_call["fork", c_int]()
        if pid < 0:
            raise Error("fork failed")
        if pid == 0:
            _ = external_call["execv", c_int](path, pointers.unsafe_ptr())
            external_call["_exit", NoneType](c_int(127))
        self.children.append(Process(child_pid=Int(pid)))

    def join(mut self) raises:
        for i in range(len(self.children)):
            var deadline = perf_counter() + 20
            var status = self.children[i].poll()
            while not status.has_exited():
                if perf_counter() > deadline:
                    raise Error("Native counter worker timed out")
                sleep(0.001)
                status = self.children[i].poll()
            assert_true(Bool(status.exit_code), "worker terminated by signal")
            assert_equal(status.exit_code.value(), 0, "worker failed")

    def ready(mut self, index: Int, marker: String) raises:
        var deadline = perf_counter() + 5
        while not exists(marker):
            if (
                self.children[index].poll().has_exited()
                or perf_counter() > deadline
            ):
                raise Error("Native worker did not become ready")
            sleep(0.005)


def write(path: String, text: String) raises:
    with open(path, "w") as output:
        output.write(text)


def read(path: String) raises -> Int:
    with open(path, "r") as input:
        return Int(input.read())


def main() raises:
    var args = argv()
    assert_equal(len(args), 6, "WORKER DIRECTORY LOCK ROUNDS WORKERS")
    var executable = args[1]
    var root = args[2]
    var rounds = Int(args[4])
    var count = Int(args[5])
    assert_true(rounds > 0 and count > 0)
    var lock = args[3]
    var data = root + "/native-counter.txt"
    write(data, "0")
    for _ in range(rounds):
        var workers = Workers()
        for _ in range(count):
            workers.spawn(executable, ["counter", lock, data])
        workers.join()
    var expected = rounds * count * 120
    assert_equal(read(data), expected, "lost or duplicated protected updates")
    # Preserve the counter for the independent parent-process observation.
    data = root + "/native-racy.txt"
    # Force both unlocked children to read before either may write.
    write(data, "0")
    var gate = root + "/native-racy.go"
    var workers = Workers()
    for i in range(2):
        workers.spawn(
            executable,
            ["racy", lock, data, root + "/native-racy-" + String(i), gate],
        )
    for i in range(2):
        workers.ready(i, root + "/native-racy-" + String(i))
    write(gate, "go")
    workers.join()
    assert_equal(read(data), 1, "negative control must expose a lost update")
    print(
        '{"protected_updates":',
        expected,
        ',"process_runs":',
        rounds * count,
        ',"unlocked_negative_control":1}',
    )
