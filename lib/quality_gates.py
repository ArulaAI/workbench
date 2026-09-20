"""Read executable Quality Gates configuration for both gates.sh and eval."""
from __future__ import annotations

import argparse
from pathlib import Path
import re


def read_gates(agent: Path) -> list[dict[str, str]]:
    gates = []
    in_section = False
    subsystem = ""
    fence = ""
    for raw in agent.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if fence:
            if line.startswith(fence) and set(line) == {fence[0]}:
                fence = ""
            continue
        opening = re.match(r"^(`{3,}|~{3,})", line)
        if opening:
            fence = opening[1]
            continue
        heading = re.match(r"^(#{1,6})(?:\s|$)", line)
        level = len(heading[1]) if heading else 0
        if not in_section:
            in_section = bool(re.match(r"^##\s+Quality\s+Gates\s*$", line, re.I))
            continue
        if level == 3:
            subsystem = line[3:].strip().lower()
            continue
        if level:
            break
        match = re.match(r"^(?:-\s*)?([A-Za-z_][A-Za-z_0-9-]*):\s*(.+)$", line)
        if match:
            gates.append({"gate": match[1], "subsystem": subsystem,
                          "command": match[2].strip().strip("`")})
    return gates


def gate_applies(row: dict, subsystem: str) -> bool:
    if not row["subsystem"] or subsystem == "both":
        return True
    return subsystem != "none" and subsystem == row["subsystem"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent_file", type=Path)
    parser.add_argument("gate")
    parser.add_argument("subsystem", nargs="?", default="both")
    args = parser.parse_args()
    for row in read_gates(args.agent_file):
        if row["gate"] == args.gate and gate_applies(row, args.subsystem):
            print(row["command"])


if __name__ == "__main__":
    main()
