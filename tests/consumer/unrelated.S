/*
 * unrelated.S — Standalone bare-metal ARM entry point for link isolation tests.
 *
 * Built via standard add_executable() in the same CMake project as Ndless
 * programs to verify that find_package(Ndless) does not inject crt0.o or
 * override global executable link rules.
 */

.syntax unified
.arm
.text

/* Minimal _start entry point that immediately returns. */
.global _start
_start:
    bx lr

/* Mark stack as non-executable to silence GNU ld warnings. */
.section .note.GNU-stack,"",%progbits
