// h1/Esp32SerialPort.hpp -- ISerialPort backed by ESP-IDF's uart_driver.
//
// Open one UART, map it to the given RX/TX GPIOs, and hand back an
// ISerialPort that the rest of the SDK uses without knowing it's on
// FreeRTOS.
#pragma once

#include <cstdint>
#include <memory>

#include "driver/uart.h"
#include "h1/ISerialPort.hpp"

namespace h1 {

// Open `port` at `baud` (8N1, no flow control) on the given pins. `rxBufSize`
// is the UART driver's RX ring buffer in bytes -- must be > 256 and big
// enough to hold the largest expected frame (~4 KB for a full TM30 packet).
//
// Throws std::runtime_error if any of the underlying esp-idf calls fail.
std::unique_ptr<ISerialPort> openEsp32SerialPort(
    uart_port_t port,
    int rxPin,
    int txPin,
    int baud = 115200,
    int rxBufSize = 8192);

}  // namespace h1
