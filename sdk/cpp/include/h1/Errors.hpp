// h1/Errors.hpp -- exception hierarchy for the H1 SDK.
//
// All errors derive from H1Error (which derives from std::runtime_error).
// Callers can catch the base class for any SDK error, or one of the
// specific subclasses to handle a particular failure mode.
#pragma once

#include <cstdint>
#include <stdexcept>
#include <string>

namespace h1 {

class H1Error : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// Protocol violations: bad header/footer, checksum mismatch, wrong totalLen,
// unexpected dataType, truncated frame, etc.
class ProtocolError : public H1Error {
public:
    using H1Error::H1Error;
};

// Serial port read timed out.
class TimeoutError : public H1Error {
public:
    using H1Error::H1Error;
};

// Device returned an error status (0x15 invalid command, 0xFF unsupported/out-of-range).
class DeviceError : public H1Error {
public:
    DeviceError(std::uint8_t code, std::uint8_t cmdType, const std::string& msg)
        : H1Error(msg), code_(code), cmdType_(cmdType) {}

    std::uint8_t code() const noexcept { return code_; }
    std::uint8_t cmdType() const noexcept { return cmdType_; }

private:
    std::uint8_t code_;
    std::uint8_t cmdType_;
};

}  // namespace h1
