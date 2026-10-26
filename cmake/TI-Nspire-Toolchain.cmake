# ==============================================================================
# TI-Nspire ARM GNU Cross-Compilation Toolchain File
# ==============================================================================
# Select before project():
#   cmake -DCMAKE_TOOLCHAIN_FILE=<path>/TI-Nspire-Toolchain.cmake -S . -B build
#
# Optional cache variable:
#   -DNDLESS_TOOLCHAIN_ROOT=<arm-gnu-prefix>
# ==============================================================================

# ------------------------------------------------------------------------------
# Step 1: Configure target architecture and try_compile behavior
# ------------------------------------------------------------------------------
# Bare-metal ARM targets do not have standard hosted CRT startup during CMake's
# initial compiler checks, so try_compile must build static archives instead of
# full executables.
set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

# ------------------------------------------------------------------------------
# Step 2: Collect toolchain search paths and forward to try_compile
# ------------------------------------------------------------------------------
set(NDLESS_TOOLCHAIN_ROOT "" CACHE PATH "ARM GNU toolchain prefix (optional)")
list(APPEND CMAKE_TRY_COMPILE_PLATFORM_VARIABLES NDLESS_TOOLCHAIN_ROOT)
list(REMOVE_DUPLICATES CMAKE_TRY_COMPILE_PLATFORM_VARIABLES)

set(_ndless_hints)
if(NDLESS_TOOLCHAIN_ROOT)
    list(APPEND _ndless_hints
        "${NDLESS_TOOLCHAIN_ROOT}/bin"
        "${NDLESS_TOOLCHAIN_ROOT}"
    )
endif()

if(CMAKE_C_COMPILER)
    get_filename_component(_ndless_bin "${CMAKE_C_COMPILER}" DIRECTORY)
    list(PREPEND _ndless_hints "${_ndless_bin}")
endif()

# ------------------------------------------------------------------------------
# Step 3: Locate the primary ARM C compiler (arm-none-eabi-gcc)
# ------------------------------------------------------------------------------
if(NOT CMAKE_C_COMPILER)
    find_program(
        CMAKE_C_COMPILER
        NAMES arm-none-eabi-gcc
        HINTS ${_ndless_hints}
        REQUIRED
    )
endif()
get_filename_component(_ndless_bin "${CMAKE_C_COMPILER}" DIRECTORY)

# ------------------------------------------------------------------------------
# Step 4: Locate matching companion tools from the same toolchain directory
# ------------------------------------------------------------------------------
# Restrict search with NO_DEFAULT_PATH to the selected compiler's directory (and
# explicit hints) so unrelated toolchains elsewhere on PATH are never mixed.
set(_companion_tools
    "CXX_COMPILER|g++"
    "AR|ar"
    "RANLIB|ranlib"
    "OBJCOPY|objcopy"
    "READELF|readelf"
)
foreach(_pair IN LISTS _companion_tools)
    string(REPLACE "|" ";" _pair "${_pair}")
    list(GET _pair 0 _variable)
    list(GET _pair 1 _tool)

    if(NOT CMAKE_${_variable})
        find_program(
            CMAKE_${_variable}
            NAMES "arm-none-eabi-${_tool}"
            HINTS "${_ndless_bin}" ${_ndless_hints}
            NO_DEFAULT_PATH
            REQUIRED
        )
    endif()
endforeach()

# Use the C compiler driver as the assembler driver if not explicitly set.
if(NOT CMAKE_ASM_COMPILER)
    set(CMAKE_ASM_COMPILER "${CMAKE_C_COMPILER}" CACHE FILEPATH "ARM assembler driver")
endif()

# ------------------------------------------------------------------------------
# Step 5: Configure cross-compilation root path search rules
# ------------------------------------------------------------------------------
# Host executables (such as Python) are searched on the host system, while
# libraries, headers, and packages are restricted to target/prefix roots.
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
