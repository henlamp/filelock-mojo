"""Generate API references and execute the documented standalone examples."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path

from _support import BUILD, MOJO, PACKAGE_NAMES, ROOT, run, source_hash, write_report


def functions(declarations, label: str, lines: list[str]) -> int:
    count = 0
    for function in declarations:
        if function["name"].startswith("_"):
            continue
        for overload in function["overloads"]:
            summary = overload.get("summary", "").strip()
            if not summary:
                raise RuntimeError(f"Undocumented API: {label}.{function['name']}")
            lines.extend([f"```mojo\n{overload['signature']}\n```", summary, ""])
            count += 1
    return count


def main():
    output = BUILD / "docs"
    output.mkdir(exist_ok=True)
    results = {}
    for package in PACKAGE_NAMES:
        path = output / f"{package}.json"
        run(
            [
                MOJO,
                "doc",
                "--Werror",
                "-I",
                ROOT / "src",
                ROOT / "src" / package,
                "-o",
                path,
            ],
            package + "-docs",
        )
        declaration = json.loads(path.read_text())["decl"]
        lines = [f"# {package}", "", "Generated from the Mojo API docstrings.", ""]
        count = 0
        for module in declaration["modules"]:
            if module["name"].startswith("_"):
                continue
            count += functions(module["functions"], package, lines)
            for item in module["structs"] + module["traits"]:
                if item["name"].startswith("_"):
                    continue
                if not item.get("summary", "").strip():
                    raise RuntimeError(f"Undocumented type: {package}.{item['name']}")
                lines.extend(
                    [
                        f"## {item['name']}",
                        "",
                        item["summary"],
                        item.get("description", ""),
                        "",
                    ]
                )
                count += 1 + functions(
                    item["functions"], package + "." + item["name"], lines
                )
        (output / f"{package}.md").write_text("\n".join(lines))
        markdown = ROOT / "docs/libraries" / (package.replace("_", "-") + ".md")
        examples = re.findall(
            r"```mojo\n(.*?)```",
            markdown.read_text() + "\n" + (ROOT / "README.md").read_text(),
            flags=re.DOTALL,
        )
        if not examples:
            raise RuntimeError(f"No executable documentation example: {package}")
        for number, source in enumerate(examples):
            with tempfile.TemporaryDirectory(
                prefix="doc-example-", dir=BUILD
            ) as directory:
                work = Path(directory)
                fixture = work / "example.mojo"
                fixture.write_text(source)
                run(
                    [MOJO, "run", "--Werror", "-I", ROOT / "src", fixture],
                    f"{package}-doc-example-{number}",
                    cwd=work,
                )
        results[package] = {
            "api_declarations": count,
            "executed_examples": len(examples),
            "source_sha256": source_hash(package),
            "documentation_sha256": hashlib.sha256(markdown.read_bytes()).hexdigest(),
        }
        print(
            f"{package}: {count} API declarations documented; {len(examples)} example(s) executed",
            flush=True,
        )
    write_report(ROOT / "tests/documentation-verification.json", results)


if __name__ == "__main__":
    main()
