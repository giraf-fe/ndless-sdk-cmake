/*
 * basic.c — Minimal C consumer test program for Ndless SDK integration tests.
 *
 * Exercises:
 *   1. Standard heap allocation (malloc / free) backed by Ndless syscalls.
 *   2. Interoperability with an external ARM assembly function (helper.S).
 *   3. A global data symbol (patch_marker) inspected and modified by
 *      POST_LINK ELF patch scripts during packaging.
 */

#include <libndls.h>
#include <stdlib.h>

/* Marker value modified in staged ELF copies by tests/consumer/patch.py. */
volatile unsigned patch_marker = 0x12345678;

/* Defined in helper.S: returns value + 1. */
extern unsigned helper(unsigned value);

int main(void)
{
    /* Step 1: Allocate a small heap buffer to verify syscall-backed malloc. */
    char *memory = malloc(32);
    if (memory) {
        /* Step 2: Invoke the assembly helper with the patch marker value. */
        memory[0] = (char)helper(patch_marker);

        /* Step 3: Release the allocated heap buffer. */
        free(memory);
    }

    /* Step 4: Return the marker value as the program exit status. */
    return (int)patch_marker;
}
