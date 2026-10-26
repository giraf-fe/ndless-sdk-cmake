/*
 * newlib_compat.c — Weak stubs for pre-built Newlib compatibility.
 *
 * The original ndless-sdk builds Newlib from source with:
 *   -DMALLOC_PROVIDED -DABORT_PROVIDED -DNO_FORK
 * which excludes Newlib's internal malloc/_sbrk and fork code.
 *
 * External ARM GNU toolchains on any host may include a standard
 * Newlib build. These weak stubs satisfy symbols that
 * Newlib expects but that ndless programs don't need, without
 * conflicting with any strong definitions elsewhere.
 */

/* Weak _init/_fini: Ndless uses __cpp_init/__cpp_fini in crti.S/crtn.S
 * instead of the standard ELF _init/_fini. Pre-built Newlib's crt
 * references these, so we provide harmless weak definitions. */
__attribute__((weak)) void _init(void) {}
__attribute__((weak)) void _fini(void) {}

/* Weak _sbrk: Only needed if Newlib's internal malloc is pulled in.
 * Since the syscalls library provides malloc/free via OS syscalls
 * and is linked before libc, Newlib's malloc should never be reached.
 * This stub is a safety net. */
__attribute__((weak)) void *_sbrk(int incr)
{
    (void)incr;
    return (void *)-1;
}
