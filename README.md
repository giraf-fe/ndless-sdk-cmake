# ndless-sdk-cmake

Experimental, host-independent CMake build/install layer for the TI-Nspire
Ndless SDK. Native Windows, Linux, and macOS are the intended hosts; the target
is always ARM GNU `arm-none-eabi`, not the host compiler.

**Validated so far:** Linux/amd64 in Docker, ARM GCC 13.2.1, binutils 2.42,
CMake 3.28.3, Python 3.12.3 / pyelftools 0.30. Ninja Release, Unix Makefiles
Release, and Ninja Multi-Config Debug pass the integration suite. Native
Windows/AMD64 also passes Ninja Release/Debug and Ninja Multi-Config Debug with
ARM GCC 14.2.1 and Python 3.13.2. macOS and calculator/emulator runtime validation
remain outstanding.

## Requirements

- CMake **3.24+**, Git, Ninja (recommended).
- ARM GNU GCC/G++ and matching binutils, including ARM926EJ-S support,
  Newlib, C++ headers, and the complete libstdc++ runtime.
- Host Python **3.8+** with `pyelftools` (`requirements.txt`). Both standard
  Python **`venv`** and **`conda`** (or `mamba` / `micromamba`) environments
  are supported.

No MSYS, Cygwin, or WSL is required by the build system on Windows. No package
registry, PATH modification, administrator install, or system-Python pip
modification is performed. Docker is optional; native Windows builds do not use it.

## Python environments (`venv` and `conda`)

Both the SDK build (`CMakeLists.txt`) and installed application package
(`NdlessConfig.cmake`) use CMake's `FindPython3` module to locate a Python 3.8+
interpreter with `pyelftools` installed. Either **`venv`** or **`conda`** can be
used:

- **Using `venv`**:
  ```sh
  python -m venv .venv
  # Linux/macOS: .venv/bin/python | Windows: .venv/Scripts/python.exe
  .venv/bin/python -m pip install -r requirements.txt
  ```
- **Using `conda` (or `mamba` / `micromamba`)**:
  ```sh
  conda create -n ndless python=3.12 -y
  conda activate ndless
  python -m pip install -r requirements.txt
  # (or: conda install -c conda-forge pyelftools)
  ```
- **How CMake selects the environment**:
  - If a `venv` (`VIRTUAL_ENV`) or `conda` (`CONDA_PREFIX`) environment is
    active in your shell, CMake's `FindPython3` automatically detects and uses
    it first (`sdk-release` / `sdk-debug` presets and direct `cmake` invocations).
  - You can always pin a specific `venv` or `conda` interpreter explicitly
    (even without activating the environment) via
    `-DPython3_EXECUTABLE=<absolute-path-to-python>` (for example,
    `.venv/bin/python`, `.venv/Scripts/python.exe`, `<conda-env>/bin/python`, or
    `<conda-env>/python.exe` on Windows).
  - Note: The `windows-release` and `windows-debug` presets in
    `CMakePresets.json` default `Python3_EXECUTABLE` to
    `${sourceDir}/.venv/Scripts/python.exe`; pass
    `-DPython3_EXECUTABLE=<conda-or-venv-python>` on the command line to
    override that default with a Conda environment or custom `venv`.

## Native Windows: local install

From the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1 -Configuration Release -Test
```

This uses existing system tools, creates a project-local `.venv` and upstream
checkout if needed, installs into **`install/windows-release`**, builds all five
samples, and runs the test suite. `-Configuration Debug` uses
`install/windows-debug`. All test installs, temporary files, and pip activity
stay within this checkout; your home SDK, package registry, and PATH are untouched.
The execution-policy override is process-only. See [Windows instructions](docs/windows.md)
for tool selection, the native CMake presets, and exact output paths.

## Fetch sources and install

From the repository root (use `python3` instead of `python` where appropriate):

```sh
python -m venv .venv
```

Select that environment's Python: `.venv/bin/python` on Linux/macOS,
`.venv/Scripts/python.exe` on Windows. Activate the environment, or replace
`python` below with that interpreter; pass its absolute path to CMake:

```sh
python -m pip --isolated --disable-pip-version-check install --no-cache-dir -r requirements.txt
python scripts/fetch_upstream.py
cmake --preset sdk-release -DPython3_EXECUTABLE=<absolute-venv-python>
cmake --build --preset sdk-release
cmake --install build/sdk-release
```

The preset installs into `install/release`. `sdk-debug` uses a separate
`install/debug` prefix. The fetch script checks out the immutable revision in
`upstream.lock.json`, initializes only required submodules, and refuses to
overwrite existing sources. CMake itself never downloads or runs pip.

To use an existing checkout/offline sources, skip fetching and configure with
`-DNDLESS_SOURCE_DIR=<path-to-Ndless>`; initialize its nspire-io/zlib submodules
first. Overrides of the pinned upstream revision are explicitly experimental.

To select a non-PATH toolchain, pass
`-DNDLESS_TOOLCHAIN_ROOT=<arm-gnu-prefix>` (containing `bin/`) or explicit
`CMAKE_C_COMPILER` / `CMAKE_CXX_COMPILER` paths. Matching binutils are searched
beside the C compiler. Use a fresh build tree when changing toolchains.

Without presets, select `cmake/TI-Nspire-Toolchain.cmake` through
`CMAKE_TOOLCHAIN_FILE`, and set your own `CMAKE_INSTALL_PREFIX` and build type.
All generated headers, stubs, objects, and loaders stay in the binary tree;
upstream sources remain untouched.

## Build an application

```cmake
cmake_minimum_required(VERSION 3.24)
project(MyApplication LANGUAGES C CXX ASM)
find_package(Ndless 0.1 CONFIG REQUIRED)
add_nspire_program(app SOURCES main.cpp NAME "My app" AUTHOR "Me"
    USE_NSPIREIO GC_SECTIONS)
target_compile_features(app PRIVATE cxx_std_17)
```

Configure the application with these cache values (one line on any shell):

```sh
cmake -S . -B build -G Ninja -DCMAKE_TOOLCHAIN_FILE=<sdk-prefix>/share/ndless/cmake/TI-Nspire-Toolchain.cmake -DCMAKE_PREFIX_PATH=<sdk-prefix> -DPython3_EXECUTABLE=<host-python>
cmake --build build
```

Quote whole arguments that contain spaces. Select the toolchain **before**
`project()`; `find_package` cannot change an already-selected compiler.

The default build creates `app.elf` and `app.tns`. Explicitly build `app_tns`
for the deployable artifact, or `app` for ELF only. This explicit packaging
target is a change from the old Windows helper's post-build-only behavior.
TNS files are placed in the current binary directory (`<config>/` for
multi-config generators). `NDLESS_TNS_FILE` on the ELF target exposes the path.
Deleting a TNS or changing a converter/loader causes repackaging independently
of relinking. Multi-config builds use `--config Release` or `--config Debug`.

To build the five upstream samples, configure `samples/` the same way and
also pass `-DNDLESS_SOURCE_DIR=<upstream-checkout>`.

### Package API

- `add_nspire_program`: `SOURCES`, `LIBRARIES`, `NAME`, `AUTHOR`, `VERSION`,
  `NOTICE`, `NDLESS_MIN`, `GENZEHN_FLAGS`, `USE_NSPIREIO`, `GC_SECTIONS`.
  Release and MinSizeRel programs default to `-Os`, as upstream's Makefile
  template does; an `-O` option the program adds with `target_compile_options`
  overrides it. `Ndless::sdk` itself sets no optimization level.
- Exported targets: `Ndless::sdk`, `Ndless::ndls`, `Ndless::syscalls`,
  `Ndless::syscalls_nspireio`, `Ndless::nspireio`, `Ndless::zlib`.
- Optional prebuilt targets: `Ndless::SDL`, `Ndless::SDL_gfx`, `Ndless::SDL_image`.
  The helper accepts their legacy unqualified names (and `z` for zlib).
- Legacy include/library variables, `PYTHON_EXECUTABLE`,
  `Ndless_HAS_POST_LINK`, `Ndless_USE_NSPIREIO`, and old `cmake/` package/toolchain
  paths are retained. `find_package` does not alter global link rules.
- `NDLESS_USER_LIB_DIR` is opt-in. No `~/.ndless` directory is created/searched
  implicitly; preferably supply your own library targets in `LIBRARIES`.

### ELF patching before packaging

```cmake
add_nspire_program(app SOURCES main.cpp
    POST_LINK "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/patch.py"
        "$<TARGET_FILE:app>"
    POST_LINK_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/patch.py")
```

`POST_LINK` accepts multiple commands separated by `COMMAND`, with generator
expressions. Commands execute without a shell; use `cmake -E` for portable shell
utilities. Declare patch scripts/data in `POST_LINK_DEPENDS`. Commands run
on a **private ELF copy**: occurrences of the expanded target-file path in
command arguments are redirected to it. Commands must patch that supplied path,
not locate/hardcode the original ELF independently. Relative files are resolved
from the consumer binary directory. Tools that require the ELF to sit beside
other files must be adapted for staging. The original linked ELF is unchanged,
patches never accumulate on rebuild, and a failed command preserves the previous
TNS. This safer staging behavior intentionally differs from the old helper.

## Docker development / tests

The existing development container keeps this source at
`/workspace/ndless-sdk-cmake` and upstream at `/workspace/ndless-upstream`.
For a standalone environment, build from this repository root:

```sh
docker build -f docker/Dockerfile -t ndless-sdk-cmake-dev .
docker run -it --name ndless-cmake-dev --mount source=ndless-cmake-work,target=/workspace ndless-sdk-cmake-dev
```

Inside that new container, source is at `/opt/ndless-sdk-cmake`. Copy it to
`/workspace/ndless-sdk-cmake` for editing; source copies and builds in `/workspace`
persist in the volume. Build changes require either rebuilding the image or
copying updated source into the container.

```sh
cd /workspace/ndless-sdk-cmake
python3 scripts/fetch_upstream.py --destination /workspace/ndless-upstream
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tests/integration.py --upstream /workspace/ndless-upstream
```

The fetch step is only needed if that checkout does not already exist.
Integration tests use an empty work directory (by default under
`build/integration/run-*`), preserve their artifacts/report,
and exercise independent SDK builds/installs, all samples, relocation without
the original SDK source/build paths, compressed/uncompressed metadata, startup
order, generated-file recovery, post-link ordering/failure safety, no-op builds,
and dependency-triggered regeneration. Pass `--generator "Unix Makefiles"` or
`--generator "Ninja Multi-Config" --config Debug` for other tested variants.
Linux CI runs this matrix; the Windows launcher runs native Ninja tests.
See [validation](docs/validation.md).

## Scope and remaining work

This builds libndls, both syscall variants, nspire-io, zlib, startup objects,
and both Zehn loaders. nSDL archives remain upstream **prebuilt ARM libraries**;
disable installation with `-DNDLESS_WITH_SDL=OFF`. FreeType, luna, and the Ndless
runtime/installer are not built by this project yet. This is not yet a complete
replacement for every upstream Make target.

Device/emulator testing is still required for allocation, exceptions,
constructors/destructors, I/O, and loader behavior; successful compilation and
format checks do not prove runtime correctness. Native macOS tests, broader
Windows/toolchain coverage, and redistribution/license review remain release
gates. See [THIRD_PARTY.md](THIRD_PARTY.md).
