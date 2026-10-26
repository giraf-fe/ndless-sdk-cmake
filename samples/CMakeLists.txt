# ==============================================================================
# Upstream Ndless SDK Samples Build
# ==============================================================================
# Standalone CMake consumer project that builds the upstream Ndless sample
# programs against an installed Ndless SDK package.
# ==============================================================================

cmake_minimum_required(VERSION 3.24)
project(NdlessSamples LANGUAGES C CXX ASM)

# ------------------------------------------------------------------------------
# Step 1: Discover the installed Ndless SDK package
# ------------------------------------------------------------------------------
find_package(Ndless 0.1 CONFIG REQUIRED)

# ------------------------------------------------------------------------------
# Step 2: Locate the upstream Ndless sample source directory
# ------------------------------------------------------------------------------
set(NDLESS_SOURCE_DIR
    "${CMAKE_CURRENT_LIST_DIR}/../upstream/Ndless"
    CACHE PATH "Upstream checkout containing samples"
)
set(_samples "${NDLESS_SOURCE_DIR}/ndless-sdk/samples")

# ------------------------------------------------------------------------------
# Step 3: Define sample TI-Nspire application targets
# ------------------------------------------------------------------------------
# 3a. Basic C++ console sample using nspire-io.
add_nspire_program(
    helloworld-cpp
    SOURCES "${_samples}/helloworld-cpp/hello.cpp"
    USE_NSPIREIO
)

# 3b. SDL graphics sample (enabled when prebuilt nSDL archives are installed).
if(TARGET Ndless::SDL)
    add_nspire_program(
        helloworld-sdl
        SOURCES "${_samples}/helloworld-sdl/hello-sdl.c"
        LIBRARIES SDL
    )
endif()

# 3c. C standard library (Newlib) sample with dead-section garbage collection.
add_nspire_program(
    newlib
    SOURCES "${_samples}/newlib/test_newlib.c"
    USE_NSPIREIO
    GC_SECTIONS
)

# 3d. C++ standard library (Newlib / libstdc++) sample.
add_nspire_program(
    newlib-cpp
    SOURCES "${_samples}/newlib-c++/test_newlib.cpp"
    USE_NSPIREIO
)

# 3e. Nspire Graphic Context (NGC) demo using the legacy screen buffer API.
add_nspire_program(
    ngc_demo
    SOURCES "${_samples}/ngc/ngc_demo.c"
)
target_compile_definitions(ngc_demo PRIVATE OLD_SCREEN_API)
