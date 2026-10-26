# Prototype validation

## Test hosts

Initial development/builds ran inside the persistent Linux Docker container
`ndless-sdk-cmake-sandbox-1`, on Docker Desktop's `linux/amd64` engine.
The old Windows SDK repository was mounted read-only. Native Windows/AMD64
builds were subsequently validated without Docker, MSYS/Cygwin/WSL, or Visual
Studio. macOS has not yet been tested.

Tool versions: Ubuntu 24.04, CMake 3.28.3, Ninja 1.11.1, GNU Make 4.3,
ARM GNU GCC/G++ 13.2.1, binutils 2.42, Python 3.12.3, pyelftools 0.30.
Upstream Ndless is pinned to `c659d1691295dd5db79ab171fff680638ca6a4bf`
(updated from initial prototype baseline `9484d8da7c7a4dde9766138c2e42e1d1e3acfcd4`).

Native Windows tools: ARM GCC/G++ 14.2.1, binutils 2.43.1.20241119,
CMake 4.4.0-rc2, Ninja 1.11.1.git.kitware.jobserver-1, Python 3.13.2,
pyelftools 0.30, and Windows PowerShell 5.1.26100.9711. Existing tools were
used as-is; installs and temporary files were confined to the new repository.
See [Windows instructions](windows.md).

## Passed

| Host | Generator | Configuration | Result |
| --- | --- | --- | --- |
| Linux/amd64 | Ninja | Release | PASS |
| Linux/amd64 | Unix Makefiles | Release | PASS |
| Linux/amd64 | Ninja Multi-Config | Debug | PASS |
| Windows/AMD64 | Ninja | Release | PASS |
| Windows/AMD64 | Ninja | Debug | PASS |
| Windows/AMD64 | Ninja Multi-Config | Debug | PASS |

Machine-readable results are in [test-results/](test-results/). Each full run:

- Builds and installs both syscall variants, libndls, zlib, nspire-io, three
  startup objects, and both loaders into an arbitrary prefix with spaces.
- Builds all five upstream sample TNS files and validates Zehn headers,
  relocation presence, metadata sizing, and executable entry bounds.
- Builds independent C/C++/ASM consumers and an unrelated executable. Checks
  that package discovery leaves global executable link rules unchanged.
- Checks startup instruction placement and generated syscall wrapper coverage.
- Verifies compressed/uncompressed packaging and application metadata,
  including numeric zero-valued version/minimum-version flags.
- Executes two ordered post-link ELF patches; verifies the packaged bytes are
  patched while the original linker output is unchanged. Rebuilds must not
  accumulate patches. A failing patch must preserve the previous ELF/TNS.
- Verifies no-change builds are no-ops; deletes TNS, generated syscall header,
  and a loader and verifies recovery. Modifies patch/converter timestamps and
  verifies repackaging.
- Moves the install prefix and makes the original SDK source/build paths
  unavailable, then builds a fresh independent consumer with package-registry
  lookup disabled. Also tests the old `cmake/` discovery/toolchain paths.
- Verifies upstream Git status is unchanged.

Five Python unit tests additionally cover Zehn bitfields, UTF-8 metadata,
post-link command splitting, stub whitespace/variadic/naked wrappers, and
compressed/uncompressed loader selection. The explicit pinned-source fetch
command and configure/build/install presets were also exercised in the container.
A clean `NDLESS_WITH_SDL=OFF` install and the four remaining samples passed.
Compiler/binutils/Python paths containing spaces also passed an SDK build,
install, and independent consumer build. The standalone project Docker image
built successfully and passed its Python unit tests and a full offline Ninja
integration run using only the pinned upstream sources in the workspace volume.

On Windows, both launcher configurations installed locally into
`install/windows-release` and `install/windows-debug` and built all five
samples. A further full native integration run passed with spaces in both the
compiler/binutils prefix (via a project-local junction to the existing tools)
and the Python venv path. Native test installs/relocations remained under
`build/`; pip used only local venvs with caching disabled. No home SDK or CMake
package registry was modified. Native build logs are in the ignored
`build/windows-logs/` directory. A cold launcher run from a source directory
containing spaces also created a fresh local venv and successfully built and
installed all SDK/sample outputs with the spaced compiler prefix. The updated
integration harness/presets were regression-tested successfully on Linux/Ninja.

## Changes driven by testing

- Bare-metal Newlib's `limits.h` may lack `PATH_MAX`. A build-tree wrapper
  includes `sys/param.h` before the upstream syscall runtime, without editing
  upstream.
- The previous Python stub generator skipped five Lua wrappers because function
  names had whitespace before `(`. The parser accepts that whitespace now.
  Wrapper ID coverage is compared against upstream's tracked stubs; tracked
  stubs themselves contain stale signature differences, so byte identity is
  deliberately not required.
- CMake interprets literal `COMMAND` tokens embedded in command lists as its
  own syntax. Post-link arguments are serialized into per-configuration JSON,
  ensuring all patch commands execute inside the staging driver rather than
  accidentally running after conversion against the original ELF.
- Legacy package discovery with a version request requires a version file next
  to its forwarding config; both modern and compatibility locations install it.

## Explicit limitations / release gates

- No application has been executed on a calculator or emulator. Static checks
  do not prove allocation, I/O, C++ exceptions, constructor/destructor behavior,
  or loader runtime correctness. Validate those before treating this as a
  production SDK.
- Native macOS, Windows ARM64, and a broader GCC/Newlib matrix still need
  validation. Windows AMD64 tool/Python paths with spaces have passed.
- CMake 3.28.3 (Linux) and 4.4.0-rc2 (Windows) were exercised; 3.24 is the
  declared feature baseline.
- nSDL archives remain prebuilt upstream dependencies; sample links are not
  exhaustive ABI or redistribution audits. FreeType/luna/runtime builds are
  outside this initial implementation.
- Upstream startup assembly can trigger GNU ld's missing `.note.GNU-stack`
  warning, and GCC 14's linker warns about RWX LOAD segments in the bare-metal
  loaders. Upstream startup/loader scripts are retained unchanged.
- SDK binary installations are per configuration/toolchain. Use separate
  prefixes rather than overwriting a Release install with Debug or a different
  GCC/Newlib build. Reinstalling without SDL does not remove archives left by
  an earlier install; use a clean prefix.
- The Docker base/package versions are exploratory, not a frozen release image.
  The Linux workflow is supplied but has not been run on GitHub Actions yet.
