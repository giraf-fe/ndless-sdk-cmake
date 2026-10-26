#!/usr/bin/env python3
"""
package_program.py — Stage, patch, and package an ARM ELF into a TI-Nspire .tns.

Copies the linker's output ELF into a private temporary staging directory before
running optional POST_LINK patch commands, `genzehn.py`, and `make_prg.py`.
This guarantees that:
  1. The original linked ELF is never mutated in-place (rebuilds never stack
     patches on an already-patched ELF).
  2. A failing POST_LINK command or conversion step leaves both the original ELF
     and any previously packaged .tns file intact.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import List, Sequence, Tuple


def split_commands(arguments: Sequence[str]) -> List[List[str]]:
    """
    Split a flat argument list on 'COMMAND' separators into discrete commands.

    Raises ValueError if any command segment is empty (leading, consecutive, or
    trailing 'COMMAND' tokens).
    """
    commands: List[List[str]] = []
    current_command: List[str] = []

    for arg in arguments:
        if arg == "COMMAND":
            if not current_command:
                raise ValueError("Empty POST_LINK command")
            commands.append(current_command)
            current_command = []
        else:
            current_command.append(arg)

    if current_command:
        commands.append(current_command)
    elif arguments:
        raise ValueError("Empty trailing POST_LINK command")

    return commands


def load_flags_and_commands(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    tail: Sequence[str],
) -> Tuple[List[str], List[List[str]]]:
    """
    Extract genzehn flags and POST_LINK commands from either the CMake-generated
    JSON file (--arguments-json) or trailing command-line arguments (--).
    """
    if args.arguments_json:
        if tail:
            parser.error("Cannot combine --arguments-json with trailing commands")
        payload = json.loads(args.arguments_json.read_text(encoding="utf-8"))
        flags = list(payload["flags"])
        commands = split_commands(payload["commands"])
        return flags, commands

    if not 0 <= args.genzehn_count <= len(tail):
        parser.error("Invalid genzehn argument count")

    flags = list(tail[: args.genzehn_count])
    commands = split_commands(tail[args.genzehn_count :])
    return flags, commands


def main() -> None:
    # --------------------------------------------------------------------------
    # Step 1: Parse command-line arguments
    # --------------------------------------------------------------------------
    # JSON is used by CMake to avoid interpreting user command arguments as
    # add_custom_command keywords. The `--` separator form supports direct CLI tests.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Path to linked ARM ELF input")
    parser.add_argument("--output", required=True, type=Path, help="Output .tns path")
    parser.add_argument("--tool-dir", required=True, type=Path, help="SDK bin/ directory")
    parser.add_argument("--arguments-json", type=Path, help="JSON file with flags and commands")
    parser.add_argument("--genzehn-count", type=int, default=0, help="Number of leading tail args for genzehn")

    boundary = sys.argv.index("--") if "--" in sys.argv else len(sys.argv)
    args = parser.parse_args(sys.argv[1:boundary])
    tail = sys.argv[boundary + 1 :]

    flags, commands = load_flags_and_commands(parser, args, tail)

    # --------------------------------------------------------------------------
    # Step 2: Resolve file paths and prepare output directory
    # --------------------------------------------------------------------------
    original_elf = Path(args.input).resolve()
    output_tns = args.output.resolve()
    tools_dir = args.tool_dir.resolve()
    output_tns.parent.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------------------
    # Step 3: Stage a private copy of the ELF in a temporary directory
    # --------------------------------------------------------------------------
    with tempfile.TemporaryDirectory(prefix=".ndless-", dir=output_tns.parent) as temp_dir:
        temp_path = Path(temp_dir)
        staged_elf = temp_path / original_elf.name
        shutil.copy2(original_elf, staged_elf)

        # ----------------------------------------------------------------------
        # Step 4: Execute POST_LINK commands against the private ELF copy
        # ----------------------------------------------------------------------
        # Substitute occurrences of the original $<TARGET_FILE:...> string with
        # the staged copy path (also works inside flags like --input=<path>).
        for command in commands:
            staged_command = [arg.replace(args.input, str(staged_elf)) for arg in command]
            subprocess.run(staged_command, check=True)

        # ----------------------------------------------------------------------
        # Step 5: Convert the staged ELF into a Zehn binary via genzehn.py
        # ----------------------------------------------------------------------
        staged_zehn = temp_path / "program.zehn"
        subprocess.run(
            [
                sys.executable,
                str(tools_dir / "genzehn.py"),
                "--input",
                str(staged_elf),
                "--output",
                str(staged_zehn),
                *flags,
            ],
            check=True,
        )

        # ----------------------------------------------------------------------
        # Step 6: Prepend the Zehn loader via make_prg.py to create a .tns
        # ----------------------------------------------------------------------
        staged_tns = temp_path / "program.tns"
        subprocess.run(
            [
                sys.executable,
                str(tools_dir / "make_prg.py"),
                str(staged_zehn),
                str(staged_tns),
            ],
            check=True,
        )

        # ----------------------------------------------------------------------
        # Step 7: Atomically move the completed .tns into its final destination
        # ----------------------------------------------------------------------
        os.replace(staged_tns, output_tns)


if __name__ == "__main__":
    main()
