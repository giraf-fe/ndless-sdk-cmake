/*
 * constructors.cpp — C++17 consumer test program for Ndless SDK integration tests.
 *
 * Exercises:
 *   1. Global C++ object construction (__cpp_init in crti.S) and destruction
 *      (__cpp_fini in crtn.S).
 *   2. Standard C++ library containers (std::string, std::vector) linked
 *      against libstdc++ and nspire-io syscalls.
 */

#include <libndls.h>
#include <string>
#include <vector>

/* The program's own -O2 (CMakeLists.txt) must override the SDK's default -Os. */
#ifdef __OPTIMIZE_SIZE__
#error "add_nspire_program's default -Os overrode the program's own -O2"
#endif

/* Step 1: Define a type with non-trivial construction and destruction. */
struct Lifetime {
    std::string message{"constructor"};

    ~Lifetime()
    {
        message.clear();
    }
};

/* Step 2: Instantiate a global object to require .init_array / .fini_array. */
Lifetime lifetime;

int main()
{
    /* Step 3: Exercise dynamic STL allocation and combine with global state. */
    const std::vector<unsigned> values{1, 2, 3};
    return static_cast<int>(values.size() + lifetime.message.size());
}
