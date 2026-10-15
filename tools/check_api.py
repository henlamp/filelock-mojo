"""Check public declarations against the reviewed source-compatibility contract."""

from __future__ import annotations

import argparse
import json
import re

from _support import RELEASE_NAMES, ROOT, source_hash, write_report

MAGIC = {
    "__init__",
    "__len__",
    "__getitem__",
    "__enter__",
    "__exit__",
    "__deinit__",
    "__eq__",
    "__ne__",
    "__str__",
    "__bool__",
}


def public(name):
    return not name.startswith("_") or name in MAGIC


def snapshot(package):
    declarations = {}
    for path in sorted((ROOT / "src" / package).glob("*.mojo")):
        if path.stem.startswith("_"):
            continue
        lines = path.read_text().splitlines()
        owner = ""
        index = 0
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            indent = len(line) - len(line.lstrip())
            type_match = re.match(r"(?:struct|trait) (\w+)", stripped)
            func_match = re.match(r"def (\w+)", stripped)
            if indent == 0 and type_match:
                owner = type_match[1]
            match = type_match if indent == 0 else func_match
            if indent == 0 and func_match:
                owner = ""
                match = func_match
            if (
                match
                and indent in {0, 4}
                and public(match[1])
                and (not owner or public(owner))
            ):
                signature = [stripped]
                while not signature[-1].endswith(":"):
                    index += 1
                    signature.append(lines[index].strip())
                name = ".".join(
                    x for x in (path.stem, owner, match[1] if func_match else "") if x
                )
                declarations.setdefault(name, []).append(
                    " ".join(signature)[:-1].strip()
                )
            elif indent == 4 and owner and public(owner):
                member = re.match(r"(?:var|comptime) (\w+)\s*[:=]", stripped)
                if member and public(member[1]):
                    declarations.setdefault(
                        f"{path.stem}.{owner}.{member[1]}", []
                    ).append(stripped)
            index += 1
    init = (ROOT / "src" / package / "__init__.mojo").read_text()
    imports = re.findall(r"from\s+\.[\w]+\s+import\s+(\([^)]*\)|[^\n]+)", init, re.S)
    exports = sorted(
        {
            name.strip()
            for entry in imports
            for name in entry.strip("()").split(",")
            if name.strip()
        }
    )
    return {
        "compiler": "1.1.0",
        "api_version": "0.1",
        "exports": exports,
        "declarations": {k: sorted(v) for k, v in sorted(declarations.items())},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--record",
        action="store_true",
        help="Record an explicitly reviewed API revision",
    )
    args = parser.parse_args()
    checks = {}
    for package in RELEASE_NAMES:
        actual = snapshot(package)
        path = ROOT / "tests/api" / (package + ".json")
        if args.record:
            path.parent.mkdir(exist_ok=True)
            write_report(path, actual)
        expected = json.loads(path.read_text())
        if actual != expected:
            changed = sorted(
                set(actual["declarations"]) ^ set(expected["declarations"])
                | {
                    key
                    for key in actual["declarations"].keys()
                    & expected["declarations"].keys()
                    if actual["declarations"][key] != expected["declarations"][key]
                }
            )
            raise RuntimeError(
                f"Reviewed API differs for {package}: {changed}; review the compatibility impact before updating the baseline"
            )
        checks[package] = {
            "status": "passed",
            "public_exports": len(actual["exports"]),
            "public_declarations": len(actual["declarations"]),
            "source_sha256": source_hash(package),
        }
        print(f"{package}: reviewed declarations and exports match")
    write_report(ROOT / "tests/api-verification.json", checks)


if __name__ == "__main__":
    main()
