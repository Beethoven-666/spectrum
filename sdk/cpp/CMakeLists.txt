# H1 spectrometer C++ SDK build.
#
# Outputs a static library target `h1::sdk` plus tests, examples, and a
# small CLI tool. Tests and CLI pull doctest / CLI11 via FetchContent so
# there are no system dependencies beyond a C++17 compiler.

cmake_minimum_required(VERSION 3.16)
project(h1_sdk
        VERSION 0.1.0
        DESCRIPTION "H1 spectrometer SDK"
        LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(H1_SDK_BUILD_TESTS    "Build h1 SDK unit tests"        ON)
option(H1_SDK_BUILD_EXAMPLES "Build h1 SDK examples and CLI"  ON)

# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------

set(H1_SDK_SOURCES
    src/Device.cpp
    src/Framing.cpp
    src/Protocol.cpp
    src/Types.cpp
    src/UnixSerialPort.cpp
    src/WinSerialPort.cpp
)

add_library(h1_sdk STATIC ${H1_SDK_SOURCES})
add_library(h1::sdk ALIAS h1_sdk)

target_include_directories(h1_sdk
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_compile_features(h1_sdk PUBLIC cxx_std_17)

if(MSVC)
    target_compile_options(h1_sdk PRIVATE /W4 /permissive-)
else()
    target_compile_options(h1_sdk PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(UNIX AND NOT APPLE)
    # pthreads for std::thread on Linux.
    find_package(Threads REQUIRED)
    target_link_libraries(h1_sdk PUBLIC Threads::Threads)
elseif(APPLE)
    find_package(Threads REQUIRED)
    target_link_libraries(h1_sdk PUBLIC Threads::Threads)
endif()

# ---------------------------------------------------------------------------
# Tests (doctest)
# ---------------------------------------------------------------------------

if(H1_SDK_BUILD_TESTS)
    include(FetchContent)
    # doctest still ships `cmake_minimum_required(3.0)`, which CMake 4 refuses.
    # Inject the policy override so the build works on both CMake 3.16+ and 4.x.
    set(CMAKE_POLICY_VERSION_MINIMUM "3.5" CACHE STRING "" FORCE)
    FetchContent_Declare(
        doctest
        GIT_REPOSITORY https://github.com/doctest/doctest.git
        GIT_TAG        v2.4.11
        GIT_SHALLOW    TRUE
    )
    FetchContent_MakeAvailable(doctest)

    add_executable(h1_sdk_tests
        tests/main.cpp
        tests/test_protocol_encode.cpp
        tests/test_protocol_decode.cpp
        tests/test_spectrum_frame.cpp
        tests/test_device.cpp
    )
    target_link_libraries(h1_sdk_tests PRIVATE h1_sdk doctest::doctest)
    target_include_directories(h1_sdk_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
    if(MSVC)
        target_compile_options(h1_sdk_tests PRIVATE /W4)
    else()
        target_compile_options(h1_sdk_tests PRIVATE -Wall -Wextra -Wpedantic)
    endif()

    enable_testing()
    add_test(NAME h1_sdk_tests COMMAND h1_sdk_tests)
endif()

# ---------------------------------------------------------------------------
# Examples + CLI (CLI11)
# ---------------------------------------------------------------------------

if(H1_SDK_BUILD_EXAMPLES)
    include(FetchContent)
    FetchContent_Declare(
        cli11
        GIT_REPOSITORY https://github.com/CLIUtils/CLI11.git
        GIT_TAG        v2.4.2
        GIT_SHALLOW    TRUE
    )
    FetchContent_MakeAvailable(cli11)

    set(H1_EXAMPLES
        01_device_info
        02_capture_once
        03_stream
        04_exposure_control
        05_efficiency_curve
    )
    foreach(ex ${H1_EXAMPLES})
        add_executable(${ex} examples/${ex}.cpp)
        target_link_libraries(${ex} PRIVATE h1_sdk)
        if(NOT MSVC)
            target_compile_options(${ex} PRIVATE -Wall -Wextra -Wpedantic)
        endif()
    endforeach()

    add_executable(h1_cli examples/cli.cpp)
    target_link_libraries(h1_cli PRIVATE h1_sdk CLI11::CLI11)
    if(NOT MSVC)
        target_compile_options(h1_cli PRIVATE -Wall -Wextra -Wpedantic)
    endif()
endif()
