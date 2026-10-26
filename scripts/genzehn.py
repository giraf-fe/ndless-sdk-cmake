#!/usr/bin/env python3
"""
genzehn.py – Python rewrite of genzehn.cpp (genzehn 1.5.2 by Fabian Vogt)

Converts ARM ELF executables into the Zehn format used by Ndless on TI-Nspire
calculators. Supports both generating Zehn files from ELF inputs and inspecting
existing Zehn files.

Requirements:
    pip install pyelftools
"""

import argparse
from enum import IntEnum
import struct
import sys
from typing import List, Set, Tuple
import zlib

# ---------------------------------------------------------------------------
# Zehn format constants and types (from zehn.h)
# ---------------------------------------------------------------------------

ZEHN_SIGNATURE = 0x6E68655A  # "Zehn" in little-endian ASCII
ZEHN_VERSION = 1

# struct Zehn_header – 8 × uint32_t = 32 bytes, little-endian, packed:
#   signature, version, file_size, reloc_count,
#   flag_count, extra_size, alloc_size, entry_offset
ZEHN_HEADER_FMT = "<IIIIIIII"
ZEHN_HEADER_SIZE = struct.calcsize(ZEHN_HEADER_FMT)

# Zehn_reloc and Zehn_flag are both packed 32-bit bitfields:
#   type : 8 bits (low byte)  |  offset/data : 24 bits (high 3 bytes)
# Stored as a single little-endian uint32.
ZEHN_ENTRY_FMT = "<I"
ZEHN_ENTRY_SIZE = 4


class ZehnRelocType(IntEnum):
    ADD_BASE = 0         # Add base address of executable
    ADD_BASE_GOT = 1     # Add base until 0xFFFFFFFF sentinel
    SET_ZERO = 2         # Set value to 0 (undo GOT relocs for undef symbols)
    FILE_COMPRESSED = 3  # File is compressed; offset is ZehnCompressType
    UNALIGNED_RELOC = 4  # Marker: at least one unaligned relocation exists


class ZehnCompressType(IntEnum):
    ZLIB = 0


class ZehnFlagType(IntEnum):
    NDLESS_VERSION_MIN = 0
    NDLESS_VERSION_MAX = 1
    NDLESS_REVISION_MIN = 2
    NDLESS_REVISION_MAX = 3
    RUNS_ON_COLOR = 4
    RUNS_ON_CLICKPAD = 5
    RUNS_ON_TOUCHPAD = 6
    RUNS_ON_32MB = 7
    EXECUTABLE_NAME = 8
    EXECUTABLE_AUTHOR = 9
    EXECUTABLE_VERSION = 10
    EXECUTABLE_NOTICE = 11
    RUNS_ON_HWW = 12
    USES_LCD_BLIT = 13


# ELF constants not always exported by pyelftools
EM_ARM = 40
SHT_SYMTAB = 2
SHT_REL = 9
SHT_RELA = 4
SHT_NOBITS = 8
SHF_ALLOC = 0x2
STB_WEAK = 2
STT_NOTYPE = 0
SHN_UNDEF = 0

# ARM relocation types
R_ARM_ABS32 = 2
R_ARM_GOT_BREL = 26
R_ARM_TARGET1 = 38


# ---------------------------------------------------------------------------
# Helper: pack / unpack a Zehn entry (reloc or flag) bitfield
# ---------------------------------------------------------------------------

def pack_zehn_entry(type_val: int, data_val: int) -> bytes:
    """Pack an 8-bit type and 24-bit data/offset into 4 LE bytes."""
    word = (type_val & 0xFF) | ((data_val & 0x00FFFFFF) << 8)
    return struct.pack("<I", word)


def unpack_zehn_entry(raw: bytes) -> Tuple[int, int]:
    """Unpack 4 LE bytes into (type, data/offset)."""
    word = struct.unpack("<I", raw)[0]
    return (word & 0xFF, (word >> 8) & 0x00FFFFFF)


# ---------------------------------------------------------------------------
# Extra-data string helpers (null-terminated strings in a bytearray)
# ---------------------------------------------------------------------------

def zehn_extra_string(s: str, extra_data: bytearray) -> int:
    """Append *s* (null-terminated UTF-8) to *extra_data*; return its start offset."""
    pos = len(extra_data)
    extra_data.extend(s.encode("utf-8"))
    extra_data.append(0)
    return pos


def zehn_get_string(pos: int, extra_data: bytes) -> str:
    """Read a null-terminated UTF-8 string starting at *pos* in *extra_data*."""
    if pos > len(extra_data) - 1:
        return "<invalid>"
    end = extra_data.index(0, pos) if 0 in extra_data[pos:] else len(extra_data)
    return extra_data[pos:end].decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# --info mode: inspect an existing Zehn or .tns file
# ---------------------------------------------------------------------------

def do_info(input_path: str) -> int:
    # Step 1: Read the initial prefix buffer (up to 20 KiB) to scan for the
    #         Zehn header signature (skipping any prepended loader binary).
    try:
        with open(input_path, "rb") as f:
            buf = f.read(5120 * 4)
    except OSError:
        print(f"Failed to load '{input_path}'!", file=sys.stderr)
        return 1

    if len(buf) == 0:
        print(f"Failed to load '{input_path}'!", file=sys.stderr)
        return 1

    # Step 2: Locate the (ZEHN_SIGNATURE, ZEHN_VERSION) uint32 pair.
    words = struct.unpack(f"<{len(buf) // 4}I", buf[: len(buf) // 4 * 4])
    zehn_start = -1
    for i in range(len(words) - 1):
        if words[i] == ZEHN_SIGNATURE and words[i + 1] == ZEHN_VERSION:
            zehn_start = i * 4
            break

    if zehn_start == -1:
        print("Input is not a supported Zehn file!", file=sys.stderr)
        return 1

    # Step 3: Read the complete Zehn image starting at the discovered offset.
    try:
        with open(input_path, "rb") as f:
            f.seek(zehn_start)
            rest = f.read()
    except OSError:
        print("Failed to read header!", file=sys.stderr)
        return 1

    if len(rest) < ZEHN_HEADER_SIZE:
        print("Failed to read header!", file=sys.stderr)
        return 1

    # Step 4: Unpack and print the Zehn header fields.
    (
        _signature,
        _version,
        file_size,
        reloc_count,
        flag_count,
        extra_size,
        alloc_size,
        entry_offset,
    ) = struct.unpack(ZEHN_HEADER_FMT, rest[:ZEHN_HEADER_SIZE])

    print(f"Zehn header starts at byte 0x{zehn_start:x}")
    print(f"{reloc_count}\trelocations")
    print(f"{flag_count}\tflags")
    print(f"{extra_size}\tbytes extra data")
    print(f"{alloc_size}\tbytes needed to load this file")
    print(f"{file_size}\tbytes Zehn executable file")
    print(f"Entry point:\t0x{entry_offset:x}")

    # Step 5: Unpack the relocation table, flag table, and extra string data.
    offset = ZEHN_HEADER_SIZE
    relocs_raw = rest[offset : offset + ZEHN_ENTRY_SIZE * reloc_count]
    offset += ZEHN_ENTRY_SIZE * reloc_count
    relocs = [unpack_zehn_entry(relocs_raw[i : i + 4]) for i in range(0, len(relocs_raw), 4)]

    flags_raw = rest[offset : offset + ZEHN_ENTRY_SIZE * flag_count]
    offset += ZEHN_ENTRY_SIZE * flag_count
    flags = [unpack_zehn_entry(flags_raw[i : i + 4]) for i in range(0, len(flags_raw), 4)]

    extra_data = rest[offset : offset + extra_size]

    if reloc_count > 0 and relocs[0][0] == ZehnRelocType.FILE_COMPRESSED:
        print(f"This file is compressed (type {relocs[0][1]})")

    # Step 6: Display human-readable application metadata flags.
    print()
    for ftype, fdata in flags:
        if ftype == ZehnFlagType.EXECUTABLE_NAME:
            print(f"Application: {zehn_get_string(fdata, extra_data)}")
        elif ftype == ZehnFlagType.EXECUTABLE_VERSION:
            print(f"Version: {fdata}")
        elif ftype == ZehnFlagType.EXECUTABLE_AUTHOR:
            print(f"Author: {zehn_get_string(fdata, extra_data)}")
        elif ftype == ZehnFlagType.EXECUTABLE_NOTICE:
            print(f"Notice: {zehn_get_string(fdata, extra_data)}")
        elif ftype in (
            ZehnFlagType.NDLESS_VERSION_MAX,
            ZehnFlagType.NDLESS_VERSION_MIN,
            ZehnFlagType.NDLESS_REVISION_MAX,
            ZehnFlagType.NDLESS_REVISION_MIN,
            ZehnFlagType.RUNS_ON_32MB,
            ZehnFlagType.RUNS_ON_CLICKPAD,
            ZehnFlagType.RUNS_ON_COLOR,
            ZehnFlagType.RUNS_ON_TOUCHPAD,
        ):
            pass
        elif ftype == ZehnFlagType.RUNS_ON_HWW:
            if fdata:
                print("This executable supports the HW-W 240x320 LCD.")
        elif ftype == ZehnFlagType.USES_LCD_BLIT:
            if fdata:
                print("This executable uses the new lcd_blit API.")
        else:
            print(f"Unknown flag type {ftype}")

    return 0


# ---------------------------------------------------------------------------
# Generation mode: convert an ARM ELF executable into a Zehn binary
# ---------------------------------------------------------------------------

def do_generate(args: argparse.Namespace) -> int:
    try:
        from elftools.elf.elffile import ELFFile
        from elftools.elf.relocation import RelocationSection
        from elftools.elf.sections import SymbolTableSection
    except ImportError:
        print(
            "Error: pyelftools is required. Install with: pip install pyelftools",
            file=sys.stderr,
        )
        return 1

    verbose = args.verbose
    should_compress = args.compress

    # -----------------------------------------------------------------------
    # Step 1: Open and validate the ARM ELF input file
    # -----------------------------------------------------------------------
    try:
        elf_stream = open(args.input, "rb")
        elf = ELFFile(elf_stream)
    except Exception as e:
        print(f"Failed to load '{args.input}'! ({e})", file=sys.stderr)
        return 1

    if elf.header.e_machine != "EM_ARM":
        print("Input not for ARM!", file=sys.stderr)
        elf_stream.close()
        return 1

    # -----------------------------------------------------------------------
    # Step 2: Initialize Zehn output tables and populate metadata flags
    # -----------------------------------------------------------------------
    reloc_table: List[Tuple[int, int]] = []  # (type, offset)
    flag_table: List[Tuple[int, int]] = []   # (type, data)
    extra_data = bytearray()
    exec_data = bytearray()

    skipped_nobits = 0
    undefined_symbols: Set[int] = set()
    got_address = 0
    undo_relocs: Set[int] = set()

    entry_offset = elf.header.e_entry

    if verbose:
        print(f"Generating Zehn file, version {ZEHN_VERSION}.")
        print(f"Entry at 0x{entry_offset:x}.")

    if args.name is not None:
        flag_table.append((ZehnFlagType.EXECUTABLE_NAME, zehn_extra_string(args.name, extra_data)))
    if args.author is not None:
        flag_table.append((ZehnFlagType.EXECUTABLE_AUTHOR, zehn_extra_string(args.author, extra_data)))
    if args.version is not None:
        flag_table.append((ZehnFlagType.EXECUTABLE_VERSION, args.version))
    if args.notice is not None:
        flag_table.append((ZehnFlagType.EXECUTABLE_NOTICE, zehn_extra_string(args.notice, extra_data)))

    if args.ndless_min is not None:
        flag_table.append((ZehnFlagType.NDLESS_VERSION_MIN, args.ndless_min))
    if args.ndless_rev_min is not None:
        flag_table.append((ZehnFlagType.NDLESS_REVISION_MIN, args.ndless_rev_min))
    if args.ndless_max is not None:
        flag_table.append((ZehnFlagType.NDLESS_VERSION_MAX, args.ndless_max))
    if args.ndless_rev_max is not None:
        flag_table.append((ZehnFlagType.NDLESS_REVISION_MAX, args.ndless_rev_max))

    flag_table.append((ZehnFlagType.RUNS_ON_COLOR, int(args.color_support)))
    flag_table.append((ZehnFlagType.RUNS_ON_CLICKPAD, int(args.clickpad_support)))
    flag_table.append((ZehnFlagType.RUNS_ON_TOUCHPAD, int(args.touchpad_support)))
    flag_table.append((ZehnFlagType.RUNS_ON_32MB, int(args.support_32mb)))

    # -----------------------------------------------------------------------
    # Step 3: First pass — inspect symbols and pack SHF_ALLOC sections
    # -----------------------------------------------------------------------
    # libndls.h places _genzehn_new_lcd_api / _genzehn_old_lcd_api symbols into
    # the binary to indicate which screen API the program uses.
    using_old_lcd_api = False
    using_new_lcd_api = False

    for section in elf.iter_sections():
        if verbose:
            print(f"Section '{section.name}' has flags 0x{section['sh_flags']:x}.")

        # 3a. Scan symbol tables for undefined symbols and LCD API markers.
        if isinstance(section, SymbolTableSection):
            for sym_idx in range(section.num_symbols()):
                sym = section.get_symbol(sym_idx)
                name = sym.name
                bind = sym["st_info"]["bind"]
                stype = sym["st_info"]["type"]
                shndx = sym["st_shndx"]

                if name == "_genzehn_new_lcd_api":
                    using_new_lcd_api = True
                elif name == "_genzehn_old_lcd_api":
                    using_old_lcd_api = True

                if shndx == "SHN_UNDEF":
                    if bind != "STB_WEAK" and stype != "STT_NOTYPE":
                        print(
                            f"\tSymbol '{name}' isn't defined anywhere and not weak!",
                            file=sys.stderr,
                        )
                        elf_stream.close()
                        return 1
                    undefined_symbols.add(sym_idx)
                    if verbose:
                        print(f"\tSymbol '{name}' is undefined, but weak.")
            continue

        # 3b. Skip non-loadable sections (those without SHF_ALLOC).
        if not (section["sh_flags"] & SHF_ALLOC):
            if verbose:
                print("\tSkipping.")
            continue

        if section.name == ".got":
            got_address = section["sh_addr"]

        sh_addr = section["sh_addr"]
        sh_size = section["sh_size"]

        if verbose:
            print(f"\tIt will be placed at 0x{sh_addr:x} (size 0x{sh_size:x}).")

        # 3c. Verify section ordering and pad alignment gaps with zeros.
        if sh_addr < len(exec_data):
            print(f"\tSection '{section.name}' is overlapping!", file=sys.stderr)
            elf_stream.close()
            return 1
        elif sh_addr > len(exec_data):
            if verbose:
                print(
                    f"\tWarning: Section '{section.name}' not directly following! "
                    f"(is at 0x{sh_addr:x} but I'm currently at 0x{len(exec_data):x})",
                    file=sys.stderr,
                )
            exec_data.extend(b"\x00" * (sh_addr - len(exec_data)))

        # 3d. Handle NOBITS (.bss) sections without inflating file size unless requested.
        if section["sh_type"] == "SHT_NOBITS":
            if verbose:
                print(f"\tNOBITS section at 0x{sh_addr:x}.")
            if not args.include_bss:
                skipped_nobits = sh_size
            else:
                exec_data.extend(b"\x00" * sh_size)
            continue
        elif skipped_nobits != 0:
            print(
                f"\tWarning: NOBITS section (like .bss) not at the end! "
                f"({section.name} is after it)",
                file=sys.stderr,
            )
            exec_data.extend(b"\x00" * skipped_nobits)
            skipped_nobits = 0

        exec_data.extend(section.data())

    # -----------------------------------------------------------------------
    # Step 4: Determine LCD blit and 240x320 (HW-W) display support flags
    # -----------------------------------------------------------------------
    uses_lcd_blit = False
    if args.uses_lcd_blit is not None:
        uses_lcd_blit = args.uses_lcd_blit
    else:
        if using_old_lcd_api and using_new_lcd_api:
            print(
                "Warning: Using both the old (SCREEN_BASE_ADDRESS) and new (lcd_blit) API!",
                file=sys.stderr,
            )
            print("Assuming '--uses-lcd-blit false'!", file=sys.stderr)
        elif not using_old_lcd_api and not using_new_lcd_api:
            print(
                "Warning: Using neither old (SCREEN_BASE_ADDRESS) nor new (lcd_blit) API!",
                file=sys.stderr,
            )
            print("Assuming '--uses-lcd-blit false'!", file=sys.stderr)
        elif using_new_lcd_api:
            uses_lcd_blit = True

    flag_table.append((ZehnFlagType.USES_LCD_BLIT, int(uses_lcd_blit)))

    hww_compat = uses_lcd_blit
    if args.support_240x320 is not None:
        hww_compat = args.support_240x320

    if not hww_compat:
        print(
            "Warning: Your application does not appear to support 240x320px displays!",
            file=sys.stderr,
        )
        print("If it does, override with '--240x320-support true'.", file=sys.stderr)

    flag_table.append((ZehnFlagType.RUNS_ON_HWW, int(hww_compat)))

    # -----------------------------------------------------------------------
    # Step 5: Second pass — process .got and section relocations
    # -----------------------------------------------------------------------
    unaligned_reloc_found = False

    for section in elf.iter_sections():
        # 5a. Validate and record the Global Offset Table (.got) base relocation.
        if section.name == ".got":
            if verbose:
                print("Found .got section.")

            got_data = section.data()
            if len(got_data) < 4:
                print("Error: .got section too small!", file=sys.stderr)
                elf_stream.close()
                return 1

            last_word = struct.unpack("<I", got_data[-4:])[0]
            if last_word != 0xFFFFFFFF:
                print("Error: .got section doesn't end with 0xFFFFFFFF!", file=sys.stderr)
                elf_stream.close()
                return 1

            if section["sh_addr"] & 0b11:
                print("Error: .got section not aligned to 4-byte boundary!", file=sys.stderr)
                elf_stream.close()
                return 1

            reloc_table.append((ZehnRelocType.ADD_BASE_GOT, section["sh_addr"]))
            continue

        # 5b. Reject RELA relocations and skip non-relocation sections.
        if section["sh_type"] == "SHT_RELA":
            print("RELA type relocation is not supported!", file=sys.stderr)
            elf_stream.close()
            return 1

        if not isinstance(section, RelocationSection):
            continue

        # 5c. Only process relocations targeting loadable (SHF_ALLOC) sections.
        relocated_section_name = section.name[4:]  # strip ".rel" prefix
        need_to_reloc = False
        for s in elf.iter_sections():
            if s.name == relocated_section_name:
                need_to_reloc = bool(s["sh_flags"] & SHF_ALLOC)
                break

        if not need_to_reloc:
            if verbose:
                print(f"Skipping relocation section '{section.name}' as it will not be loaded.")
            continue

        entries_count = section.num_relocations()
        if verbose:
            print(f"Found relocation section '{section.name}' ({entries_count} entries).")

        # 5d. Translate each ARM relocation entry into a Zehn relocation entry.
        for rel_idx in range(entries_count):
            rel = section.get_relocation(rel_idx)
            r_offset = rel["r_offset"]
            r_info = rel["r_info"]
            r_sym = r_info >> 8     # ELF32_R_SYM
            r_type = r_info & 0xFF  # ELF32_R_TYPE

            if r_sym in undefined_symbols:
                if verbose:
                    print(f"\tSkipping relocation of 0x{r_offset:x}, because it's undefined.")

                if r_type == R_ARM_GOT_BREL:
                    # Undo reloc: the whole GOT is relocated by ADD_BASE_GOT, so
                    # entries for undefined weak symbols must be reset to 0.
                    got_entry_addr = struct.unpack_from("<I", exec_data, r_offset)[0]
                    target = got_address + got_entry_addr
                    if target not in undo_relocs:
                        undo_relocs.add(target)
                        if verbose:
                            print(f"\tUndo-reloc for 0x{target:x}.")
                continue

            if r_type in (R_ARM_ABS32, R_ARM_TARGET1):
                if verbose:
                    print(f"\tNeed Reloc at 0x{r_offset:x}.")

                if r_offset & 0b11:
                    if verbose:
                        print("\t\tReloc is unaligned.")
                    if not unaligned_reloc_found:
                        unaligned_reloc_found = True
                        reloc_table.append((ZehnRelocType.UNALIGNED_RELOC, 0))
                        if verbose:
                            print("\t\tUnaligned marker added.")

                reloc_table.append((ZehnRelocType.ADD_BASE, r_offset))

    # -----------------------------------------------------------------------
    # Step 6: Append GOT undo relocations, pad extra data, and compress
    # -----------------------------------------------------------------------
    for offset in sorted(undo_relocs):
        reloc_table.append((ZehnRelocType.SET_ZERO, offset))

    if len(extra_data) % 4 != 0:
        extra_data.extend(b"\x00" * (4 - len(extra_data) % 4))

    compressed_exec = b""
    if should_compress:
        if verbose:
            print("Compressing executable... ", end="")
        compressed_exec = zlib.compress(bytes(exec_data))
        reloc_table.insert(0, (ZehnRelocType.FILE_COMPRESSED, int(ZehnCompressType.ZLIB)))
        if verbose:
            print("done!")

    # -----------------------------------------------------------------------
    # Step 7: Compute final Zehn header sizes and write the output file
    # -----------------------------------------------------------------------
    reloc_count = len(reloc_table)
    flag_count = len(flag_table)
    extra_size = len(extra_data)

    file_size = (
        ZEHN_HEADER_SIZE
        + reloc_count * ZEHN_ENTRY_SIZE
        + flag_count * ZEHN_ENTRY_SIZE
        + extra_size
        + len(exec_data)
    )
    alloc_size = file_size + skipped_nobits

    if should_compress:
        file_size -= len(exec_data)
        file_size += len(compressed_exec)

    if verbose:
        print()
        print("Zehn creation succeeded:")
        print(f"\t{reloc_count}\trelocations")
        print(f"\t\t{len(undo_relocs)}\tundo-relocations")
        print(f"\t{flag_count}\tflags")
        print(f"\t{extra_size}\tbytes extra data")
        print(f"\t{alloc_size}\tbytes needed to load this file")
        print(f"\t{file_size}\tbytes Zehn executable file")
        if should_compress:
            print(f"\t{len(exec_data) - len(compressed_exec)}\tbytes saved by compression")

    try:
        with open(args.output, "wb") as out:
            out.write(
                struct.pack(
                    ZEHN_HEADER_FMT,
                    ZEHN_SIGNATURE,
                    ZEHN_VERSION,
                    file_size,
                    reloc_count,
                    flag_count,
                    extra_size,
                    alloc_size,
                    entry_offset,
                )
            )
            for rtype, roffset in reloc_table:
                out.write(pack_zehn_entry(rtype, roffset))
            for ftype, fdata in flag_table:
                out.write(pack_zehn_entry(ftype, fdata))
            out.write(bytes(extra_data))
            if should_compress:
                out.write(compressed_exec)
            else:
                out.write(bytes(exec_data))
    except OSError:
        print(f"Failed to open '{args.output}'", file=sys.stderr)
        elf_stream.close()
        return 2

    elf_stream.close()
    return 0


# ---------------------------------------------------------------------------
# Argument parsing (mirrors boost::program_options from the C++ version)
# ---------------------------------------------------------------------------

def str_to_bool(v: str) -> bool:
    """Parse a boolean value from a command-line string."""
    if v.lower() in ("true", "1", "yes"):
        return True
    if v.lower() in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError(f"Boolean value expected, got '{v}'")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="genzehn 1.5.2 by Fabian Vogt (Python port)"
    )

    # Required I/O paths
    parser.add_argument("--input", type=str, help="ELF input file")
    parser.add_argument("--output", type=str, help="Zehn output file")

    # Mode and metadata flags
    parser.add_argument("--info", action="store_true",
                        help="print information about a zehn file")
    parser.add_argument("--include-bss", action="store_true", dest="include_bss",
                        help="include the contents of the NOBITS sections in the file")
    parser.add_argument("--compress", action="store_true",
                        help="compress the executable's contents")
    parser.add_argument("--name", type=str, default=None,
                        help="executable name")
    parser.add_argument("--verbose", action="store_true",
                        help="output something, even if no error occurred")
    parser.add_argument("--author", type=str, default=None,
                        help="executable author")
    parser.add_argument("--version", type=int, default=1,
                        help="executable version (default: 1)")
    parser.add_argument("--notice", type=str, default=None,
                        help="executable notice")
    parser.add_argument("--ndless-min", type=int, default=None, dest="ndless_min",
                        help="min. ndless version * 10, e.g 3.1 = 31")
    parser.add_argument("--ndless-rev-min", type=int, default=None, dest="ndless_rev_min",
                        help="min. ndless revision")
    parser.add_argument("--ndless-max", type=int, default=None, dest="ndless_max",
                        help="max. ndless version * 10")
    parser.add_argument("--ndless-rev-max", type=int, default=None, dest="ndless_rev_max",
                        help="max. ndless revision")
    parser.add_argument("--color-support", type=str_to_bool, default=True,
                        dest="color_support",
                        help="Whether CX and CM are supported (default: true)")
    parser.add_argument("--clickpad-support", type=str_to_bool, default=True,
                        dest="clickpad_support",
                        help="Whether clickpads are supported (default: true)")
    parser.add_argument("--touchpad-support", type=str_to_bool, default=True,
                        dest="touchpad_support",
                        help="Whether touchpads (classic and CX/CM) are supported (default: true)")
    parser.add_argument("--32MB-support", type=str_to_bool, default=True,
                        dest="support_32mb",
                        help="Whether 32MB SDRAM is supported (default: true)")
    parser.add_argument("--240x320-support", type=str_to_bool, default=None,
                        dest="support_240x320",
                        help="Whether a 240x320x16 LCD (HW-W) is supported")
    parser.add_argument("--uses-lcd-blit", type=str_to_bool, default=None,
                        dest="uses_lcd_blit",
                        help="Whether the new lcd_blit API is being used")

    args = parser.parse_args()

    # Dispatch --info inspection mode
    if args.info:
        if not args.input:
            print(
                "You need to supply an input file: genzehn --info --input=file.tns",
                file=sys.stderr,
            )
            return 1
        return do_info(args.input)

    # Dispatch ELF -> Zehn generation mode
    if not args.input or not args.output:
        print("Input and output file names not provided!", file=sys.stderr)
        return 1

    return do_generate(args)


if __name__ == "__main__":
    sys.exit(main())
