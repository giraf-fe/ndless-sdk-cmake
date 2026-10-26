# Native Windows builds (project-local installs)

Use an existing native Windows Python 3.8+, CMake 3.24+, Ninja, Git, and complete
ARM GNU `arm-none-eabi` toolchain. MSYS, Cygwin, WSL, Visual Studio, and Docker
are not required. The existing tools are used as-is; the launcher does not
install system tools or edit PATH.

## Recommended launcher

From this repository root, in PowerShell or Command Prompt:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1 -Configuration Release -Test
```

`-ExecutionPolicy Bypass` applies to this process only; it does not change your
user/machine execution policy. `-Test` is optional and runs the Python unit
suite plus an independent SDK build/install/relocation/incremental test.

Debug has its own build and install prefix:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1 -Configuration Debug -Test
```

Optional arguments:

- `-ToolchainRoot "C:/path/to/arm-gnu-toolchain"`: existing prefix containing
  `bin/arm-none-eabi-gcc.exe` and companion tools. Otherwise use PATH discovery.
- `-PythonExecutable "C:/path/to/python.exe"`: interpreter used to create the
  local `.venv`, if it does not already exist (this can be a standard Windows
  Python install or a Conda environment's `python.exe`). Otherwise native
  `python.exe` must be available on PATH (Windows Store aliases are not invoked
  automatically).
- `-UpstreamDir "C:/path/to/Ndless"`: use an existing upstream checkout, or
  fetch the pinned revision at that explicit destination if absent.
- `-Jobs 4`: limit SDK/sample build parallelism.

The launcher fails on missing tools/dependencies; it does not request elevation,
run a toolchain installer, overwrite existing upstream sources, or remove build
directories. Changing compilers requires a fresh build directory: move aside
`build/windows-release` or `build/windows-debug` first, or use direct CMake with
a different `-B` path. Installing into an existing prefix does not uninstall
obsolete files from earlier configurations; separate prefixes are recommended.

## Where files go

All default writable paths are under this checkout:

| Path | Contents |
| --- | --- |
| `.venv/` | Native Python environment and pyelftools |
| `upstream/Ndless/` | Pinned upstream checkout and required submodules |
| `build/windows-release/`, `build/windows-debug/` | SDK build trees |
| `install/windows-release/`, `install/windows-debug/` | Installed SDKs |
| `build/windows-samples-release/`, `build/windows-samples-debug/` | Sample ELF/TNS files |
| `build/windows-tests-<config>-<id>/` | Isolated test installs, relocated SDK, consumers, and `report.json` |
| `build/windows-temp/` | Launcher/subprocess temporary files |

Test subprocesses use a `host-temp/` directory in their test run. pip is invoked
in isolated, no-cache, no-version-check mode; it installs only into `.venv`.
TEMP/TMP/TMPDIR changes apply only to the launcher process and its children,
and the previous process environment is restored afterward. No CMake package
registry entry is created or used. No home SDK, home library directory, shell
profile, persistent environment, or user pip cache is modified.

## CMake without the launcher

After preparing `.venv` and fetching sources explicitly, the native presets are
sufficient:

```powershell
cmake --preset windows-release
cmake --build --preset windows-release
cmake --install build/windows-release
```

`windows-debug` is the Debug equivalent. Both presets default `Python3_EXECUTABLE`
to the project-local `.venv/Scripts/python.exe` and disable user/system
package-registry lookup.

Both **`venv`** and **`conda`** environments are supported when driving CMake
directly:
- To use the project-local `venv`, no extra Python flag is needed with the
  `windows-release` / `windows-debug` presets.
- To use a **Conda** environment (e.g., `conda create -n ndless python=3.12 pyelftools`)
  or an external `venv`, pass `-DPython3_EXECUTABLE=C:/path/to/conda/envs/ndless/python.exe`
  when configuring the preset or consumer project (or use the `sdk-release` /
  `sdk-debug` presets from an activated Conda prompt, where CMake's `FindPython3`
  automatically detects `CONDA_PREFIX` / `VIRTUAL_ENV`).

Use `-DNDLESS_SOURCE_DIR=...` and `-DNDLESS_TOOLCHAIN_ROOT=...` for source/tool
locations as needed. The usual installed-consumer workflow works unchanged;
use an absolute local SDK prefix, for example:

```powershell
$Sdk = (Resolve-Path install/windows-release).Path.Replace('\', '/')
$Python = (Resolve-Path .venv/Scripts/python.exe).Path.Replace('\', '/')
cmake -S samples -B build/my-windows-samples -G Ninja "-DCMAKE_TOOLCHAIN_FILE=$Sdk/share/ndless/cmake/TI-Nspire-Toolchain.cmake" "-DCMAKE_PREFIX_PATH=$Sdk" "-DPython3_EXECUTABLE=$Python" "-DNDLESS_SOURCE_DIR=$PWD/upstream/Ndless" -DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF -DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF
cmake --build build/my-windows-samples
```

## Validation

Native Windows/AMD64, ARM GNU GCC/G++ 14.2.1, binutils 2.43.1,
Python 3.13.2 / pyelftools 0.30, Ninja 1.11.1.git.kitware.jobserver-1,
CMake 4.4.0-rc2, and Windows PowerShell 5.1:

- Launcher: Release and Debug SDK installs and all five sample TNS outputs.
- Complete integration suites: Ninja Release, Ninja Debug, Ninja Multi-Config Debug.
- A separate full run with the compiler/binutils prefix and Python executable
  both containing spaces (the compiler prefix used a project-local NTFS junction
  to the existing read-only tool installation).
- A cold launcher run in a source path containing spaces created a fresh local
  venv, installed its requirements, and built/installed the SDK and all samples
  using the spaced compiler prefix and the existing pinned source checkout.
- Unit tests, private-copy post-link patching, relocation with original SDK
  source/build paths unavailable, legacy package paths, and no-change/deleted-
  output rebuilds passed. All test installs remained below the project `build/`.

Machine-readable reports are in `docs/test-results/windows-*.json`. GCC 14's
linker reports RWX LOAD-segment warnings for the upstream bare-metal loader
scripts; those scripts are retained unchanged. Native tests were run locally,
not in GitHub Actions. Other Windows architectures/toolchain versions and actual
calculator/emulator execution are not yet validated.
