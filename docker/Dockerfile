# ==============================================================================
# Ubuntu 24.04 Cross-Compilation & Test Container for ndless-sdk-cmake
# ==============================================================================

FROM ubuntu:24.04

# Step 1: Install ARM bare-metal GNU toolchain, Newlib/libstdc++, CMake, Ninja,
#         Git, and Python 3 with pyelftools.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        binutils-arm-none-eabi \
        ca-certificates \
        cmake \
        gcc-arm-none-eabi \
        git \
        libnewlib-arm-none-eabi \
        libstdc++-arm-none-eabi-dev \
        libstdc++-arm-none-eabi-newlib \
        make \
        ninja-build \
        python3 \
        python3-pyelftools \
    && rm -rf /var/lib/apt/lists/*

# Step 2: Copy repository sources into a read-only template location.
COPY . /opt/ndless-sdk-cmake

# Step 3: Default to /workspace for persistent volumes and interactive shells.
WORKDIR /workspace
CMD ["bash"]
