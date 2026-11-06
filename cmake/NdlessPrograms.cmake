# ==============================================================================
# Ndless Application Build and Packaging Helpers (NdlessPrograms.cmake)
# ==============================================================================
# Defines add_nspire_program() for compiling, linking, patching, and packaging
# TI-Nspire Ndless executables (.elf -> .zehn -> .tns).
# ==============================================================================

include_guard(GLOBAL)

# ------------------------------------------------------------------------------
# Helper: _ndless_json_array(<out_var> [items...])
# ------------------------------------------------------------------------------
# Serializes a list of arguments into a JSON array string.
# We serialize genzehn flags and POST_LINK commands into a JSON file rather than
# embedding them directly in add_custom_command(), whose keyword parser would
# otherwise intercept user arguments such as COMMAND or DEPENDS.
function(_ndless_json_array output)
    set(_json "[")
    set(_separator "")

    foreach(_arg IN LISTS ARGN)
        string(REPLACE "\\" "\\\\" _arg "${_arg}")
        string(REPLACE "\"" "\\\"" _arg "${_arg}")
        string(REPLACE "\n" "\\n" _arg "${_arg}")
        string(REPLACE "\r" "\\r" _arg "${_arg}")
        string(REPLACE "\t" "\\t" _arg "${_arg}")
        string(APPEND _json "${_separator}\"${_arg}\"")
        set(_separator ",")
    endforeach()

    string(APPEND _json "]")
    set(${output} "${_json}" PARENT_SCOPE)
endfunction()

# ------------------------------------------------------------------------------
# Function: add_nspire_program(<name> ...)
# ------------------------------------------------------------------------------
# Creates an ARM ELF executable target (<name>, producing <name>.elf) and an
# associated packaging target (<name>_tns, producing <name>.tns).
function(add_nspire_program name)
    # --------------------------------------------------------------------------
    # Step 1: Parse and validate function arguments
    # --------------------------------------------------------------------------
    set(_options
        GC_SECTIONS
        USE_NSPIREIO
    )
    set(_one_value_keywords
        NAME
        AUTHOR
        VERSION
        NOTICE
        NDLESS_MIN
    )
    set(_multi_value_keywords
        SOURCES
        LIBRARIES
        GENZEHN_FLAGS
        POST_LINK
        POST_LINK_DEPENDS
    )
    cmake_parse_arguments(
        PARSE_ARGV 1 PRG
        "${_options}"
        "${_one_value_keywords}"
        "${_multi_value_keywords}"
    )

    if(PRG_KEYWORDS_MISSING_VALUES)
        message(FATAL_ERROR "Missing values for ${PRG_KEYWORDS_MISSING_VALUES}")
    endif()

    # Allow positional sources if SOURCES keyword was omitted.
    if(NOT PRG_SOURCES)
        set(PRG_SOURCES ${PRG_UNPARSED_ARGUMENTS})
    elseif(PRG_UNPARSED_ARGUMENTS)
        message(FATAL_ERROR "Unknown add_nspire_program arguments: ${PRG_UNPARSED_ARGUMENTS}")
    endif()

    if(NOT PRG_SOURCES)
        message(FATAL_ERROR "add_nspire_program(${name}) requires SOURCES")
    endif()

    # --------------------------------------------------------------------------
    # Step 2: Verify cross-compilation state and locate SDK directories
    # --------------------------------------------------------------------------
    if(NOT CMAKE_CROSSCOMPILING OR NOT CMAKE_C_COMPILER_ID STREQUAL "GNU")
        message(FATAL_ERROR "Select TI-Nspire-Toolchain.cmake before project()")
    endif()

    get_target_property(_root Ndless::sdk NDLESS_SDK_ROOT)
    set(_system "${_root}/system")
    set(_tools "${_root}/bin")

    # --------------------------------------------------------------------------
    # Step 3: Create the ELF executable target and attach SDK compile flags
    # --------------------------------------------------------------------------
    add_executable(${name} ${PRG_SOURCES})
    set_target_properties(${name} PROPERTIES SUFFIX .elf)
    target_link_libraries(${name} PRIVATE Ndless::sdk)

    # The upstream Makefile template's default optimization. As the target's
    # first own option it precedes any target_compile_options() the caller
    # adds afterwards, so a program's own -O level wins (on Ndless::sdk it
    # would come last and override it).
    target_compile_options(${name} PRIVATE
        "$<$<CONFIG:Release>:-Os>"
        "$<$<CONFIG:MinSizeRel>:-Os>"
    )

    # --------------------------------------------------------------------------
    # Step 4: Configure bare-metal startup objects and linker flags
    # --------------------------------------------------------------------------
    # Passing crt0.o and crti.o via target_link_options() ensures CMake places
    # them BEFORE user <OBJECTS> on the linker command line, without overriding
    # global CMAKE_<LANG>_LINK_EXECUTABLE rules for unrelated targets.
    target_link_options(${name} PRIVATE
        -mcpu=arm926ej-s
        -nostdlib
        -static
        "${_system}/crt0.o"
        "${_system}/crti.o"
        -Wl,--pic-veneer
        -Wl,--emit-relocs
        -Wl,-u,_malloc_r
        "-Wl,-T,${_system}/ldscript"
    )
    if(PRG_GC_SECTIONS)
        target_link_options(${name} PRIVATE -Wl,--gc-sections)
    endif()

    # --------------------------------------------------------------------------
    # Step 5: Resolve library dependencies and teardown object ordering
    # --------------------------------------------------------------------------
    # Select standard or nspire-io-backed syscall library.
    set(_syscalls Ndless::syscalls)
    if(PRG_USE_NSPIREIO OR Ndless_USE_NSPIREIO)
        set(_syscalls Ndless::syscalls_nspireio)
    endif()

    # Map shorthand library names (e.g. "z", "SDL") to imported Ndless:: targets.
    set(_libraries)
    foreach(_lib IN LISTS PRG_LIBRARIES)
        if(_lib STREQUAL "z")
            list(APPEND _libraries Ndless::zlib)
        elseif(TARGET Ndless::${_lib})
            list(APPEND _libraries Ndless::${_lib})
        else()
            list(APPEND _libraries "${_lib}")
        endif()
    endforeach()

    if(NDLESS_USER_LIB_DIR)
        target_link_directories(${name} PRIVATE "${NDLESS_USER_LIB_DIR}")
    endif()

    # Link user libraries followed by the SDK/Newlib runtime group, libgcc, and
    # finally crtn.o (placed AFTER user objects and libraries to close .init/.fini).
    target_link_libraries(${name} PRIVATE
        ${_libraries}
        -Wl,--start-group
            Ndless::nspireio
            stdc++
            Ndless::ndls
            ${_syscalls}
            m
            c
        -Wl,--end-group
        gcc
        "${_system}/crtn.o"
    )

    # Ensure relinking occurs if the linker script or startup objects change.
    set_property(
        TARGET ${name}
        APPEND PROPERTY LINK_DEPENDS
            "${_system}/ldscript"
            "${_system}/crt0.o"
            "${_system}/crti.o"
            "${_system}/crtn.o"
    )

    # --------------------------------------------------------------------------
    # Step 6: Build genzehn metadata flags and write per-config arguments JSON
    # --------------------------------------------------------------------------
    set(_flags)
    if(NOT DEFINED PRG_NAME)
        set(PRG_NAME "${name}")
    endif()

    set(_metadata_mappings
        "NAME|name"
        "AUTHOR|author"
        "VERSION|version"
        "NOTICE|notice"
        "NDLESS_MIN|ndless-min"
    )
    foreach(_entry IN LISTS _metadata_mappings)
        string(REPLACE "|" ";" _entry "${_entry}")
        list(GET _entry 0 _key)
        list(GET _entry 1 _flag)
        if(DEFINED PRG_${_key})
            list(APPEND _flags "--${_flag}" "${PRG_${_key}}")
        endif()
    endforeach()
    list(APPEND _flags ${PRG_GENZEHN_FLAGS})

    _ndless_json_array(_flags_json ${_flags})
    _ndless_json_array(_commands_json ${PRG_POST_LINK})

    set(_arguments "${CMAKE_CURRENT_BINARY_DIR}/.ndless/${name}/$<CONFIG>/arguments.json")
    file(
        GENERATE
        OUTPUT "${_arguments}"
        CONTENT "{\"flags\":${_flags_json},\"commands\":${_commands_json}}\n"
        TARGET ${name}
    )

    # --------------------------------------------------------------------------
    # Step 7: Register custom command and target to package <name>.tns
    # --------------------------------------------------------------------------
    set(_out "${CMAKE_CURRENT_BINARY_DIR}")
    if(CMAKE_CONFIGURATION_TYPES)
        string(APPEND _out "/$<CONFIG>")
    endif()
    set(_tns "${_out}/${name}.tns")

    # Track packaging outputs independently of relinking. Deleting a .tns or
    # modifying a converter, loader, or patch script reruns package_program.py
    # on a private copy of the ELF without mutating the linker output.
    add_custom_command(
        OUTPUT "${_tns}"
        COMMAND
            "${Python3_EXECUTABLE}"
            "${_tools}/package_program.py"
            --input "$<TARGET_FILE:${name}>"
            --output "${_tns}"
            --tool-dir "${_tools}"
            --arguments-json "${_arguments}"
        DEPENDS
            ${name}
            "${_arguments}"
            "${_tools}/package_program.py"
            "${_tools}/genzehn.py"
            "${_tools}/make_prg.py"
            "${_tools}/zehn_loader.tns"
            "${_tools}/zehn_loader_compressed.tns"
            ${PRG_POST_LINK_DEPENDS}
        COMMENT "Packaging ${name}.tns"
        VERBATIM
    )

    add_custom_target(${name}_tns ALL DEPENDS "${_tns}")
    set_property(TARGET ${name} PROPERTY NDLESS_TNS_FILE "${_tns}")
endfunction()
