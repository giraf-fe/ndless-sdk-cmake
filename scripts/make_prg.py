#!/usr/bin/env python3
"""
make_prg.py — Prepend a TI-Nspire Zehn loader to a Zehn executable.

Inspects the input `.zehn` header and relocation table to determine whether the
payload is zlib-compressed (`FILE_COMPRESSED` relocation type = 3), selects
either `zehn_loader_compressed.tns` or `zehn_loader.tns` from the script's
directory, and writes the concatenated `[loader + zehn]` output `.tns` file.
"""

import os
import struct
import sys

# Zehn binary format constants (little-endian)
ZEHN_SIGNATURE = 0x6E68655A  # "Zehn" in ASCII
ZEHN_VERSION = 1
ZEHN_HEADER_SIZE = 32
ZEHN_RELOC_FILE_COMPRESSED = 3


def is_zehn_compressed(zehn_data: bytes) -> bool:
    """
    Check whether a validated Zehn image begins with a FILE_COMPRESSED
    relocation entry.
    """
    reloc_count = struct.unpack_from("<I", zehn_data, 12)[0]
    if reloc_count > 0 and len(zehn_data) >= ZEHN_HEADER_SIZE + 4:
        # Relocation entries begin immediately after the 32-byte Zehn header.
        first_reloc = struct.unpack_from("<I", zehn_data, ZEHN_HEADER_SIZE)[0]
        # Low 8 bits encode the relocation type; 3 is FILE_COMPRESSED.
        reloc_type = first_reloc & 0xFF
        return reloc_type == ZEHN_RELOC_FILE_COMPRESSED
    return False


def main() -> None:
    # --------------------------------------------------------------------------
    # Step 1: Validate command-line arguments and input file existence
    # --------------------------------------------------------------------------
    if len(sys.argv) < 3:
        print("Usage: make_prg.py <input.zehn> <output.tns>")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found.", file=sys.stderr)
        sys.exit(1)

    # --------------------------------------------------------------------------
    # Step 2: Read and validate the Zehn header
    # --------------------------------------------------------------------------
    with open(input_path, "rb") as f:
        zehn_data = f.read()

    if len(zehn_data) < ZEHN_HEADER_SIZE:
        print("Error: Input file is too small to be a Zehn file.", file=sys.stderr)
        sys.exit(1)

    signature, version = struct.unpack_from("<II", zehn_data, 0)
    if signature != ZEHN_SIGNATURE or version != ZEHN_VERSION:
        print("Error: Input file is not a supported Zehn file.", file=sys.stderr)
        sys.exit(1)

    # --------------------------------------------------------------------------
    # Step 3: Detect compression and select the matching Zehn loader binary
    # --------------------------------------------------------------------------
    compressed = is_zehn_compressed(zehn_data)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    loader_name = "zehn_loader_compressed.tns" if compressed else "zehn_loader.tns"
    loader_path = os.path.join(script_dir, loader_name)

    if not os.path.exists(loader_path):
        print(f"Error: Loader file '{loader_path}' not found.", file=sys.stderr)
        sys.exit(1)

    with open(loader_path, "rb") as lf:
        loader_data = lf.read()

    # --------------------------------------------------------------------------
    # Step 4: Write the combined [loader + zehn] payload to the output .tns file
    # --------------------------------------------------------------------------
    with open(output_path, "wb") as out_f:
        out_f.write(loader_data)
        out_f.write(zehn_data)

    print(f"Successfully generated {output_path}")


if __name__ == "__main__":
    main()
