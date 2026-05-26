// src/Protocol.hpp -- pure functions for encoding commands and decoding
// responses. No I/O, no state -- everything in this header takes byte
// spans in and out so it can be unit tested directly against PROTOCOL.md
// test vectors.
#pragma once

#include <cstdint>
#include <vector>

#include "h1/Types.hpp"

namespace h1::proto {

// Frame protocol constants. Magic bytes are spelled out as named constants
// to keep grep-ability when staring at hex dumps.
constexpr std::uint8_t kFrameHeader0 = 0xCC;
constexpr std::uint8_t kCmdHeader1 = 0x01;
constexpr std::uint8_t kRespHeader1 = 0x81;
constexpr std::uint8_t kFooter0 = 0x0D;
constexpr std::uint8_t kFooter1 = 0x0A;

// Total framing overhead (header2 + len3 + cmdType1 + checksum1 + footer2).
constexpr std::size_t kFrameOverhead = 9;

// Command IDs (PROTOCOL.md §3.1).
constexpr std::uint8_t kCmdStopCapture = 0x04;
constexpr std::uint8_t kCmdGetDeviceInfo = 0x08;
constexpr std::uint8_t kCmdSetExposureMode = 0x0A;
constexpr std::uint8_t kCmdGetExposureMode = 0x0B;
constexpr std::uint8_t kCmdSetExposureTime = 0x0C;
constexpr std::uint8_t kCmdGetExposureTime = 0x0D;
constexpr std::uint8_t kCmdGetWavelengthRange = 0x0F;
constexpr std::uint8_t kCmdSetMaxExposureTime = 0x13;
constexpr std::uint8_t kCmdGetMaxExposureTime = 0x14;
constexpr std::uint8_t kCmdSendEfficiencyCurve = 0x23;
constexpr std::uint8_t kCmdResetEfficiencyCurve = 0x25;
constexpr std::uint8_t kCmdVerifyEfficiencyCurve = 0x27;
constexpr std::uint8_t kCmdCaptureSingleNoTm30 = 0x32;
constexpr std::uint8_t kCmdStartStreamNoTm30 = 0x33;
constexpr std::uint8_t kCmdCaptureSingleWithTm30 = 0x34;
constexpr std::uint8_t kCmdStartStreamWithTm30 = 0x35;
constexpr std::uint8_t kCmdSetCieMode = 0x36;
constexpr std::uint8_t kCmdGetCieMode = 0x37;
constexpr std::uint8_t kCmdEnterExitSleep = 0x40;
constexpr std::uint8_t kCmdSetWorkingMode = 0x41;

// Device status codes (PROTOCOL.md §3.2).
constexpr std::uint8_t kStatusOk = 0x00;
constexpr std::uint8_t kStatusInvalid = 0x15;
constexpr std::uint8_t kStatusUnsupported = 0xFF;

// Build a complete command frame. `cmdData` may be empty.
std::vector<std::uint8_t> buildCommand(std::uint8_t cmdType,
                                       const std::uint8_t* cmdData = nullptr,
                                       std::size_t cmdDataLen = 0);

// Convenience overload.
inline std::vector<std::uint8_t> buildCommand(std::uint8_t cmdType,
                                              const std::vector<std::uint8_t>& cmdData) {
    return buildCommand(cmdType, cmdData.data(), cmdData.size());
}

// Validate a fully-received response frame and return a pointer/length
// view of the validData section. Throws ProtocolError or DeviceError when
// validation or the device status byte indicates failure. The caller is
// expected to know the expected cmdType -- if `expectedCmdType` is
// non-zero we check it matches the dataType byte.
//
// `validDataOut` is set to point inside `frame` (no copy). The frame
// buffer must outlive the use of validDataOut.
void parseResponse(const std::uint8_t* frame, std::size_t frameLen,
                   std::uint8_t expectedCmdType,
                   const std::uint8_t** validDataOut, std::size_t* validDataLenOut);

// Same as parseResponse but additionally interprets validData as a single
// status byte (used by all "set" commands). Throws DeviceError for 0x15/0xFF.
void parseStatusResponse(const std::uint8_t* frame, std::size_t frameLen,
                         std::uint8_t expectedCmdType);

// Total-frame length from the 3-byte little-endian length field at offset 2.
// Returns 0 if `frame` is too short to read the length field.
std::size_t readTotalLen(const std::uint8_t* frame, std::size_t frameLen);

// Compute the 1-byte checksum (sum of all bytes prior to the checksum
// position, masked to 8 bits).
std::uint8_t checksum(const std::uint8_t* bytes, std::size_t len);

// ----- SpectrumFrame decoding -----------------------------------------
//
// `validData` is the validData payload (excluding header/checksum/footer).
// `wavelengthCount` = end - start + 1 (the number of u16 raw samples).
SpectrumFrame decodeSpectrumFrame(const std::uint8_t* validData,
                                  std::size_t validDataLen,
                                  std::size_t wavelengthCount,
                                  bool includeTm30);

}  // namespace h1::proto
