// src/Device.cpp -- Pimpl-hidden implementation of the high-level Device.
#include "h1/Device.hpp"

#include <atomic>
#include <chrono>
#include <cstring>
#include <mutex>
#include <optional>
#include <thread>
#include <utility>

#include "Framing.hpp"
#include "Protocol.hpp"
#include "h1/Errors.hpp"

namespace h1 {
namespace {

using Clock = std::chrono::steady_clock;
using namespace std::chrono_literals;

// Default timeouts per PROTOCOL.md §7.
constexpr auto kDefaultSetGetTimeout = 1000ms;
constexpr auto kDefaultCaptureTimeout = 5000ms;
constexpr auto kDefaultVerifyCurveTimeout = 10000ms;

// Max cmdData bytes per efficiency-curve packet (PROTOCOL.md §3.16). The
// per-packet ceiling is 999 bytes total which leaves 990 cmdData bytes,
// i.e. 247 floats. We use 247 to match the example in the doc.
constexpr std::size_t kEffCurveMaxFloatsPerPacket = 247;
constexpr std::uint8_t kEffCurveStartMarker = 0x04;

}  // namespace

struct Device::Impl {
    std::unique_ptr<ISerialPort> port;

    // Cached wavelength range so we know how many u16 samples to expect
    // when decoding spectrum frames. Lazily populated.
    std::optional<WavelengthRange> wavelengthRange;

    // Serialises all command/response exchanges so streaming and one-shot
    // commands don't trample each other.
    std::mutex ioMutex;

    // Streaming state. The thread reads frames from the port and pushes
    // them to `onFrame`. `stopFlag` tells it to wind down.
    std::thread streamThread;
    std::atomic<bool> streamRunning{false};
    std::atomic<bool> streamStopFlag{false};
    bool streamWithTm30 = false;

    explicit Impl(std::unique_ptr<ISerialPort> p) : port(std::move(p)) {}

    // Send one frame and read one response, validating it. Returns the
    // raw frame buffer; the caller is responsible for interpreting the
    // validData via proto::parseResponse / parseStatusResponse.
    std::vector<std::uint8_t> exchange(const std::vector<std::uint8_t>& cmd,
                                       std::chrono::milliseconds timeout) {
        // Caller already holds ioMutex (or knows the stream loop is idle).
        if (port->write(cmd.data(), cmd.size()) != cmd.size()) {
            throw H1Error("short write to serial port");
        }
        return framing::readFrame(*port, timeout);
    }

    void sendOnly(const std::vector<std::uint8_t>& cmd) {
        if (port->write(cmd.data(), cmd.size()) != cmd.size()) {
            throw H1Error("short write to serial port");
        }
    }

    // Convenience: send a set-type command and decode the status byte.
    void exchangeStatus(std::uint8_t cmdType,
                        const std::uint8_t* data, std::size_t dataLen,
                        std::chrono::milliseconds timeout) {
        std::lock_guard<std::mutex> lk(ioMutex);
        const auto cmd = proto::buildCommand(cmdType, data, dataLen);
        const auto resp = exchange(cmd, timeout);
        proto::parseStatusResponse(resp.data(), resp.size(), cmdType);
    }

    // Ensure wavelengthRange is populated. Caller must already hold ioMutex.
    const WavelengthRange& ensureWavelengthRangeLocked() {
        if (!wavelengthRange) {
            const auto cmd = proto::buildCommand(proto::kCmdGetWavelengthRange);
            const auto resp = exchange(cmd, kDefaultSetGetTimeout);
            const std::uint8_t* vp = nullptr;
            std::size_t vlen = 0;
            proto::parseResponse(resp.data(), resp.size(), proto::kCmdGetWavelengthRange,
                                 &vp, &vlen);
            if (vlen != 4) {
                throw ProtocolError("wavelength range response should be 4 bytes, got " +
                                    std::to_string(vlen));
            }
            WavelengthRange r;
            r.start = static_cast<std::uint16_t>(vp[0] | (vp[1] << 8));
            r.end = static_cast<std::uint16_t>(vp[2] | (vp[3] << 8));
            wavelengthRange = r;
        }
        return *wavelengthRange;
    }

    void joinStreamThread() {
        if (streamThread.joinable()) streamThread.join();
        streamRunning = false;
        streamStopFlag = false;
    }
};

// ---------------------------------------------------------------------------

Device::Device(std::unique_ptr<ISerialPort> port)
    : pimpl_(std::make_unique<Impl>(std::move(port))) {
    if (!pimpl_->port) {
        throw H1Error("Device constructed with null serial port");
    }
}

Device::~Device() {
    try {
        if (pimpl_ && pimpl_->streamRunning.load()) {
            stopStreaming();
        }
    } catch (...) {
        // Destructors don't throw; swallow.
    }
    if (pimpl_ && pimpl_->port) {
        try {
            pimpl_->port->close();
        } catch (...) {
        }
    }
}

DeviceInfo Device::getDeviceInfo() {
    std::lock_guard<std::mutex> lk(pimpl_->ioMutex);
    const std::uint8_t param = 0x18;  // length expected = 24 (per spec)
    const auto cmd = proto::buildCommand(proto::kCmdGetDeviceInfo, &param, 1);
    const auto resp = pimpl_->exchange(cmd, kDefaultSetGetTimeout);
    const std::uint8_t* vp = nullptr;
    std::size_t vlen = 0;
    proto::parseResponse(resp.data(), resp.size(), proto::kCmdGetDeviceInfo, &vp, &vlen);
    if (vlen != 24) {
        throw ProtocolError("device info response should be 24 bytes, got " +
                            std::to_string(vlen));
    }
    DeviceInfo info;
    info.serialNumber.assign(reinterpret_cast<const char*>(vp), vlen);
    return info;
}

WavelengthRange Device::getWavelengthRange() {
    std::lock_guard<std::mutex> lk(pimpl_->ioMutex);
    // Force a refresh: clear the cache.
    pimpl_->wavelengthRange.reset();
    return pimpl_->ensureWavelengthRangeLocked();
}

void Device::setExposureMode(ExposureMode mode) {
    const std::uint8_t b = static_cast<std::uint8_t>(mode);
    pimpl_->exchangeStatus(proto::kCmdSetExposureMode, &b, 1, kDefaultSetGetTimeout);
}

ExposureMode Device::getExposureMode() {
    std::lock_guard<std::mutex> lk(pimpl_->ioMutex);
    const auto cmd = proto::buildCommand(proto::kCmdGetExposureMode);
    const auto resp = pimpl_->exchange(cmd, kDefaultSetGetTimeout);
    const std::uint8_t* vp = nullptr;
    std::size_t vlen = 0;
    proto::parseResponse(resp.data(), resp.size(), proto::kCmdGetExposureMode, &vp, &vlen);
    if (vlen != 1) throw ProtocolError("getExposureMode: expected 1 byte");
    return static_cast<ExposureMode>(vp[0]);
}

void Device::setExposureTimeUs(std::uint32_t us) {
    std::uint8_t buf[4];
    buf[0] = us & 0xFF;
    buf[1] = (us >> 8) & 0xFF;
    buf[2] = (us >> 16) & 0xFF;
    buf[3] = (us >> 24) & 0xFF;
    pimpl_->exchangeStatus(proto::kCmdSetExposureTime, buf, 4, kDefaultSetGetTimeout);
}

std::uint32_t Device::getExposureTimeUs() {
    std::lock_guard<std::mutex> lk(pimpl_->ioMutex);
    const auto cmd = proto::buildCommand(proto::kCmdGetExposureTime);
    const auto resp = pimpl_->exchange(cmd, kDefaultSetGetTimeout);
    const std::uint8_t* vp = nullptr;
    std::size_t vlen = 0;
    proto::parseResponse(resp.data(), resp.size(), proto::kCmdGetExposureTime, &vp, &vlen);
    if (vlen != 4) throw ProtocolError("getExposureTime: expected 4 bytes");
    return static_cast<std::uint32_t>(vp[0]) |
           (static_cast<std::uint32_t>(vp[1]) << 8) |
           (static_cast<std::uint32_t>(vp[2]) << 16) |
           (static_cast<std::uint32_t>(vp[3]) << 24);
}

void Device::setMaxExposureTimeUs(std::uint32_t us) {
    std::uint8_t buf[4];
    buf[0] = us & 0xFF;
    buf[1] = (us >> 8) & 0xFF;
    buf[2] = (us >> 16) & 0xFF;
    buf[3] = (us >> 24) & 0xFF;
    pimpl_->exchangeStatus(proto::kCmdSetMaxExposureTime, buf, 4, kDefaultSetGetTimeout);
}

std::uint32_t Device::getMaxExposureTimeUs() {
    std::lock_guard<std::mutex> lk(pimpl_->ioMutex);
    const auto cmd = proto::buildCommand(proto::kCmdGetMaxExposureTime);
    const auto resp = pimpl_->exchange(cmd, kDefaultSetGetTimeout);
    const std::uint8_t* vp = nullptr;
    std::size_t vlen = 0;
    proto::parseResponse(resp.data(), resp.size(), proto::kCmdGetMaxExposureTime, &vp, &vlen);
    if (vlen != 4) throw ProtocolError("getMaxExposureTime: expected 4 bytes");
    return static_cast<std::uint32_t>(vp[0]) |
           (static_cast<std::uint32_t>(vp[1]) << 8) |
           (static_cast<std::uint32_t>(vp[2]) << 16) |
           (static_cast<std::uint32_t>(vp[3]) << 24);
}

void Device::setCieMode(CieMode mode) {
    const std::uint8_t b = static_cast<std::uint8_t>(mode);
    pimpl_->exchangeStatus(proto::kCmdSetCieMode, &b, 1, kDefaultSetGetTimeout);
}

CieMode Device::getCieMode() {
    std::lock_guard<std::mutex> lk(pimpl_->ioMutex);
    const auto cmd = proto::buildCommand(proto::kCmdGetCieMode);
    const auto resp = pimpl_->exchange(cmd, kDefaultSetGetTimeout);
    const std::uint8_t* vp = nullptr;
    std::size_t vlen = 0;
    proto::parseResponse(resp.data(), resp.size(), proto::kCmdGetCieMode, &vp, &vlen);
    if (vlen != 1) throw ProtocolError("getCieMode: expected 1 byte");
    return static_cast<CieMode>(vp[0]);
}

void Device::setWorkingMode(WorkingMode mode) {
    const std::uint8_t b = static_cast<std::uint8_t>(mode);
    pimpl_->exchangeStatus(proto::kCmdSetWorkingMode, &b, 1, kDefaultSetGetTimeout);
}

void Device::enterSleep() {
    std::lock_guard<std::mutex> lk(pimpl_->ioMutex);
    pimpl_->sendOnly(proto::buildCommand(proto::kCmdEnterExitSleep));
}

void Device::exitSleep() {
    std::lock_guard<std::mutex> lk(pimpl_->ioMutex);
    pimpl_->sendOnly(proto::buildCommand(proto::kCmdEnterExitSleep));
}

void Device::stopCapture() {
    std::lock_guard<std::mutex> lk(pimpl_->ioMutex);
    pimpl_->sendOnly(proto::buildCommand(proto::kCmdStopCapture));
}

SpectrumFrame Device::captureSingle(bool includeTm30) {
    // Use a generous default: 2x current exposure (if we can get it without
    // racing) capped to at least 5 s. We don't query exposure here to keep
    // the call cheap; users with very long exposures can call the overload.
    return captureSingle(includeTm30, kDefaultCaptureTimeout);
}

SpectrumFrame Device::captureSingle(bool includeTm30, std::chrono::milliseconds timeout) {
    if (pimpl_->streamRunning.load()) {
        throw H1Error("captureSingle called while streaming is active");
    }
    std::lock_guard<std::mutex> lk(pimpl_->ioMutex);
    const std::uint8_t cmdType =
        includeTm30 ? proto::kCmdCaptureSingleWithTm30 : proto::kCmdCaptureSingleNoTm30;
    const auto& wr = pimpl_->ensureWavelengthRangeLocked();
    const auto cmd = proto::buildCommand(cmdType);
    const auto resp = pimpl_->exchange(cmd, timeout);
    const std::uint8_t* vp = nullptr;
    std::size_t vlen = 0;
    proto::parseResponse(resp.data(), resp.size(), cmdType, &vp, &vlen);
    return proto::decodeSpectrumFrame(vp, vlen, wr.count(), includeTm30);
}

void Device::startStreaming(FrameCallback onFrame, bool includeTm30, ErrorCallback onError) {
    if (!onFrame) throw H1Error("startStreaming requires a non-null onFrame callback");
    if (pimpl_->streamRunning.exchange(true)) {
        throw H1Error("startStreaming called while already streaming");
    }
    pimpl_->streamStopFlag = false;
    pimpl_->streamWithTm30 = includeTm30;

    // We must initialise the wavelength cache before kicking off the loop
    // since the loop reads it without taking ioMutex (it owns the port
    // exclusively for the duration of streaming).
    {
        std::lock_guard<std::mutex> lk(pimpl_->ioMutex);
        pimpl_->ensureWavelengthRangeLocked();
        const std::uint8_t cmdType =
            includeTm30 ? proto::kCmdStartStreamWithTm30 : proto::kCmdStartStreamNoTm30;
        const auto cmd = proto::buildCommand(cmdType);
        pimpl_->sendOnly(cmd);
    }

    pimpl_->streamThread = std::thread([this, onFrame = std::move(onFrame),
                                        onError = std::move(onError), includeTm30]() {
        const std::uint8_t cmdType =
            includeTm30 ? proto::kCmdStartStreamWithTm30 : proto::kCmdStartStreamNoTm30;
        const std::size_t count = pimpl_->wavelengthRange->count();
        try {
            while (!pimpl_->streamStopFlag.load()) {
                // Per-frame timeout: the device should emit at the exposure
                // rate. Use the same 5 s default as captureSingle.
                std::vector<std::uint8_t> raw;
                try {
                    raw = framing::readFrame(*pimpl_->port, kDefaultCaptureTimeout);
                } catch (const TimeoutError&) {
                    if (pimpl_->streamStopFlag.load()) break;
                    throw;
                }
                const std::uint8_t* vp = nullptr;
                std::size_t vlen = 0;
                proto::parseResponse(raw.data(), raw.size(), cmdType, &vp, &vlen);
                SpectrumFrame frame = proto::decodeSpectrumFrame(vp, vlen, count, includeTm30);
                onFrame(std::move(frame));
            }
        } catch (...) {
            if (onError) {
                try {
                    onError(std::current_exception());
                } catch (...) {
                    // Don't let a buggy error callback crash the thread.
                }
            }
        }
    });
}

void Device::stopStreaming() {
    if (!pimpl_->streamRunning.load()) return;
    pimpl_->streamStopFlag = true;
    // Send the stop command; the device emits 1-2 more frames before
    // really halting.
    try {
        // We avoid grabbing ioMutex because the stream thread owns the
        // port; writes are still safe on POSIX termios while another
        // thread reads, and PROTOCOL.md §8.4 calls out that mutex is for
        // "in-flight request + optional stream" not for the stop command.
        const auto cmd = proto::buildCommand(proto::kCmdStopCapture);
        pimpl_->port->write(cmd.data(), cmd.size());
    } catch (...) {
        // best effort
    }
    pimpl_->joinStreamThread();
    // Swallow any straggler bytes the device emitted after the stop.
    try {
        framing::drain(*pimpl_->port);
    } catch (...) {
    }
}

bool Device::isStreaming() const {
    return pimpl_->streamRunning.load();
}

void Device::uploadEfficiencyCurve(const std::vector<float>& ratios) {
    if (ratios.empty()) {
        throw H1Error("uploadEfficiencyCurve called with empty ratio array");
    }
    std::lock_guard<std::mutex> lk(pimpl_->ioMutex);
    // 1) Start packet: cmdData = 0x04
    const auto startCmd =
        proto::buildCommand(proto::kCmdSendEfficiencyCurve, &kEffCurveStartMarker, 1);
    pimpl_->sendOnly(startCmd);

    // 2) Data packets. Each packet carries up to 247 floats (= 988 bytes
    //    of cmdData, + 9 byte frame overhead = 997 bytes total, well under
    //    the 999 byte ceiling).
    for (std::size_t i = 0; i < ratios.size(); i += kEffCurveMaxFloatsPerPacket) {
        const std::size_t n =
            std::min(kEffCurveMaxFloatsPerPacket, ratios.size() - i);
        std::vector<std::uint8_t> buf(n * 4);
        std::memcpy(buf.data(), ratios.data() + i, buf.size());
        const auto pkt =
            proto::buildCommand(proto::kCmdSendEfficiencyCurve, buf.data(), buf.size());
        pimpl_->sendOnly(pkt);
    }
    // 3) Caller must invoke verifyAndComputeEfficiencyCurve() to commit.
}

void Device::verifyAndComputeEfficiencyCurve() {
    pimpl_->exchangeStatus(proto::kCmdVerifyEfficiencyCurve, nullptr, 0,
                           kDefaultVerifyCurveTimeout);
}

void Device::resetEfficiencyCurve() {
    pimpl_->exchangeStatus(proto::kCmdResetEfficiencyCurve, nullptr, 0,
                           kDefaultSetGetTimeout);
}

}  // namespace h1
