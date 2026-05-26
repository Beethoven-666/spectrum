// h1/Device.hpp -- high-level facade over the H1 spectrometer protocol.
//
// One Device owns one ISerialPort. All public methods are mutually exclusive
// (a single command at a time); the streaming receive loop runs on a worker
// thread and invokes the user's callback from that thread.
#pragma once

#include <chrono>
#include <cstdint>
#include <exception>
#include <functional>
#include <memory>
#include <vector>

#include "h1/Errors.hpp"
#include "h1/ISerialPort.hpp"
#include "h1/Types.hpp"

namespace h1 {

class Device {
public:
    using FrameCallback = std::function<void(SpectrumFrame)>;
    using ErrorCallback = std::function<void(std::exception_ptr)>;

    // Takes ownership of `port`. Caches the wavelength range on first frame
    // read; callers that want to override the cached value should call
    // getWavelengthRange() before capturing.
    explicit Device(std::unique_ptr<ISerialPort> port);
    ~Device();

    Device(const Device&) = delete;
    Device& operator=(const Device&) = delete;

    // ---- 0x08 / 0x0F -------------------------------------------------
    DeviceInfo getDeviceInfo();
    WavelengthRange getWavelengthRange();

    // ---- 0x0A / 0x0B / 0x0C / 0x0D / 0x13 / 0x14 ---------------------
    void setExposureMode(ExposureMode mode);
    ExposureMode getExposureMode();
    void setExposureTimeUs(std::uint32_t us);
    std::uint32_t getExposureTimeUs();
    void setMaxExposureTimeUs(std::uint32_t us);
    std::uint32_t getMaxExposureTimeUs();

    // ---- 0x36 / 0x37 -------------------------------------------------
    void setCieMode(CieMode mode);
    CieMode getCieMode();

    // ---- 0x41 / 0x40 / 0x04 ------------------------------------------
    void setWorkingMode(WorkingMode mode);
    void enterSleep();  // device has no explicit ack; sends 0x40
    void exitSleep();   // same command toggles the state
    void stopCapture(); // raw 0x04; usually called via stopStreaming()

    // ---- 0x32 / 0x34 -------------------------------------------------
    // Blocks until the device returns the frame. Default timeout is
    // max(2 * exposure, 5000) ms; pass an explicit override if needed.
    SpectrumFrame captureSingle(bool includeTm30 = false);
    SpectrumFrame captureSingle(bool includeTm30, std::chrono::milliseconds timeout);

    // ---- 0x33 / 0x35 + 0x04 ------------------------------------------
    // Starts a background thread that reads frames continuously. `onFrame`
    // is called for each decoded frame. `onError` (optional) is invoked if
    // the receive loop hits a protocol/timeout error.
    void startStreaming(FrameCallback onFrame,
                        bool includeTm30 = false,
                        ErrorCallback onError = nullptr);
    void stopStreaming();
    bool isStreaming() const;

    // ---- 0x23 / 0x25 / 0x27 ------------------------------------------
    // Sends the start packet (cmdData=0x04), splits `ratios` into <=999B
    // packets, and pushes them back-to-back. Caller still must call
    // verifyAndComputeEfficiencyCurve() to actually commit.
    void uploadEfficiencyCurve(const std::vector<float>& ratios);
    void verifyAndComputeEfficiencyCurve();
    void resetEfficiencyCurve();

private:
    struct Impl;
    std::unique_ptr<Impl> pimpl_;
};

}  // namespace h1
