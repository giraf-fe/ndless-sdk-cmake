#!/usr/bin/env python3
"""
test_tools.py — Unit tests for Ndless SDK Python helper scripts.

Covers:
  1. Zehn 32-bit bitfield packing and unpacking (`genzehn.py`).
  2. Null-terminated UTF-8 string encoding/decoding in Zehn extra data (`genzehn.py`).
  3. `POST_LINK` `COMMAND`-delimited argument list splitting (`package_program.py`).
  4. Syscall stub generation for regular, spaced-return-type, 5+ argument, and
     variadic signatures (`mkStubs.py`).
  5. Compressed vs. uncompressed Zehn loader prepending (`make_prg.py`).
"""

import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> ModuleType:
    """Dynamically import a script module from `scripts/<name>.py`."""
    script_path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ToolTests(unittest.TestCase):
    def test_zehn_entry_round_trip(self) -> None:
        """Verify 8-bit type and 24-bit data/offset bitfields pack and unpack losslessly."""
        tool = load("genzehn")
        test_cases = (
            (0, 0),
            (3, 0),
            (255, 0xFFFFFF),
            (1, 0x123456),
        )
        for kind, value in test_cases:
            packed = tool.pack_zehn_entry(kind, value)
            self.assertEqual(tool.unpack_zehn_entry(packed), (kind, value))

    def test_utf8_extra_string(self) -> None:
        """Verify UTF-8 strings are null-terminated and retrieved at their byte offset."""
        tool = load("genzehn")
        extra = bytearray()

        # Step 1: Append a UTF-8 string containing a multibyte character.
        offset = tool.zehn_extra_string("Ndless café", extra)

        # Step 2: Read the string back from the extra-data buffer.
        self.assertEqual(tool.zehn_get_string(offset, bytes(extra)), "Ndless café")

    def test_split_commands(self) -> None:
        """Verify POST_LINK command lists split on 'COMMAND' and reject empty segments."""
        tool = load("package_program")

        # Step 1: Empty input yields no commands.
        self.assertEqual(tool.split_commands([]), [])

        # Step 2: Multiple commands separated by COMMAND preserve internal spaces.
        raw_args = ["python", "a file.py", "COMMAND", "cmake", "-E", "echo", "x"]
        expected = [["python", "a file.py"], ["cmake", "-E", "echo", "x"]]
        self.assertEqual(tool.split_commands(raw_args), expected)

        # Step 3: Leading, trailing, or standalone COMMAND tokens raise ValueError.
        for invalid_args in (["COMMAND"], ["python", "COMMAND"], ["COMMAND", "python"]):
            with self.assertRaises(ValueError):
                tool.split_commands(invalid_args)

    def test_stub_whitespace_and_naked_wrappers(self) -> None:
        """Verify mkStubs.py handles parenthesized return types, 5+ args, and variadics."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)

            # Step 1: Write a synthetic syscall-list.h covering all stub forms.
            source = directory / "syscall-list.h"
            source.write_text(
                """// START_OF_LIST
#define e_regular 1 // int regular(int p1)
#define e_space 2 // (const char*) spaced (int p1)
#define e_many 3 // int many(int p1, int p2, int p3, int p4, int p5)
#define e_variadic 4 // int variable(int p1, ...)
// END_OF_LIST
""",
                encoding="utf-8",
            )

            # Step 2: Run mkStubs.py to generate declarations and C++ stub wrappers.
            header = directory / "include" / "declarations.h"
            stubs = directory / "src" / "stubs.cpp"
            subprocess.run(
                [sys.executable, ROOT / "scripts" / "mkStubs.py", source, header, stubs],
                check=True,
            )

            # Step 3: Verify generated prototype and wrapper forms.
            declarations = header.read_text(encoding="utf-8")
            generated = stubs.read_text(encoding="utf-8")
            self.assertIn("const char* spaced(int p1);", declarations)
            self.assertIn("return syscall<e_space, const char*>(p1);", generated)
            self.assertIn("__attribute__((naked)) int many", generated)
            self.assertIn("__attribute__((naked)) int variable", generated)

    def test_loader_selection_and_missing_loader(self) -> None:
        """Verify make_prg.py selects the matching loader and fails if it is missing."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)

            # Step 1: Stage make_prg.py and mock loader binaries in a temp dir.
            script = directory / "make_prg.py"
            script.write_bytes((ROOT / "scripts" / "make_prg.py").read_bytes())
            (directory / "zehn_loader.tns").write_bytes(b"plain-loader")
            (directory / "zehn_loader_compressed.tns").write_bytes(b"compressed-loader")

            source = directory / "input.zehn"
            output = directory / "output.tns"

            # Step 2: Verify both uncompressed (reloc 0) and compressed (reloc 3)
            #         Zehn inputs prepend the appropriate loader.
            for compressed in (False, True):
                header = struct.pack("<8I", 0x6E68655A, 1, 36, 1, 0, 0, 36, 0)
                zehn = header + struct.pack("<I", 3 if compressed else 0)
                source.write_bytes(zehn)

                subprocess.run([sys.executable, script, source, output], check=True)
                expected_loader = b"compressed-loader" if compressed else b"plain-loader"
                self.assertEqual(output.read_bytes(), expected_loader + zehn)

            # Step 3: Remove the compressed loader and verify make_prg.py fails cleanly.
            (directory / "zehn_loader_compressed.tns").unlink()
            result = subprocess.run(
                [sys.executable, script, source, output],
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
