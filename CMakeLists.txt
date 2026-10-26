# ==============================================================================
# Ndless SDK CMake Build System
# ==============================================================================
# Cross-compiles the TI-Nspire Ndless SDK (startup objects, zlib, nspire-io,
# syscall libraries, libndls, and Zehn loaders) from a pinned upstream Ndless
# checkout without modifying upstream sources, and installs a relocatable
# CMake package for building TI-Nspire applications.
# ==============================================================================

cmake_minimum_required(VERSION 3.24)
project(NdlessSDK VERSION 0.1.0 LANGUAGES C CXX ASM)

# ------------------------------------------------------------------------------
# Step 1: Verify ARM GNU cross-compilation environment
# ------------------------------------------------------------------------------
# Ensure CMake was configured with cmake/TI-Nspire-Toolchain.cmake and that the
# active compiler targets bare-metal ARM (arm-none-eabi).
if(NOT CMAKE_CROSSCOMPILING OR NOT CMAKE_C_COMPILER_ID STREQUAL "GNU")
    message(FATAL_ERROR
        "Use cmake/TI-Nspire-Toolchain.cmake with an ARM GNU toolchain in a fresh build directory"
    )
endif()

execute_process(
    COMMAND "${CMAKE_C_COMPILER}" -dumpmachine
    OUTPUT_VARIABLE _machine
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(NOT _machine STREQUAL "arm-none-eabi")
    message(FATAL_ERROR "Expected arm-none-eabi compiler target, got '${_machine}'")
endif()

# ------------------------------------------------------------------------------
# Step 2: Locate and validate the upstream Ndless source checkout
# ------------------------------------------------------------------------------
# The upstream checkout is treated as read-only input. Verify that both the
# core SDK files and the required submodules (nspire-io, zlib) are present.
set(NDLESS_SOURCE_DIR
    "${CMAKE_CURRENT_SOURCE_DIR}/upstream/Ndless"
    CACHE PATH "Pinned upstream Ndless checkout (not modified)"
)
get_filename_component(NDLESS_SOURCE_DIR "${NDLESS_SOURCE_DIR}" ABSOLUTE)
set(sdk "${NDLESS_SOURCE_DIR}/ndless-sdk")

set(_required_sdk_files
    include/libndls.h
    system/crt0.S
    libsyscalls/osvar.cpp
    thirdparty/nspire-io/include/nspireio2.h
    thirdparty/zlib/zlib.h
)
foreach(_required IN LISTS _required_sdk_files)
    if(NOT EXISTS "${sdk}/${_required}")
        message(FATAL_ERROR
            "Missing ${sdk}/${_required}. "
            "Run scripts/fetch_upstream.py or set NDLESS_SOURCE_DIR to an initialized checkout."
        )
    endif()
endforeach()

# ------------------------------------------------------------------------------
# Step 3: Locate host Python interpreter and verify pyelftools
# ------------------------------------------------------------------------------
# Python is used at build time to generate syscall stubs (scripts/mkStubs.py)
# and by downstream consumers to package ELF binaries into Zehn/.tns files.
#
# Both Python venv and Conda environments are supported:
#   - Active venv (VIRTUAL_ENV) or Conda (CONDA_PREFIX) environments are
#     detected automatically by CMake's FindPython3 module.
#   - Any venv or Conda interpreter can also be selected explicitly via
#     -DPython3_EXECUTABLE=<path-to-python> or -DPython3_ROOT_DIR=<env-prefix>.
find_package(Python3 3.8 REQUIRED COMPONENTS Interpreter)

execute_process(
    COMMAND "${Python3_EXECUTABLE}" -c "import elftools"
    RESULT_VARIABLE _python_status
    ERROR_QUIET
)
if(NOT _python_status EQUAL 0)
    message(FATAL_ERROR
        "${Python3_EXECUTABLE} needs pyelftools; "
        "install requirements.txt into that Python (venv or conda) environment"
    )
endif()

# ------------------------------------------------------------------------------
# Step 4: Configure SDK build options and record upstream revision metadata
# ------------------------------------------------------------------------------
option(NDLESS_WITH_SDL "Install the three upstream prebuilt ARM nSDL archives" ON)
option(NDLESS_WARNINGS_AS_ERRORS "Treat SDK warnings as errors" OFF)

# Read the expected upstream commit hash from upstream.lock.json.
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/upstream.lock.json" _lock)
string(JSON _pinned_commit GET "${_lock}" commit)

# Compare the actual upstream Git HEAD against the pinned lockfile commit.
set(NDLESS_UPSTREAM_REVISION "unknown")
find_package(Git QUIET)
if(Git_FOUND AND EXISTS "${NDLESS_SOURCE_DIR}/.git")
    execute_process(
        COMMAND "${GIT_EXECUTABLE}" -C "${NDLESS_SOURCE_DIR}" rev-parse HEAD
        OUTPUT_VARIABLE NDLESS_UPSTREAM_REVISION
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
    if(NOT NDLESS_UPSTREAM_REVISION STREQUAL _pinned_commit)
        message(WARNING
            "Building untested upstream revision ${NDLESS_UPSTREAM_REVISION}; "
            "pinned baseline is ${_pinned_commit}"
        )
    endif()
endif()

# Emit build provenance metadata (version, revision, compiler, SDL status).
configure_file(
    cmake/build-info.json.in
    "${CMAKE_CURRENT_BINARY_DIR}/build-info.json"
    @ONLY
)
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/build-info.json" DESTINATION share/ndless)

# ------------------------------------------------------------------------------
# Step 5: Generate syscall declarations and stub wrappers
# ------------------------------------------------------------------------------
# Parse upstream syscall-list.h with scripts/mkStubs.py to produce
# syscall-decls.h and stubs.cpp inside the build tree (never in upstream/).
set(generated "${CMAKE_CURRENT_BINARY_DIR}/generated")

add_custom_command(
    OUTPUT
        "${generated}/include/syscall-decls.h"
        "${generated}/stubs.cpp"
    COMMAND
        "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/scripts/mkStubs.py"
        "${sdk}/include/syscall-list.h"
        "${generated}/include/syscall-decls.h"
        "${generated}/stubs.cpp"
    DEPENDS
        "${sdk}/include/syscall-list.h"
        scripts/mkStubs.py
    COMMENT "Generating Ndless syscall declarations and ARM stub wrappers"
    VERBATIM
)

add_custom_target(
    ndless_stubs
    DEPENDS
        "${generated}/include/syscall-decls.h"
        "${generated}/stubs.cpp"
)

# Shared build-time interface target carrying common include paths and ARM926EJ-S
# compilation flags for all internal SDK targets.
add_library(ndless_build_options INTERFACE)
target_include_directories(ndless_build_options INTERFACE
    "${generated}/include"
    "${sdk}/include"
    "${sdk}/thirdparty/nspire-io/include"
    "${sdk}/thirdparty/zlib"
)
target_compile_definitions(ndless_build_options INTERFACE _TINSPIRE)
target_compile_options(ndless_build_options INTERFACE
    -mcpu=arm926ej-s
    -marm
    -ffunction-sections
    -fdata-sections
    -Wall
)
if(NDLESS_WARNINGS_AS_ERRORS)
    target_compile_options(ndless_build_options INTERFACE -Werror)
endif()

# Helper to attach internal compile options and generated header dependencies.
function(ndless_internal target)
    target_link_libraries(${target} PRIVATE "$<BUILD_INTERFACE:ndless_build_options>")
    add_dependencies(${target} ndless_stubs)
endfunction()

# ------------------------------------------------------------------------------
# Step 6: Build bare-metal startup and teardown objects (crt0.o, crti.o, crtn.o)
# ------------------------------------------------------------------------------
# Three independent object targets keep startup objects available under stable
# installed filenames. Consumer link options place crt0.o and crti.o BEFORE user
# objects and crtn.o AFTER user objects/libraries.
foreach(_crt IN ITEMS crt0 crti crtn)
    add_library(${_crt} OBJECT "${sdk}/system/${_crt}.S")
    ndless_internal(${_crt})
    target_compile_definitions(${_crt} PRIVATE GNU_AS)
    install(
        FILES "$<TARGET_OBJECTS:${_crt}>"
        DESTINATION system
        RENAME "${_crt}.o"
    )
endforeach()

# ------------------------------------------------------------------------------
# Step 7: Build third-party static libraries (zlib and nspire-io)
# ------------------------------------------------------------------------------
# 7a. zlib (installed as libz.a): used by compressed Zehn loaders and user apps.
set(_zlib_sources
    adler32.c
    compress.c
    crc32.c
    deflate.c
    infback.c
    inffast.c
    inflate.c
    inftrees.c
    trees.c
    uncompr.c
    zutil.c
)
list(TRANSFORM _zlib_sources PREPEND "${sdk}/thirdparty/zlib/")

add_library(zlib STATIC ${_zlib_sources})
set_target_properties(zlib PROPERTIES OUTPUT_NAME z)
ndless_internal(zlib)
target_compile_definitions(zlib PRIVATE NO_GZIP)
target_compile_options(zlib PRIVATE -Os -ffreestanding -fPIE)

# 7b. nspire-io (installed as libnspireio.a): console and UART I/O routines.
set(_nspireio_sources
    common/console.c
    common/cursor.c
    common/queue.c
    common/util.c
    arch-nspire/nspire-uart.c
    arch-nspire/nspire.c
    common/cpp/console.cpp
    common/cpp/file.cpp
    common/cpp/uart.cpp
)
list(TRANSFORM _nspireio_sources PREPEND "${sdk}/thirdparty/nspire-io/")

add_library(nspireio STATIC ${_nspireio_sources})
ndless_internal(nspireio)
target_compile_definitions(nspireio PRIVATE NSPIREIO_BUILD)
target_compile_options(nspireio PRIVATE -O3)
target_include_directories(nspireio PRIVATE
    "${sdk}/thirdparty/nspire-io/common"
    "${sdk}/thirdparty/nspire-io/arch-nspire"
)

# ------------------------------------------------------------------------------
# Step 8: Build Ndless syscall and core SDK libraries
# ------------------------------------------------------------------------------
# 8a. Wrap upstream libsyscalls/stdlib.cpp so <sys/param.h> provides PATH_MAX
#     on bare-metal Newlib toolchains without modifying the upstream checkout.
configure_file(
    compat/syscalls_stdlib.cpp.in
    "${generated}/syscalls_stdlib.cpp"
    @ONLY
)

# 8b. Build both standard (libsyscalls.a) and nspire-io-backed
#     (libsyscalls_nspireio.a) syscall static libraries.
foreach(_variant IN ITEMS syscalls syscalls_nspireio)
    add_library(${_variant} STATIC
        "${sdk}/libsyscalls/osvar.cpp"
        "${sdk}/libsyscalls/realpath.c"
        "${generated}/syscalls_stdlib.cpp"
        "${generated}/stubs.cpp"
        compat/newlib_compat.c
    )
    ndless_internal(${_variant})
    target_compile_features(${_variant} PRIVATE c_std_11 cxx_std_11)
    target_compile_options(${_variant} PRIVATE
        -O3
        -nostdlib
        -fPIE
        -mlong-calls
        "$<$<COMPILE_LANGUAGE:CXX>:-fno-exceptions;-fno-rtti>"
    )
endforeach()
target_compile_definitions(syscalls_nspireio PRIVATE USE_NSPIREIO)

# 8c. Build libndls.a from all C and C++ sources in ndless-sdk/libndls/.
file(GLOB _ndls_sources CONFIGURE_DEPENDS
    "${sdk}/libndls/*.c"
    "${sdk}/libndls/*.cpp"
)
add_library(ndls STATIC ${_ndls_sources})
ndless_internal(ndls)
target_compile_features(ndls PRIVATE cxx_std_11)
target_compile_options(ndls PRIVATE
    -O2
    -funroll-loops
    -nostdlib
    -Wextra
    "$<$<COMPILE_LANGUAGE:CXX>:-fno-exceptions;-fno-rtti>"
)

# ------------------------------------------------------------------------------
# Step 9: Build Zehn executable loaders (uncompressed and zlib-compressed)
# ------------------------------------------------------------------------------
# Each loader is linked as a standalone static ELF using upstream's loader
# ldscript, then converted into a flat binary (.tns) via objcopy. make_prg.py
# prepends one of these loaders to user Zehn binaries.
foreach(_loader IN ITEMS zehn_loader zehn_loader_compressed)
    add_executable(${_loader}_elf "${sdk}/tools/zehn_loader/loader.cpp")
    ndless_internal(${_loader}_elf)
    target_compile_features(${_loader}_elf PRIVATE cxx_std_11)
    target_compile_options(${_loader}_elf PRIVATE
        -Os
        -march=armv5te
        -fPIE
        -fno-rtti
        -fno-exceptions
        -ffreestanding
    )
    target_link_options(${_loader}_elf PRIVATE
        -nostdlib
        -nostartfiles
        -static
        "-Wl,-T,${sdk}/tools/zehn_loader/ldscript"
        -Wl,--gc-sections
    )
    set_property(
        TARGET ${_loader}_elf
        APPEND PROPERTY LINK_DEPENDS "${sdk}/tools/zehn_loader/ldscript"
    )

    if(_loader STREQUAL "zehn_loader_compressed")
        target_compile_definitions(${_loader}_elf PRIVATE ENABLE_ZLIB)
        target_link_libraries(${_loader}_elf PRIVATE zlib gcc)
    endif()

    set(_loader_directory "${CMAKE_CURRENT_BINARY_DIR}/loaders")
    if(CMAKE_CONFIGURATION_TYPES)
        string(APPEND _loader_directory "/$<CONFIG>")
    endif()
    set(_loader_output "${_loader_directory}/${_loader}.tns")

    add_custom_command(
        OUTPUT "${_loader_output}"
        COMMAND "${CMAKE_COMMAND}" -E make_directory "${_loader_directory}"
        COMMAND "${CMAKE_OBJCOPY}"
            --set-section-flags .pad=alloc,load,contents
            -O binary
            "$<TARGET_FILE:${_loader}_elf>"
            "${_loader_output}"
        DEPENDS ${_loader}_elf
        COMMENT "Generating flat binary loader ${_loader}.tns"
        VERBATIM
    )
    add_custom_target(${_loader} ALL DEPENDS "${_loader_output}")
    install(FILES "${_loader_output}" DESTINATION bin)
endforeach()

# ------------------------------------------------------------------------------
# Step 10: Define exported SDK interface and install SDK artifacts
# ------------------------------------------------------------------------------
# sdk_interface (exported as Ndless::sdk) describes consumer compile flags and
# include directories only, never global link rules.
add_library(sdk_interface INTERFACE)
set_target_properties(sdk_interface PROPERTIES EXPORT_NAME sdk)
target_include_directories(sdk_interface INTERFACE "$<INSTALL_INTERFACE:include>")
target_compile_definitions(sdk_interface INTERFACE _TINSPIRE)
target_compile_options(sdk_interface INTERFACE
    -mcpu=arm926ej-s
    -marm
    -Wall
    "$<$<CONFIG:Release>:-Os>"
    "$<$<CONFIG:MinSizeRel>:-Os>"
)

foreach(_library IN ITEMS ndls syscalls syscalls_nspireio nspireio zlib)
    target_link_libraries(${_library} INTERFACE sdk_interface)
endforeach()

# 10a. Install compiled static libraries and export target definitions.
install(
    TARGETS sdk_interface ndls syscalls syscalls_nspireio nspireio zlib
    EXPORT NdlessTargets
    ARCHIVE DESTINATION lib
)

# 10b. Install public headers (upstream SDK, generated syscalls, nspire-io, zlib).
install(
    DIRECTORY "${sdk}/include/"
    DESTINATION include
    PATTERN syscall-decls.h EXCLUDE
    PATTERN .gitignore EXCLUDE
)
install(FILES "${generated}/include/syscall-decls.h" DESTINATION include)
install(FILES "${sdk}/thirdparty/nspire-io/include/nspireio2.h" DESTINATION include)
install(DIRECTORY "${sdk}/thirdparty/nspire-io/include/nspireio" DESTINATION include)
install(
    FILES
        "${sdk}/thirdparty/zlib/zlib.h"
        "${sdk}/thirdparty/zlib/zconf.h"
    DESTINATION include
)

# 10c. Install system linker script.
install(FILES "${sdk}/system/ldscript" DESTINATION system)

# 10d. Optionally install upstream prebuilt nSDL static archives.
if(NDLESS_WITH_SDL)
    foreach(_lib IN ITEMS SDL SDL_gfx SDL_image)
        if(NOT EXISTS "${sdk}/lib/lib${_lib}.a")
            message(FATAL_ERROR "Missing upstream prebuilt archive: lib${_lib}.a")
        endif()
        install(FILES "${sdk}/lib/lib${_lib}.a" DESTINATION lib)
    endforeach()
endif()

# 10e. Install Python packaging utilities into bin/.
install(
    FILES
        scripts/genzehn.py
        scripts/make_prg.py
        scripts/package_program.py
    DESTINATION bin
)

# 10f. Install third-party and upstream license notices.
install(
    FILES
        "${NDLESS_SOURCE_DIR}/Mozilla-Public-License-v1.1.html"
        "${sdk}/system/LICENSE.txt"
        "${sdk}/lib/README_nSDL"
    DESTINATION share/ndless/licenses
)
install(
    FILES "${sdk}/thirdparty/nspire-io/LICENSE"
    DESTINATION share/ndless/licenses
    RENAME nspire-io-LICENSE
)
install(
    FILES "${sdk}/thirdparty/zlib/README"
    DESTINATION share/ndless/licenses
    RENAME zlib-README
)
install(FILES THIRD_PARTY.md DESTINATION share/ndless/licenses)

# ------------------------------------------------------------------------------
# Step 11: Generate and install CMake package configuration files
# ------------------------------------------------------------------------------
include(CMakePackageConfigHelpers)

# Generate relocatable package config and version files.
configure_package_config_file(
    cmake/NdlessConfig.cmake.in
    "${CMAKE_CURRENT_BINARY_DIR}/NdlessConfig.cmake"
    INSTALL_DESTINATION lib/cmake/Ndless
)
write_basic_package_version_file(
    "${CMAKE_CURRENT_BINARY_DIR}/NdlessConfigVersion.cmake"
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY SameMajorVersion
    ARCH_INDEPENDENT
)

# Install modern CMake package layout under lib/cmake/Ndless and share/ndless/cmake.
install(
    EXPORT NdlessTargets
    NAMESPACE Ndless::
    DESTINATION lib/cmake/Ndless
)
install(
    FILES
        "${CMAKE_CURRENT_BINARY_DIR}/NdlessConfig.cmake"
        "${CMAKE_CURRENT_BINARY_DIR}/NdlessConfigVersion.cmake"
        cmake/NdlessPrograms.cmake
    DESTINATION lib/cmake/Ndless
)
install(FILES cmake/TI-Nspire-Toolchain.cmake DESTINATION share/ndless/cmake)

# Install forwarding config and toolchain under cmake/ for backward compatibility
# with presets written for the legacy ndless-sdk-windows layout.
install(
    FILES
        cmake/TI-Nspire-Toolchain.cmake
        "${CMAKE_CURRENT_BINARY_DIR}/NdlessConfigVersion.cmake"
    DESTINATION cmake
)
file(WRITE
    "${CMAKE_CURRENT_BINARY_DIR}/NdlessConfig-forward.cmake"
    "include(\"\${CMAKE_CURRENT_LIST_DIR}/../lib/cmake/Ndless/NdlessConfig.cmake\")\n"
)
install(
    FILES "${CMAKE_CURRENT_BINARY_DIR}/NdlessConfig-forward.cmake"
    DESTINATION cmake
    RENAME NdlessConfig.cmake
)
