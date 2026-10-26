#!/usr/bin/env python3
"""
patch.py — Deterministic ELF patcher for POST_LINK integration testing.

Locates the `patch_marker` symbol in the target ARM ELF binary, adds an integer
delta to its 32-bit little-endian value in-place, and appends the delta to
`patch.log` in the current working directory.
"""

from pathlib import Path
import struct
import sys

from elftools.elf.elffile import ELFFile


def main() -> None:
    # Step 1: Parse command-line arguments (<elf-path> <integer-delta>).
    elf_path = Path(sys.argv[1])
    delta = int(sys.argv[2])

    # Step 2: Locate the file offset of the `patch_marker` symbol inside the ELF.
    with elf_path.open("rb") as stream:
        elf = ELFFile(stream)
        symtab = elf.get_section_by_name(".symtab")
        symbol = symtab.get_symbol_by_name("patch_marker")[0]
        section = elf.get_section(symbol["st_shndx"])
        file_offset = section["sh_offset"] + (symbol["st_value"] - section["sh_addr"])

    # Step 3: Increment the 32-bit little-endian integer at that offset.
    data = bytearray(elf_path.read_bytes())
    current_value = struct.unpack_from("<I", data, file_offset)[0]
    struct.pack_into("<I", data, file_offset, current_value + delta)
    elf_path.write_bytes(data)

    # Step 4: Record the applied patch step in patch.log for ordering assertions.
    with Path("patch.log").open("a", encoding="utf-8") as log:
        log.write(f"{delta}\n")


if __name__ == "__main__":
    main()
