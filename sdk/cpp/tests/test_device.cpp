// tests/test_device.cpp -- end-to-end tests for the Device class using a
// MockSerialPort. We script per-command responses and verify the SDK
// drives the correct command bytes and surfaces the right errors.
#include <doctest/doctest.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <thread>
#include <vector>

#include "HexUtils.hpp"
#include "MockSerialPort.hpp"
#include "Protocol.hpp"
#include "h1/Device.hpp"
#include "h1/Errors.hpp"

using namespace h1;
using namespace h1::testing;
using namespace std::chrono_literals;


TEST_CASE("Device::getDeviceInfo decodes 24-char SN") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();
    mock->onWrite([mock](const std::vector<std::uint8_t>& frame) {
        if (frame.size() >= 6 && frame[5] == proto::kCmdGetDeviceInfo) {
            mock->queueResponse(hex(
                "CC 81 21 00 00 08 "
                "48 31 31 42 36 56 31 30 35 33 34 43 46 50 44 2D 31 30 30 2D 30 30 30 32 "
                "B5 0D 0A"));
        }
    });
    Device dev(std::move(mockOwn));
    auto info = dev.getDeviceInfo();
    CHECK(info.serialNumber == "H11B6V10534CFPD-100-0002");

    // Verify SDK wrote the right command bytes.
    auto frames = mock->writtenFrames();
    REQUIRE(frames.size() == 1);
    requireBytesEqual(frames[0], hex("CC 01 0A 00 00 08 18 F7 0D 0A"));
}

TEST_CASE("Device::getWavelengthRange returns 340..1050") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();
    mock->onWrite([mock](const std::vector<std::uint8_t>& frame) {
        if (frame.size() >= 6 && frame[5] == proto::kCmdGetWavelengthRange) {
            mock->queueResponse(hex("CC 81 0D 00 00 0F 54 01 1A 04 DC 0D 0A"));
        }
    });
    Device dev(std::move(mockOwn));
    auto wr = dev.getWavelengthRange();
    CHECK(wr.start == 340);
    CHECK(wr.end == 1050);
    CHECK(wr.count() == 711u);
}

TEST_CASE("Device::setExposureMode(Manual) drives correct bytes and accepts success") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();
    mock->onWrite([mock](const std::vector<std::uint8_t>& frame) {
        if (frame.size() >= 6 && frame[5] == proto::kCmdSetExposureMode) {
            mock->queueResponse(hex("CC 81 0A 00 00 0A 00 61 0D 0A"));
        }
    });
    Device dev(std::move(mockOwn));
    CHECK_NOTHROW(dev.setExposureMode(ExposureMode::Manual));
    auto frames = mock->writtenFrames();
    REQUIRE(frames.size() == 1);
    requireBytesEqual(frames[0], hex("CC 01 0A 00 00 0A 00 E1 0D 0A"));
}

TEST_CASE("Device::setExposureMode throws DeviceError on 0x15") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();
    mock->onWrite([mock](const std::vector<std::uint8_t>& frame) {
        if (frame.size() >= 6 && frame[5] == proto::kCmdSetExposureMode) {
            mock->queueResponse(hex("CC 81 0A 00 00 0A 15 76 0D 0A"));
        }
    });
    Device dev(std::move(mockOwn));
    try {
        dev.setExposureMode(ExposureMode::Auto);
        FAIL("expected DeviceError");
    } catch (const DeviceError& e) {
        CHECK(e.code() == 0x15);
        CHECK(e.cmdType() == proto::kCmdSetExposureMode);
    }
}

TEST_CASE("Device::getExposureTimeUs decodes 100000") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();
    mock->onWrite([mock](const std::vector<std::uint8_t>& frame) {
        if (frame.size() >= 6 && frame[5] == proto::kCmdGetExposureTime) {
            mock->queueResponse(hex("CC 81 0D 00 00 0D A0 86 01 00 8E 0D 0A"));
        }
    });
    Device dev(std::move(mockOwn));
    CHECK(dev.getExposureTimeUs() == 100000u);
}

TEST_CASE("Device::setExposureTimeUs(100000) writes 0x0C with LE u32") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();
    mock->onWrite([mock](const std::vector<std::uint8_t>& frame) {
        if (frame.size() >= 6 && frame[5] == proto::kCmdSetExposureTime) {
            mock->queueResponse(hex("CC 81 0A 00 00 0C 00 63 0D 0A"));
        }
    });
    Device dev(std::move(mockOwn));
    CHECK_NOTHROW(dev.setExposureTimeUs(100000));
    auto frames = mock->writtenFrames();
    REQUIRE(frames.size() == 1);
    requireBytesEqual(frames[0], hex("CC 01 0D 00 00 0C A0 86 01 00 0D 0D 0A"));
}

TEST_CASE("Device::getMaxExposureTimeUs decodes 1000000") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();
    mock->onWrite([mock](const std::vector<std::uint8_t>& frame) {
        if (frame.size() >= 6 && frame[5] == proto::kCmdGetMaxExposureTime) {
            mock->queueResponse(hex("CC 81 0D 00 00 14 40 42 0F 00 FF 0D 0A"));
        }
    });
    Device dev(std::move(mockOwn));
    CHECK(dev.getMaxExposureTimeUs() == 1000000u);
}

TEST_CASE("Device::setMaxExposureTimeUs(5000000) -> 0x13") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();
    mock->onWrite([mock](const std::vector<std::uint8_t>& frame) {
        if (frame.size() >= 6 && frame[5] == proto::kCmdSetMaxExposureTime) {
            mock->queueResponse(hex("CC 81 0A 00 00 13 00 6A 0D 0A"));
        }
    });
    Device dev(std::move(mockOwn));
    CHECK_NOTHROW(dev.setMaxExposureTimeUs(5000000));
    auto frames = mock->writtenFrames();
    REQUIRE(frames.size() == 1);
    requireBytesEqual(frames[0], hex("CC 01 0D 00 00 13 40 4B 4C 00 C4 0D 0A"));
}

TEST_CASE("Device::getExposureMode + getCieMode round trips") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();
    mock->onWrite([mock](const std::vector<std::uint8_t>& frame) {
        if (frame.size() >= 6 && frame[5] == proto::kCmdGetExposureMode) {
            mock->queueResponse(hex("CC 81 0A 00 00 0B 01 63 0D 0A"));
        } else if (frame.size() >= 6 && frame[5] == proto::kCmdGetCieMode) {
            mock->queueResponse(hex("CC 81 0A 00 00 37 02 90 0D 0A"));
        }
    });
    Device dev(std::move(mockOwn));
    CHECK(dev.getExposureMode() == ExposureMode::Auto);
    CHECK(dev.getCieMode() == CieMode::Cie2015_2);
}

TEST_CASE("Device::setCieMode(Cie2015_2) drives correct bytes") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();
    mock->onWrite([mock](const std::vector<std::uint8_t>& frame) {
        if (frame.size() >= 6 && frame[5] == proto::kCmdSetCieMode) {
            mock->queueResponse(hex("CC 81 0A 00 00 36 00 8D 0D 0A"));
        }
    });
    Device dev(std::move(mockOwn));
    CHECK_NOTHROW(dev.setCieMode(CieMode::Cie2015_2));
    auto frames = mock->writtenFrames();
    REQUIRE(frames.size() == 1);
    requireBytesEqual(frames[0], hex("CC 01 0A 00 00 36 02 0F 0D 0A"));
}

TEST_CASE("Device::setWorkingMode(Trigger) drives correct bytes") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();
    mock->onWrite([mock](const std::vector<std::uint8_t>& frame) {
        if (frame.size() >= 6 && frame[5] == proto::kCmdSetWorkingMode) {
            mock->queueResponse(hex("CC 81 0A 00 00 41 00 98 0D 0A"));
        }
    });
    Device dev(std::move(mockOwn));
    CHECK_NOTHROW(dev.setWorkingMode(WorkingMode::Trigger));
    auto frames = mock->writtenFrames();
    REQUIRE(frames.size() == 1);
    requireBytesEqual(frames[0], hex("CC 01 0A 00 00 41 01 19 0D 0A"));
}

TEST_CASE("Device::enterSleep / exitSleep / stopCapture send raw commands") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();
    Device dev(std::move(mockOwn));
    dev.enterSleep();
    dev.exitSleep();
    dev.stopCapture();
    auto frames = mock->writtenFrames();
    REQUIRE(frames.size() == 3);
    requireBytesEqual(frames[0], hex("CC 01 09 00 00 40 16 0D 0A"));
    requireBytesEqual(frames[1], hex("CC 01 09 00 00 40 16 0D 0A"));
    requireBytesEqual(frames[2], hex("CC 01 09 00 00 04 DA 0D 0A"));
}

TEST_CASE("Device::resetEfficiencyCurve / verifyAndComputeEfficiencyCurve") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();
    mock->onWrite([mock](const std::vector<std::uint8_t>& frame) {
        if (frame.size() >= 6 && frame[5] == proto::kCmdResetEfficiencyCurve) {
            mock->queueResponse(hex("CC 81 0A 00 00 25 00 7C 0D 0A"));
        } else if (frame.size() >= 6 && frame[5] == proto::kCmdVerifyEfficiencyCurve) {
            mock->queueResponse(hex("CC 81 0A 00 00 27 00 7E 0D 0A"));
        }
    });
    Device dev(std::move(mockOwn));
    CHECK_NOTHROW(dev.resetEfficiencyCurve());
    CHECK_NOTHROW(dev.verifyAndComputeEfficiencyCurve());
}

TEST_CASE("Device::uploadEfficiencyCurve sends start + packets, no per-packet responses") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();
    Device dev(std::move(mockOwn));
    // Upload 500 floats so we get 3 data packets (247, 247, 6).
    std::vector<float> ratios(500, 1.5f);
    CHECK_NOTHROW(dev.uploadEfficiencyCurve(ratios));
    auto frames = mock->writtenFrames();
    // 1 start + ceil(500/247) = 3 data packets = 4 total.
    REQUIRE(frames.size() == 4);
    // First packet: start marker
    requireBytesEqual(frames[0], hex("CC 01 0A 00 00 23 04 FE 0D 0A"));
    // All data packets start with CC 01 .. 23
    for (std::size_t i = 1; i < frames.size(); ++i) {
        CHECK(frames[i][0] == 0xCC);
        CHECK(frames[i][1] == 0x01);
        CHECK(frames[i][5] == proto::kCmdSendEfficiencyCurve);
    }
    // Total payload bytes across data packets = 500 * 4.
    std::size_t totalPayload = 0;
    for (std::size_t i = 1; i < frames.size(); ++i) {
        totalPayload += frames[i].size() - proto::kFrameOverhead;
    }
    CHECK(totalPayload == 500u * 4u);
}

TEST_CASE("Device::captureSingle(false) end-to-end with synthetic 711-sample frame") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();

    // Build a synthetic 711-sample no-TM30 spectrum frame.
    constexpr std::size_t M = 711;
    constexpr std::size_t kPhoto = 47 * 4;
    constexpr std::size_t kPlant = 16 * 4;
    constexpr std::size_t kNir = 12;
    constexpr std::size_t kBlue = 4;
    constexpr std::size_t kHdr = 5;
    constexpr std::size_t kCoef = 2;
    constexpr std::size_t validLen = kHdr + kPhoto + kBlue + kNir + kPlant + kCoef + 2 * M;
    constexpr std::size_t totalLen = validLen + 9;
    static_assert(totalLen == 1706, "PROTOCOL.md says M=711 -> totalLen=1706");

    std::vector<std::uint8_t> resp;
    resp.reserve(totalLen);
    resp.push_back(0xCC);
    resp.push_back(0x81);
    resp.push_back(static_cast<std::uint8_t>(totalLen & 0xFF));
    resp.push_back(static_cast<std::uint8_t>((totalLen >> 8) & 0xFF));
    resp.push_back(static_cast<std::uint8_t>((totalLen >> 16) & 0xFF));
    resp.push_back(proto::kCmdCaptureSingleNoTm30);
    // validData: status=0, exposure=2500
    resp.push_back(0x00);
    resp.push_back(0xC4);
    resp.push_back(0x09);
    resp.push_back(0x00);
    resp.push_back(0x00);
    // photometric+blue+nir+plant: all zeros
    for (std::size_t i = 0; i < kPhoto + kBlue + kNir + kPlant; ++i) resp.push_back(0x00);
    // coefficient = 2
    resp.push_back(0x02);
    resp.push_back(0x00);
    // raw spectrum: incrementing u16
    for (std::size_t i = 0; i < M; ++i) {
        resp.push_back(static_cast<std::uint8_t>(i & 0xFF));
        resp.push_back(static_cast<std::uint8_t>((i >> 8) & 0xFF));
    }
    // checksum + footer
    const std::uint8_t cs = proto::checksum(resp.data(), resp.size());
    resp.push_back(cs);
    resp.push_back(0x0D);
    resp.push_back(0x0A);
    REQUIRE(resp.size() == totalLen);

    mock->onWrite([mock, &resp](const std::vector<std::uint8_t>& frame) {
        if (frame.size() >= 6 && frame[5] == proto::kCmdGetWavelengthRange) {
            mock->queueResponse(hex("CC 81 0D 00 00 0F 54 01 1A 04 DC 0D 0A"));
        } else if (frame.size() >= 6 && frame[5] == proto::kCmdCaptureSingleNoTm30) {
            mock->queueResponse(resp);
        }
    });
    Device dev(std::move(mockOwn));
    auto f = dev.captureSingle(false);
    CHECK(f.exposureStatus == ExposureStatus::Normal);
    CHECK(f.exposureTimeUs == 2500u);
    CHECK(f.spectrumCoefficient == 2);
    REQUIRE(f.rawSpectrum.size() == M);
    CHECK(f.rawSpectrum[0] == 0);
    CHECK(f.rawSpectrum[710] == 710);
    CHECK_FALSE(f.tm30.has_value());
}

TEST_CASE("Device::startStreaming + stopStreaming delivers frames and quiesces") {
    auto mockOwn = std::make_unique<MockSerialPort>();
    auto* mock = mockOwn.get();

    // Build a tiny synthetic frame (M=2, no TM30) so we can queue many cheaply.
    constexpr std::size_t M = 2;
    constexpr std::size_t kPhoto = 47 * 4;
    constexpr std::size_t kPlant = 16 * 4;
    constexpr std::size_t kNir = 12;
    constexpr std::size_t kBlue = 4;
    constexpr std::size_t kHdr = 5;
    constexpr std::size_t kCoef = 2;
    constexpr std::size_t validLen = kHdr + kPhoto + kBlue + kNir + kPlant + kCoef + 2 * M;
    constexpr std::size_t totalLen = validLen + 9;

    auto makeFrame = [&](std::uint16_t marker) {
        std::vector<std::uint8_t> resp;
        resp.reserve(totalLen);
        resp.push_back(0xCC);
        resp.push_back(0x81);
        resp.push_back(static_cast<std::uint8_t>(totalLen & 0xFF));
        resp.push_back(static_cast<std::uint8_t>((totalLen >> 8) & 0xFF));
        resp.push_back(static_cast<std::uint8_t>((totalLen >> 16) & 0xFF));
        resp.push_back(proto::kCmdStartStreamNoTm30);
        resp.push_back(0x00);
        resp.push_back(0x10);
        resp.push_back(0x00);
        resp.push_back(0x00);
        resp.push_back(0x00);
        for (std::size_t i = 0; i < kPhoto + kBlue + kNir + kPlant; ++i) resp.push_back(0x00);
        resp.push_back(0x00); resp.push_back(0x00);  // coef=0
        // raw samples: both equal to marker
        resp.push_back(static_cast<std::uint8_t>(marker & 0xFF));
        resp.push_back(static_cast<std::uint8_t>((marker >> 8) & 0xFF));
        resp.push_back(static_cast<std::uint8_t>(marker & 0xFF));
        resp.push_back(static_cast<std::uint8_t>((marker >> 8) & 0xFF));
        const std::uint8_t cs = proto::checksum(resp.data(), resp.size());
        resp.push_back(cs);
        resp.push_back(0x0D);
        resp.push_back(0x0A);
        return resp;
    };

    // Queue 3 frames in response to the start-stream command.
    mock->onWrite([mock, &makeFrame](const std::vector<std::uint8_t>& frame) {
        if (frame.size() >= 6 && frame[5] == proto::kCmdGetWavelengthRange) {
            // wavelength 100..101 -> M=2 (checksum: sum % 0x100 = 0x32)
            mock->queueResponse(hex("CC 81 0D 00 00 0F 64 00 65 00 32 0D 0A"));
        } else if (frame.size() >= 6 && frame[5] == proto::kCmdStartStreamNoTm30) {
            mock->queueResponse(makeFrame(11));
            mock->queueResponse(makeFrame(22));
            mock->queueResponse(makeFrame(33));
        }
        // Stop command (0x04) elicits no response; the worker will exit.
    });

    Device dev(std::move(mockOwn));

    std::mutex mu;
    std::condition_variable cv;
    std::vector<std::uint16_t> markers;

    dev.startStreaming([&](SpectrumFrame f) {
        std::lock_guard<std::mutex> lk(mu);
        markers.push_back(f.rawSpectrum.front());
        cv.notify_all();
    }, /*includeTm30=*/false);

    // Wait until we've received all 3 queued frames (or time out).
    {
        std::unique_lock<std::mutex> lk(mu);
        const bool ok = cv.wait_for(lk, 2s, [&]() { return markers.size() >= 3; });
        REQUIRE(ok);
    }
    dev.stopStreaming();
    CHECK_FALSE(dev.isStreaming());

    std::lock_guard<std::mutex> lk(mu);
    REQUIRE(markers.size() >= 3);
    CHECK(markers[0] == 11);
    CHECK(markers[1] == 22);
    CHECK(markers[2] == 33);

    // Verify the SDK sent the stop command at the tail.
    bool sawStop = false;
    for (const auto& f : mock->writtenFrames()) {
        if (f.size() >= 6 && f[5] == proto::kCmdStopCapture) { sawStop = true; break; }
    }
    CHECK(sawStop);
}
