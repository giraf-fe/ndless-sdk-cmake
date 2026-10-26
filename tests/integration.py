#!/usr/bin/env python3
"""
integration.py — End-to-end build, install, relocation, and incremental test suite.

Exercises the complete Ndless CMake SDK workflow on the host machine (ARM
binaries are inspected statically rather than executed on hardware):
  1. SDK build and installation from a source path containing spaces.
  2. Syscall stub coverage and missing-generated-file recovery.
  3. Building and validating all five upstream sample applications.
  4. Consumer C/C++/ASM compilation, startup object ordering, Zehn compression,
     metadata encoding, and non-mutating POST_LINK ELF patching.
  5. Incremental rebuilds (no-op rebuilds, deleted .tns recovery, patch script
     and converter timestamp dependencies, and failed patch rollback safety).
  6. SDK package relocation with original source/build trees unavailable, plus
     backward-compatible legacy `cmake/` discovery paths.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Set, Tuple
import zlib

from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[1]

ZEHN_SIGNATURE = 0x6E68655A
ZEHN_VERSION = 1
ZEHN_HEADER_SIZE = 32
ZEHN_RELOC_FILE_COMPRESSED = 3


# ==============================================================================
# Subprocess and Binary Inspection Helpers
# ==============================================================================

def run(*command: Any, cwd: Path | None = None, success: bool = True) -> str:
    """
    Execute a command, stream its combined stdout/stderr, and verify whether it
    succeeded (when `success=True`) or failed (when `success=False`).
    """
    print("+", " ".join(map(str, command)), flush=True)
    result = subprocess.run(
        list(map(str, command)),
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(result.stdout, end="", flush=True)

    if success and result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {command}")
    if not success and not result.returncode:
        raise AssertionError("Expected command failure, but it succeeded")

    return result.stdout


def inspect_tns(path: Path) -> Dict[str, Any]:
    """
    Validate a packaged `.tns` binary (loader + Zehn image) and return its
    parsed metadata, flags, and decompressed executable image.
    """
    data = path.read_bytes()
    signature = struct.pack("<II", ZEHN_SIGNATURE, ZEHN_VERSION)

    # Step 1: Scan past the prepended loader binary to find the Zehn header
    #         whose declared file_size matches the remaining byte count.
    start = data.find(signature)
    while start >= 0:
        if len(data) - start >= ZEHN_HEADER_SIZE:
            header = struct.unpack_from("<8I", data, start)
            if header[2] == len(data) - start:
                break
        start = data.find(signature, start + 1)

    assert start > 0, f"No valid loader + Zehn header found in: {path}"

    # Step 2: Unpack the 32-byte Zehn header, relocation table, flag table,
    #         extra string table, and executable payload.
    _, _, size, reloc_count, flag_count, extra_size, alloc_size, entry = header
    offset = start + ZEHN_HEADER_SIZE

    relocs = struct.unpack_from(f"<{reloc_count}I", data, offset)
    offset += reloc_count * 4

    flags = struct.unpack_from(f"<{flag_count}I", data, offset)
    offset += flag_count * 4

    extra = data[offset : offset + extra_size]
    image = data[offset + extra_size :]

    # Step 3: Decompress payload if the leading relocation is FILE_COMPRESSED.
    compressed = bool(relocs and (relocs[0] & 0xFF) == ZEHN_RELOC_FILE_COMPRESSED)
    if compressed:
        image = zlib.decompress(image)

    # Step 4: Validate entry point offset, allocation size, and relocations.
    assert entry < len(image)
    assert alloc_size >= ZEHN_HEADER_SIZE + 4 * (reloc_count + flag_count) + extra_size + len(image)
    assert reloc_count > 0

    return {
        "size": size,
        "compressed": compressed,
        "flags": {f & 0xFF: f >> 8 for f in flags},
        "extra": extra,
        "image": image,
    }


def elf_marker(path: Path) -> Tuple[int, int]:
    """
    Verify an ARM ELF executable's architecture, entry point, and C++ runtime
    hooks, and return the `(virtual_address, uint32_value)` of `patch_marker`.
    """
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        assert elf["e_machine"] == "EM_ARM"
        assert elf["e_entry"] == 0

        symbols = elf.get_section_by_name(".symtab")
        assert symbols.get_symbol_by_name("__cpp_init")
        assert symbols.get_symbol_by_name("__cpp_fini")

        symbol = symbols.get_symbol_by_name("patch_marker")[0]
        section = elf.get_section(symbol["st_shndx"])
        section_offset = symbol["st_value"] - section["sh_addr"]
        value = struct.unpack_from("<I", section.data(), section_offset)[0]
        return symbol["st_value"], value


def extract_syscall_ids(text: str) -> Set[str]:
    """Extract all `e_<name>` syscall identifiers from a `stubs.cpp` source string."""
    return set(re.findall(r'(?:syscall<|\[nr\] "i" \()(e_\w+)', text))


def ignore_repo_artifacts(directory: str, names: List[str]) -> List[str]:
    """
    shutil.copytree filter that excludes VCS metadata, caches, virtualenvs,
    upstream checkouts, and existing build/install directories.
    """
    ignored: List[str] = []
    is_root = Path(directory) == ROOT
    for name in names:
        if name in {".git", "__pycache__"}:
            ignored.append(name)
        elif is_root and (
            name in {"upstream", ".venv", ".vs", "test-results"}
            or name.startswith(("build", "install"))
        ):
            ignored.append(name)
    return ignored


# ==============================================================================
# Main Integration Test Workflow
# ==============================================================================

def main() -> None:
    # --------------------------------------------------------------------------
    # Step 1: Parse command-line arguments and initialize isolated workspace
    # --------------------------------------------------------------------------
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, type=Path, help="Path to upstream Ndless checkout")
    parser.add_argument("--work-dir", type=Path, help="Empty directory for test artifacts")
    parser.add_argument("--generator", default="Ninja", help="CMake generator to test")
    parser.add_argument("--config", default="Release", help="Build configuration (Release or Debug)")
    parser.add_argument("--toolchain-root", type=Path, help="Optional ARM GNU toolchain prefix")
    args = parser.parse_args()

    upstream = args.upstream.resolve()
    if args.work_dir:
        work = args.work_dir.resolve()
    else:
        runs = ROOT / "build" / "integration"
        runs.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="run-", dir=runs))

    # build/ is excluded from the source snapshot, so work directories under
    # build/ are safe without recursively copying the test run into itself.
    if work == ROOT or (ROOT in work.parents and ROOT / "build" not in work.parents):
        parser.error("Test work directory must be outside the source tree or below its build/ directory")

    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        parser.error(f"Test directory must be empty: {work}")

    # Confine subprocess temporary files to work/host-temp.
    temporary = work / "host-temp"
    temporary.mkdir()
    for env_name in ("TEMP", "TMP", "TMPDIR"):
        os.environ[env_name] = str(temporary)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    # Snapshot repository into a directory with spaces to test path quoting.
    source = work / "source with spaces"
    shutil.copytree(ROOT, source, ignore=ignore_repo_artifacts)

    consumer_source = work / "consumer source"
    shutil.copytree(ROOT / "tests" / "consumer", consumer_source)

    prefix = work / "installed sdk"
    sdk_build = work / "sdk build"
    samples_build = work / "sample build"
    consumer_build = work / "consumer build"

    config_args: Tuple[str, ...] = (
        "-G", args.generator,
        f"-DCMAKE_BUILD_TYPE={args.config}",
        "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF",
        "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF",
        f"-DPython3_EXECUTABLE={sys.executable}",
    )
    if args.toolchain_root:
        config_args += (f"-DNDLESS_TOOLCHAIN_ROOT={args.toolchain_root.resolve()}",)

    def configure(src: Path, build_dir: Path, toolchain_file: Path, install_dir: Path | None = None) -> None:
        run(
            "cmake",
            "-S", src,
            "-B", build_dir,
            *config_args,
            f"-DCMAKE_TOOLCHAIN_FILE={toolchain_file}",
            f"-DNDLESS_SOURCE_DIR={upstream}",
            f"-DCMAKE_PREFIX_PATH={install_dir or prefix}",
            f"-DCMAKE_INSTALL_PREFIX={prefix}",
        )

    def build(directory: Path) -> None:
        run("cmake", "--build", directory, "--config", args.config, "--parallel", "8")

    is_multi_config = "Multi-Config" in args.generator

    def artifacts(directory: Path) -> Path:
        return directory / args.config if is_multi_config else directory

    # --------------------------------------------------------------------------
    # Step 2: Build and install the SDK and verify syscall stub coverage
    # --------------------------------------------------------------------------
    upstream_before = run("git", "status", "--porcelain", cwd=upstream)

    configure(source, sdk_build, source / "cmake" / "TI-Nspire-Toolchain.cmake")
    build(sdk_build)
    run("cmake", "--install", sdk_build, "--config", args.config)

    assert upstream_before == run("git", "status", "--porcelain", cwd=upstream)

    generated_stubs = (sdk_build / "generated" / "stubs.cpp").read_text(encoding="utf-8")
    tracked_stubs = (upstream / "ndless-sdk" / "libsyscalls" / "stubs.cpp").read_text(encoding="utf-8")
    assert extract_syscall_ids(generated_stubs) == extract_syscall_ids(tracked_stubs), "Missing syscall wrappers"

    # --------------------------------------------------------------------------
    # Step 3: Verify build-graph recovery when generated outputs are removed
    # --------------------------------------------------------------------------
    (sdk_build / "generated" / "include" / "syscall-decls.h").unlink()
    loader_dir = artifacts(sdk_build / "loaders")
    (loader_dir / "zehn_loader_compressed.tns").unlink()

    build(sdk_build)
    assert (sdk_build / "generated" / "include" / "syscall-decls.h").is_file()
    assert (loader_dir / "zehn_loader_compressed.tns").is_file()
    run("cmake", "--install", sdk_build, "--config", args.config)

    # --------------------------------------------------------------------------
    # Step 4: Build and inspect all five upstream sample applications
    # --------------------------------------------------------------------------
    toolchain = prefix / "share" / "ndless" / "cmake" / "TI-Nspire-Toolchain.cmake"
    configure(source / "samples", samples_build, toolchain)
    build(samples_build)

    sample_names = ("helloworld-cpp", "helloworld-sdl", "newlib", "newlib-cpp", "ngc_demo")
    sample_sizes: Dict[str, int] = {}
    for name in sample_names:
        sample_tns = artifacts(samples_build) / f"{name}.tns"
        sample_sizes[name] = inspect_tns(sample_tns)["size"]

    # --------------------------------------------------------------------------
    # Step 5: Build consumer project and verify startup, metadata, and patching
    # --------------------------------------------------------------------------
    configure(consumer_source, consumer_build, toolchain)
    build(consumer_build)

    directory = artifacts(consumer_build)
    elf = directory / "basic.elf"
    tns = directory / "basic.tns"
    original_elf_bytes = elf.read_bytes()

    # 5a. Verify crt0.o startup code is placed at the beginning of .text.
    with (prefix / "system" / "crt0.o").open("rb") as stream:
        startup_bytes = ELFFile(stream).get_section_by_name(".text").data()[:8]
    with elf.open("rb") as stream:
        assert ELFFile(stream).get_section_by_name(".text").data()[:8] == startup_bytes

    # 5b. Verify POST_LINK patches modified the packaged .tns image (+1 + 2 = +3)
    #     without mutating the original linked ELF output.
    address, value = elf_marker(elf)
    assert value == 0x12345678, "POST_LINK must not mutate linker output"

    packaged = inspect_tns(tns)
    assert packaged["compressed"]
    assert struct.unpack_from("<I", packaged["image"], address)[0] == value + 3
    assert packaged["flags"][10] == 0 and packaged["flags"][0] == 0
    assert b"Portable test\x00" in packaged["extra"]
    assert not inspect_tns(directory / "constructors.tns")["compressed"]

    log = consumer_build / "patch.log"
    assert log.read_text(encoding="utf-8").splitlines() == ["1", "2"]

    # --------------------------------------------------------------------------
    # Step 6: Verify incremental rebuilds, dependency tracking, and rollback
    # --------------------------------------------------------------------------
    # 6a. No-change rebuild must be a no-op (all artifact mtimes unchanged).
    tracked = (elf, tns, log, directory / "constructors.tns")
    mtimes = [p.stat().st_mtime_ns for p in tracked]
    build(consumer_build)
    assert mtimes == [p.stat().st_mtime_ns for p in tracked], "No-change build was not a no-op"

    # 6b. Deleting basic.tns and rebuilding must repackage from the unmutated ELF.
    before_tns_bytes = tns.read_bytes()
    tns.unlink()
    build(consumer_build)
    assert tns.read_bytes() == before_tns_bytes and elf.read_bytes() == original_elf_bytes
    assert log.read_text(encoding="utf-8").splitlines() == ["1", "2"] * 2

    # 6c. Touching a POST_LINK dependency (patch.py) must trigger repackaging.
    time.sleep(1.1)  # Account for 1-second timestamp granularity on Unix Makefiles.
    (consumer_source / "patch.py").touch()
    build(consumer_build)
    assert log.read_text(encoding="utf-8").splitlines() == ["1", "2"] * 3
    assert elf.read_bytes() == original_elf_bytes

    # 6d. Touching an SDK packaging tool (genzehn.py) must trigger repackaging.
    time.sleep(1.1)
    (prefix / "bin" / "genzehn.py").touch()
    build(consumer_build)
    assert log.read_text(encoding="utf-8").splitlines() == ["1", "2"] * 4
    assert elf.read_bytes() == original_elf_bytes

    # 6e. A failing POST_LINK command must preserve both basic.elf and basic.tns.
    before_tns_bytes = tns.read_bytes()
    run(
        sys.executable,
        prefix / "bin" / "package_program.py",
        "--input", elf,
        "--output", tns,
        "--tool-dir", prefix / "bin",
        "--genzehn-count", "0",
        "--",
        sys.executable,
        "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'bad'); sys.exit(7)",
        elf,
        success=False,
    )
    assert elf.read_bytes() == original_elf_bytes and tns.read_bytes() == before_tns_bytes

    # --------------------------------------------------------------------------
    # Step 7: Verify SDK relocation and legacy CMake discovery paths
    # --------------------------------------------------------------------------
    # Move the installed SDK and rename the original SDK source and build trees
    # so any accidental reference to them fails immediately.
    relocated = work / "relocated sdk"
    prefix.rename(relocated)
    source.rename(work / "unavailable source")
    sdk_build.rename(work / "unavailable build")

    for cmake_config in (relocated / "lib" / "cmake" / "Ndless").glob("*.cmake"):
        content = cmake_config.read_text(encoding="utf-8").replace("\\", "/")
        assert source.as_posix() not in content and sdk_build.as_posix() not in content

    # 7a. Build consumer using the relocated SDK's standard layout.
    relocated_build = work / "relocated consumer"
    configure(
        consumer_source,
        relocated_build,
        relocated / "share" / "ndless" / "cmake" / "TI-Nspire-Toolchain.cmake",
        relocated,
    )
    build(relocated_build)
    inspect_tns(artifacts(relocated_build) / "basic.tns")

    # 7b. Build consumer using the legacy `<sdk>/cmake` layout for older presets.
    legacy_build = work / "legacy consumer"
    run(
        "cmake",
        "-S", consumer_source,
        "-B", legacy_build,
        *config_args,
        f"-DCMAKE_TOOLCHAIN_FILE={relocated / 'cmake' / 'TI-Nspire-Toolchain.cmake'}",
        f"-DNdless_DIR={relocated / 'cmake'}",
    )
    build(legacy_build)

    # --------------------------------------------------------------------------
    # Step 8: Confirm upstream checkout is untouched and write report.json
    # --------------------------------------------------------------------------
    assert upstream_before == run("git", "status", "--porcelain", cwd=upstream)

    report = {
        "host": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cmake": run("cmake", "--version").splitlines()[0],
        },
        "sdk_build": json.loads(
            (relocated / "share" / "ndless" / "build-info.json").read_text(encoding="utf-8")
        ),
        "generator": args.generator,
        "config": args.config,
        "upstream": run("git", "rev-parse", "HEAD", cwd=upstream).strip(),
        "sample_zehn_sizes": sample_sizes,
        "checks": [
            "build/install",
            "generated-file recovery",
            "five samples",
            "metadata",
            "C/C++/ASM",
            "startup entry/order",
            "syscall wrapper coverage",
            "no global link override",
            "compression",
            "post-link ordering",
            "non-mutating patches",
            "failure safety",
            "no-op rebuild",
            "deleted TNS recovery",
            "patch/converter dependencies",
            "spaces in paths",
            "relocated package without original source/build",
            "legacy config paths",
            "upstream untouched",
        ],
    }

    report_path = work / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {args.generator} / {args.config}; report: {report_path}")


if __name__ == "__main__":
    main()
