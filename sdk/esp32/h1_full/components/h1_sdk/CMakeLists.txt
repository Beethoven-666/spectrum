# h1_sdk -- ESP-IDF component wrapping the platform-neutral C++ SDK.
#
# Strategy: reuse the SDK sources from sdk/cpp/ verbatim (Device/Framing/
# Protocol/Types are platform-neutral) and add an ESP32 implementation of
# the ISerialPort interface on top.
#
# UnixSerialPort.cpp and WinSerialPort.cpp are gated by #ifdef and compile
# to empty translation units on ESP32, but we leave them out of the source
# list to keep the build clean.

set(SDK_BASE ${CMAKE_CURRENT_LIST_DIR}/../../../../cpp)

idf_component_register(
    SRCS
        "${SDK_BASE}/src/Device.cpp"
        "${SDK_BASE}/src/Framing.cpp"
        "${SDK_BASE}/src/Protocol.cpp"
        "${SDK_BASE}/src/Types.cpp"
        "src/Esp32SerialPort.cpp"
    INCLUDE_DIRS
        "${SDK_BASE}/include"
        "include"
    PRIV_INCLUDE_DIRS
        "${SDK_BASE}/src"
    REQUIRES esp_driver_uart esp_driver_gpio pthread
)

# SDK uses C++17.
target_compile_features(${COMPONENT_LIB} PUBLIC cxx_std_17)
