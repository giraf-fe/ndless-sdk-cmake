# Source provenance and third-party components

This project is an experimental CMake build layer, derived from
https://github.com/giraf-fe/ndless-sdk-windows. Its Python `genzehn.py`,
`make_prg.py`, and `mkStubs.py` tools, and `compat/newlib_compat.c`, originate
there and have local portability/correctness changes. The `genzehn.py` port
credits Fabian Vogt's genzehn 1.5.2. This file does not relicense those sources.

Upstream sources are acquired separately from
https://github.com/ndless-nspire/Ndless at the commit in `upstream.lock.json`.
The upstream checkout is never patched by the build. Its top-level Mozilla
Public License 1.1 and individual file/component notices continue to apply.

Built components:

- Ndless libndls, libsyscalls, and ARM startup/loader code from pinned upstream.
- nspire-io at the submodule revision recorded by pinned upstream.
- zlib 1.2.11 at the submodule revision recorded by pinned upstream.

Prebuilt components (optional, **not rebuilt from source here**):

- `libSDL.a`, `libSDL_gfx.a`, `libSDL_image.a` shipped in upstream `ndless-sdk/lib`.
- Corresponding upstream nSDL headers/notices and `README_nSDL` are preserved.
- Disable these archives with `-DNDLESS_WITH_SDL=OFF` if prebuilt dependencies
  are unsuitable. A successful sample link is not an exhaustive ABI audit.

ARM GCC, binutils, Newlib, and libstdc++ come from the user's external toolchain,
not from this repository. The exploratory Docker environment obtains them from
Ubuntu packages. Their respective licenses apply to any redistributed runtime
or container image.

Installed SDKs preserve upstream header notices and install the upstream MPL,
startup license, nspire-io license, zlib README, and nSDL README under
`share/ndless/licenses`. Review all applicable notices and the provenance of the
Python ports before publishing a redistributable release; this prototype is not
a licensing/redistribution audit.
