// tests/test_protocol_encode.cpp -- verifies each command produces the
// exact byte sequence from PROTOCOL.md §9.1.
#include <doctest/doctest.h>

#include <cstdint>
#include <vector>

#include "HexUtils.hpp"
#include "Protocol.hpp"

using namespace h1;
using namespace h1::testing;

namespace {

std::vector<std::uint8_t> b(std::uint8_t cmd) {
    return proto::buildCommand(cmd);
}

std::vector<std::uint8_t> b(std::uint8_t cmd, std::initializer_list<std::uint8_t> data) {
    std::vector<std::uint8_t> v(data);
    return proto::buildCommand(cmd, v.data(), v.size());
}

}  // namespace

TEST_CASE("encode StopCapture (0x04)") {
    requireBytesEqual(b(proto::kCmdStopCapture), hex("CC 01 09 00 00 04 DA 0D 0A"));
}

TEST_CASE("encode GetDeviceInfo (0x08, length=0x18)") {
    requireBytesEqual(b(proto::kCmdGetDeviceInfo, {0x18}),
                      hex("CC 01 0A 00 00 08 18 F7 0D 0A"));
}

TEST_CASE("encode SetExposureMode Manual (0x0A 0x00)") {
    requireBytesEqual(b(proto::kCmdSetExposureMode, {0x00}),
                      hex("CC 01 0A 00 00 0A 00 E1 0D 0A"));
}

TEST_CASE("encode SetExposureMode Auto (0x0A 0x01)") {
    requireBytesEqual(b(proto::kCmdSetExposureMode, {0x01}),
                      hex("CC 01 0A 00 00 0A 01 E2 0D 0A"));
}

TEST_CASE("encode GetExposureMode (0x0B)") {
    requireBytesEqual(b(proto::kCmdGetExposureMode), hex("CC 01 09 00 00 0B E1 0D 0A"));
}

TEST_CASE("encode SetExposureTime(100000us) (0x0C)") {
    // 100000 = 0x000186A0 -> LE: A0 86 01 00
    requireBytesEqual(b(proto::kCmdSetExposureTime, {0xA0, 0x86, 0x01, 0x00}),
                      hex("CC 01 0D 00 00 0C A0 86 01 00 0D 0D 0A"));
}

TEST_CASE("encode GetExposureTime (0x0D)") {
    requireBytesEqual(b(proto::kCmdGetExposureTime), hex("CC 01 09 00 00 0D E3 0D 0A"));
}

TEST_CASE("encode GetWavelengthRange (0x0F)") {
    requireBytesEqual(b(proto::kCmdGetWavelengthRange),
                      hex("CC 01 09 00 00 0F E5 0D 0A"));
}

TEST_CASE("encode SetMaxExposureTime(5000000us) (0x13)") {
    // 5000000 = 0x004C4B40 -> LE: 40 4B 4C 00
    requireBytesEqual(b(proto::kCmdSetMaxExposureTime, {0x40, 0x4B, 0x4C, 0x00}),
                      hex("CC 01 0D 00 00 13 40 4B 4C 00 C4 0D 0A"));
}

TEST_CASE("encode GetMaxExposureTime (0x14)") {
    requireBytesEqual(b(proto::kCmdGetMaxExposureTime),
                      hex("CC 01 09 00 00 14 EA 0D 0A"));
}

TEST_CASE("encode SendEfficiencyCurveStart (0x23 0x04)") {
    requireBytesEqual(b(proto::kCmdSendEfficiencyCurve, {0x04}),
                      hex("CC 01 0A 00 00 23 04 FE 0D 0A"));
}

TEST_CASE("encode VerifyEfficiencyCurve (0x27)") {
    requireBytesEqual(b(proto::kCmdVerifyEfficiencyCurve),
                      hex("CC 01 09 00 00 27 FD 0D 0A"));
}

TEST_CASE("encode ResetEfficiencyCurve (0x25)") {
    requireBytesEqual(b(proto::kCmdResetEfficiencyCurve),
                      hex("CC 01 09 00 00 25 FB 0D 0A"));
}

TEST_CASE("encode CaptureSingleNoTm30 (0x32)") {
    requireBytesEqual(b(proto::kCmdCaptureSingleNoTm30),
                      hex("CC 01 09 00 00 32 08 0D 0A"));
}

TEST_CASE("encode StartStreamNoTm30 (0x33)") {
    requireBytesEqual(b(proto::kCmdStartStreamNoTm30),
                      hex("CC 01 09 00 00 33 09 0D 0A"));
}

TEST_CASE("encode CaptureSingleWithTm30 (0x34)") {
    requireBytesEqual(b(proto::kCmdCaptureSingleWithTm30),
                      hex("CC 01 09 00 00 34 0A 0D 0A"));
}

TEST_CASE("encode StartStreamWithTm30 (0x35)") {
    requireBytesEqual(b(proto::kCmdStartStreamWithTm30),
                      hex("CC 01 09 00 00 35 0B 0D 0A"));
}

TEST_CASE("encode SetCieMode Cie2015_2 (0x36 0x02)") {
    requireBytesEqual(b(proto::kCmdSetCieMode, {0x02}),
                      hex("CC 01 0A 00 00 36 02 0F 0D 0A"));
}

TEST_CASE("encode GetCieMode (0x37)") {
    requireBytesEqual(b(proto::kCmdGetCieMode), hex("CC 01 09 00 00 37 0D 0D 0A"));
}

TEST_CASE("encode EnterExitSleep (0x40)") {
    requireBytesEqual(b(proto::kCmdEnterExitSleep), hex("CC 01 09 00 00 40 16 0D 0A"));
}

TEST_CASE("encode SetWorkingMode Trigger (0x41 0x01)") {
    requireBytesEqual(b(proto::kCmdSetWorkingMode, {0x01}),
                      hex("CC 01 0A 00 00 41 01 19 0D 0A"));
}

TEST_CASE("checksum helper matches manual sums") {
    // "CC 01 09 00 00 04" sums to 0xDA.
    const std::uint8_t bytes[] = {0xCC, 0x01, 0x09, 0x00, 0x00, 0x04};
    CHECK(proto::checksum(bytes, sizeof(bytes)) == 0xDA);
}
