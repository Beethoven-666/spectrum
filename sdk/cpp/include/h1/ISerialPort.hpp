// h1/ISerialPort.hpp -- minimal abstraction over a blocking serial port.
//
// The SDK depends only on this interface; tests inject a MockSerialPort,
// production code uses the openSerialPort() factory which returns the
// platform-appropriate concrete implementation.
#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>

namespace h1 {

class ISerialPort {
public:
    virtual ~ISerialPort() = default;

    // Write all `len` bytes. Returns the number actually written; callers
    // should treat anything less than `len` as a failure.
    virtual std::size_t write(const std::uint8_t* data, std::size_t len) = 0;

    // Block until at least one byte is available or `timeout` elapses, then
    // read up to `max_len` bytes. Returns the count read; returning 0 means
    // the timeout fired.
    virtual std::size_t read(std::uint8_t* buf, std::size_t max_len,
                             std::chrono::milliseconds timeout) = 0;

    virtual void close() = 0;
};

// Open `path` (e.g. "/dev/tty.usbserial-XXXX" or "COM5") at `baud` with
// 8N1 / no flow control. Throws std::runtime_error on failure.
std::unique_ptr<ISerialPort> openSerialPort(const std::string& path, int baud = 115200);

}  // namespace h1
