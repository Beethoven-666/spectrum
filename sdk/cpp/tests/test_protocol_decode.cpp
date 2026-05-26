// tests/test_protocol_decode.cpp -- response parsing tests against
// PROTOCOL.md §9.2 + checksum/error-code negative tests (§9.3).
#include <doctest/doctest.h>

#include <cstdint>
#include <vector>

#include "HexUtils.hpp"
#include "Protocol.hpp"
#include "h1/Errors.hpp"

using namespace h1;
using namespace h1::testing;

namespace {

// Helper: parse and return the validData bytes as a vector.
std::vector<std::uint8_t> parseValid(const std::vector<std::uint8_t>& frame,
                                     std::uint8_t expectedCmd) {
    const std::uint8_t* vp = nullptr;
    std::size_t vlen = 0;
    proto::parseResponse(frame.data(), frame.size(), expectedCmd, &vp, &vlen);
    return {vp, vp + vlen};
}

}  // namespace

TEST_CASE("decode DeviceInfo response -> SN string") {
    auto frame = hex(
        "CC 81 21 00 00 08 "
        "48 31 31 42 36 56 31 30 35 33 34 43 46 50 44 2D 31 30 30 2D 30 30 30 32 "
        "B5 0D 0A");
    auto valid = parseValid(frame, proto::kCmdGetDeviceInfo);
    REQUIRE(valid.size() == 24);
    std::string sn(valid.begin(), valid.end());
    CHECK(sn == "H11B6V10534CFPD-100-0002");
}

TEST_CASE("decode WavelengthRange response -> {340, 1050}") {
    auto frame = hex("CC 81 0D 00 00 0F 54 01 1A 04 DC 0D 0A");
    auto valid = parseValid(frame, proto::kCmdGetWavelengthRange);
    REQUIRE(valid.size() == 4);
    const std::uint16_t start = static_cast<std::uint16_t>(valid[0] | (valid[1] << 8));
    const std::uint16_t end = static_cast<std::uint16_t>(valid[2] | (valid[3] << 8));
    CHECK(start == 340);
    CHECK(end == 1050);
}

TEST_CASE("decode GetExposureTime response -> 100000") {
    auto frame = hex("CC 81 0D 00 00 0D A0 86 01 00 8E 0D 0A");
    auto valid = parseValid(frame, proto::kCmdGetExposureTime);
    REQUIRE(valid.size() == 4);
    const std::uint32_t v = static_cast<std::uint32_t>(valid[0]) |
                            (static_cast<std::uint32_t>(valid[1]) << 8) |
                            (static_cast<std::uint32_t>(valid[2]) << 16) |
                            (static_cast<std::uint32_t>(valid[3]) << 24);
    CHECK(v == 100000u);
}

TEST_CASE("decode GetMaxExposureTime response -> 1000000") {
    auto frame = hex("CC 81 0D 00 00 14 40 42 0F 00 FF 0D 0A");
    auto valid = parseValid(frame, proto::kCmdGetMaxExposureTime);
    REQUIRE(valid.size() == 4);
    const std::uint32_t v = static_cast<std::uint32_t>(valid[0]) |
                            (static_cast<std::uint32_t>(valid[1]) << 8) |
                            (static_cast<std::uint32_t>(valid[2]) << 16) |
                            (static_cast<std::uint32_t>(valid[3]) << 24);
    CHECK(v == 1000000u);
}

TEST_CASE("decode GetCieMode response -> Cie2015_2") {
    auto frame = hex("CC 81 0A 00 00 37 02 90 0D 0A");
    auto valid = parseValid(frame, proto::kCmdGetCieMode);
    REQUIRE(valid.size() == 1);
    CHECK(static_cast<CieMode>(valid[0]) == CieMode::Cie2015_2);
}

TEST_CASE("set-style success response does not throw") {
    auto frame = hex("CC 81 0A 00 00 0A 00 61 0D 0A");
    CHECK_NOTHROW(proto::parseStatusResponse(frame.data(), frame.size(),
                                             proto::kCmdSetExposureMode));
}

TEST_CASE("set-style 0x15 response throws DeviceError with code=0x15") {
    auto frame = hex("CC 81 0A 00 00 0A 15 76 0D 0A");
    try {
        proto::parseStatusResponse(frame.data(), frame.size(), proto::kCmdSetExposureMode);
        FAIL("expected DeviceError to be thrown");
    } catch (const DeviceError& e) {
        CHECK(e.code() == 0x15);
        CHECK(e.cmdType() == proto::kCmdSetExposureMode);
    }
}

TEST_CASE("set-style 0xFF response throws DeviceError with code=0xFF") {
    auto frame = hex("CC 81 0A 00 00 0A FF 60 0D 0A");
    try {
        proto::parseStatusResponse(frame.data(), frame.size(), proto::kCmdSetExposureMode);
        FAIL("expected DeviceError to be thrown");
    } catch (const DeviceError& e) {
        CHECK(e.code() == 0xFF);
        CHECK(e.cmdType() == proto::kCmdSetExposureMode);
    }
}

TEST_CASE("set-style 0x12 (SetExposureTime success) does not throw") {
    auto frame = hex("CC 81 0A 00 00 0C 00 63 0D 0A");
    CHECK_NOTHROW(proto::parseStatusResponse(frame.data(), frame.size(),
                                             proto::kCmdSetExposureTime));
}

TEST_CASE("bad checksum -> ProtocolError") {
    // Flip the checksum byte in the SetExposureMode success frame.
    auto frame = hex("CC 81 0A 00 00 0A 00 99 0D 0A");
    CHECK_THROWS_AS(proto::parseStatusResponse(frame.data(), frame.size(),
                                               proto::kCmdSetExposureMode),
                    ProtocolError);
}

TEST_CASE("bad header -> ProtocolError") {
    auto frame = hex("CC 80 0A 00 00 0A 00 61 0D 0A");
    CHECK_THROWS_AS(proto::parseStatusResponse(frame.data(), frame.size(),
                                               proto::kCmdSetExposureMode),
                    ProtocolError);
}

TEST_CASE("bad footer -> ProtocolError") {
    auto frame = hex("CC 81 0A 00 00 0A 00 61 0D 0B");
    CHECK_THROWS_AS(proto::parseStatusResponse(frame.data(), frame.size(),
                                               proto::kCmdSetExposureMode),
                    ProtocolError);
}

TEST_CASE("truncated frame -> ProtocolError") {
    auto frame = hex("CC 81 0A 00");
    CHECK_THROWS_AS(proto::parseStatusResponse(frame.data(), frame.size(),
                                               proto::kCmdSetExposureMode),
                    ProtocolError);
}

TEST_CASE("dataType mismatch -> ProtocolError") {
    // SetExposureMode success frame but we ask for cmdType=0x0C.
    auto frame = hex("CC 81 0A 00 00 0A 00 61 0D 0A");
    CHECK_THROWS_AS(proto::parseStatusResponse(frame.data(), frame.size(),
                                               proto::kCmdSetExposureTime),
                    ProtocolError);
}

TEST_CASE("totalLen mismatch -> ProtocolError") {
    // Claim len=11 but only 10 bytes provided.
    auto frame = hex("CC 81 0B 00 00 0A 00 61 0D 0A");
    CHECK_THROWS_AS(proto::parseStatusResponse(frame.data(), frame.size(),
                                               proto::kCmdSetExposureMode),
                    ProtocolError);
}
