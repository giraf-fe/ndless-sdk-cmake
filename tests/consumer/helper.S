/*
 * helper.S — Minimal ARM assembly routine for consumer integration testing.
 *
 * Verifies that CMake's ASM language support compiles .S sources with the
 * ARM GNU toolchain and links them cleanly into an Ndless executable.
 */

.syntax unified
.arm
.text

/* --------------------------------------------------------------------------
 * unsigned helper(unsigned value)
 *   Adds 1 to the first argument (r0) and returns to the caller (lr).
 * -------------------------------------------------------------------------- */
.global helper
.type helper, %function
helper:
    add r0, r0, #1
    bx lr
.size helper, .-helper

/* Mark stack as non-executable to silence GNU ld warnings. */
.section .note.GNU-stack,"",%progbits
