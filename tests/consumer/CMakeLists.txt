# ==============================================================================
# Integration Test Consumer Project
# ==============================================================================
# Exercises the installed Ndless CMake package, including:
#   - Idempotent find_package(Ndless) calls without global link rule mutation
#   - Mixed C + ARM assembly targets, metadata flags, compression, and ordered
#     POST_LINK ELF patching
#   - C++17 global constructors/destructors and STL containers with nspire-io
#   - Unrelated bare-metal executables in the same build tree
# ==============================================================================

cmake_minimum_required(VERSION 3.24)
project(NdlessConsumer LANGUAGES C CXX ASM)

# ------------------------------------------------------------------------------
# Step 1: Verify find_package(Ndless) is idempotent and leaves global link rules
#         unchanged
# ------------------------------------------------------------------------------
set(_c_link_before "${CMAKE_C_LINK_EXECUTABLE}")
set(_cxx_link_before "${CMAKE_CXX_LINK_EXECUTABLE}")

find_package(Ndless 0.1 CONFIG REQUIRED)
find_package(Ndless CONFIG REQUIRED)

if(NOT _c_link_before STREQUAL CMAKE_C_LINK_EXECUTABLE
   OR NOT _cxx_link_before STREQUAL CMAKE_CXX_LINK_EXECUTABLE)
    message(FATAL_ERROR "find_package(Ndless) must not modify global link rules")
endif()

# ------------------------------------------------------------------------------
# Step 2: Build a compressed C + ASM program with metadata and POST_LINK patches
# ------------------------------------------------------------------------------
# Exercises zero-valued numeric flags (VERSION 0, NDLESS_MIN 0), dead-section
# garbage collection, zlib compression, and two sequential POST_LINK commands
# that patch a private staged ELF copy.
add_nspire_program(
    basic
    SOURCES
        basic.c
        helper.S
    NAME "Portable test"
    AUTHOR "Ndless CMake"
    VERSION 0
    NDLESS_MIN 0
    GC_SECTIONS
    GENZEHN_FLAGS --compress
    POST_LINK
        "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/patch.py" "$<TARGET_FILE:basic>" 1
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/patch.py" "$<TARGET_FILE:basic>" 2
    POST_LINK_DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/patch.py"
)

# ------------------------------------------------------------------------------
# Step 3: Build an uncompressed C++17 program exercising global ctors/dtors
# ------------------------------------------------------------------------------
add_nspire_program(
    constructors
    SOURCES constructors.cpp
    USE_NSPIREIO
)
target_compile_features(constructors PRIVATE cxx_std_17)

# ------------------------------------------------------------------------------
# Step 4: Build an unrelated bare-metal target to verify link isolation
# ------------------------------------------------------------------------------
# This target has no dependency on Ndless targets and defines its own _start
# symbol. It would fail with duplicate startup symbols if Ndless injected a
# global executable link rule override.
add_executable(unrelated unrelated.S)
target_link_options(unrelated PRIVATE
    -nostdlib
    -Wl,-e,_start
    -mcpu=arm926ej-s
)
