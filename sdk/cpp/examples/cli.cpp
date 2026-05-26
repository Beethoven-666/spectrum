// examples/cli.cpp -- `h1` command-line tool exposing the subcommands
// listed in the SDK spec §10. Built with CLI11 for argument parsing.
//
//   h1 info                              <- 0x08 + 0x0F
//   h1 capture [--tm30]                  <- 0x32 or 0x34
//   h1 stream [--count N] [--tm30] [--csv path]
//   h1 set-exposure <us>                 <- 0x0C
//   h1 get-exposure                      <- 0x0D
//   h1 set-mode <auto|manual>            <- 0x0A
//   h1 get-mode                          <- 0x0B
//   h1 reset-curve                       <- 0x25
//
// All commands accept a global --port option (default $H1_PORT).
#include <CLI/CLI.hpp>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <string>

#include "h1/Device.hpp"

namespace {

std::string defaultPort() {
    if (const char* env = std::getenv("H1_PORT")) return env;
    return "";
}

std::unique_ptr<h1::Device> connect(const std::string& portPath) {
    if (portPath.empty()) {
        throw std::runtime_error("no serial port specified (--port or $H1_PORT)");
    }
    return std::make_unique<h1::Device>(h1::openSerialPort(portPath));
}

const char* modeName(h1::ExposureMode m) {
    return m == h1::ExposureMode::Manual ? "manual" : "auto";
}

void cmdInfo(const std::string& port) {
    auto dev = connect(port);
    auto info = dev->getDeviceInfo();
    auto wr = dev->getWavelengthRange();
    std::cout << "serial    : " << info.serialNumber << "\n";
    std::cout << "wavelength: " << wr.start << "-" << wr.end << " nm ("
              << wr.count() << " samples)\n";
    std::cout << "mode      : " << modeName(dev->getExposureMode()) << "\n";
    std::cout << "exposure  : " << dev->getExposureTimeUs() << " us\n";
    std::cout << "max expo  : " << dev->getMaxExposureTimeUs() << " us\n";
}

void cmdCapture(const std::string& port, bool tm30) {
    auto dev = connect(port);
    auto wr = dev->getWavelengthRange();
    auto f = dev->captureSingle(tm30);
    std::cout << "exposure: " << f.exposureTimeUs << " us\n";
    std::cout << "CCT     : " << f.photometric.CCT << "\n";
    std::cout << "Ra      : " << f.photometric.Ra << "\n";
    std::cout << "lux     : " << f.photometric.lux << "\n";
    if (f.tm30.has_value()) {
        std::cout << "Rf      : " << f.tm30->Rf << "\n";
        std::cout << "Rg      : " << f.tm30->Rg << "\n";
    }
    // First few raw samples for spot-check.
    auto actual = f.actualSpectrum();
    const std::size_t step = actual.empty() ? 1 : actual.size() / 8;
    std::cout << "spectrum (coef=" << f.spectrumCoefficient << "):\n";
    for (std::size_t i = 0; step > 0 && i < actual.size(); i += step) {
        std::cout << "  " << (wr.start + i) << " nm: " << actual[i] << "\n";
    }
}

void cmdStream(const std::string& port, int count, bool tm30, const std::string& csv) {
    auto dev = connect(port);
    auto wr = dev->getWavelengthRange();

    std::ofstream csvFile;
    if (!csv.empty()) {
        csvFile.open(csv);
        if (!csvFile) throw std::runtime_error("failed to open csv file: " + csv);
        // header
        csvFile << "frame,exposure_us,CCT,Ra,lux";
        if (tm30) csvFile << ",Rf,Rg";
        for (std::size_t i = 0; i < wr.count(); ++i) {
            csvFile << "," << (wr.start + i) << "nm";
        }
        csvFile << "\n";
    }

    std::mutex mu;
    std::condition_variable cv;
    std::atomic<int> got{0};

    dev->startStreaming(
        [&](h1::SpectrumFrame f) {
            const int n = ++got;
            std::cout << "frame " << n << ": expo=" << f.exposureTimeUs
                      << "us  CCT=" << f.photometric.CCT
                      << "  lux=" << f.photometric.lux << "\n";
            if (csvFile.is_open()) {
                csvFile << n << "," << f.exposureTimeUs << "," << f.photometric.CCT
                        << "," << f.photometric.Ra << "," << f.photometric.lux;
                if (tm30 && f.tm30) csvFile << "," << f.tm30->Rf << "," << f.tm30->Rg;
                auto actual = f.actualSpectrum();
                for (double v : actual) csvFile << "," << v;
                csvFile << "\n";
            }
            if (n >= count) {
                std::lock_guard<std::mutex> lk(mu);
                cv.notify_all();
            }
        },
        tm30,
        [](std::exception_ptr ep) {
            try { std::rethrow_exception(ep); }
            catch (const std::exception& e) { std::cerr << "stream error: " << e.what() << "\n"; }
        });

    {
        std::unique_lock<std::mutex> lk(mu);
        cv.wait(lk, [&]() { return got.load() >= count; });
    }
    dev->stopStreaming();
}

void cmdSetExposure(const std::string& port, std::uint32_t us) {
    auto dev = connect(port);
    dev->setExposureTimeUs(us);
    std::cout << "exposure set to " << us << " us\n";
}

void cmdGetExposure(const std::string& port) {
    auto dev = connect(port);
    std::cout << dev->getExposureTimeUs() << "\n";
}

void cmdSetMode(const std::string& port, const std::string& mode) {
    auto dev = connect(port);
    h1::ExposureMode m;
    if (mode == "auto") m = h1::ExposureMode::Auto;
    else if (mode == "manual") m = h1::ExposureMode::Manual;
    else throw std::runtime_error("mode must be 'auto' or 'manual'");
    dev->setExposureMode(m);
    std::cout << "mode set to " << modeName(m) << "\n";
}

void cmdGetMode(const std::string& port) {
    auto dev = connect(port);
    std::cout << modeName(dev->getExposureMode()) << "\n";
}

void cmdResetCurve(const std::string& port) {
    auto dev = connect(port);
    dev->resetEfficiencyCurve();
    std::cout << "efficiency curve reset to factory\n";
}

}  // namespace

int main(int argc, char** argv) {
    CLI::App app{"h1 -- command-line tool for H1 spectrometer"};
    app.require_subcommand(1);

    std::string port = defaultPort();
    app.add_option("-p,--port", port, "Serial port path (default: $H1_PORT)");

    // info
    auto* info = app.add_subcommand("info", "Show device serial number and config");

    // capture
    bool capTm30 = false;
    auto* capture = app.add_subcommand("capture", "Capture a single frame");
    capture->add_flag("--tm30", capTm30, "Include TM30 data");

    // stream
    int count = 10;
    bool strTm30 = false;
    std::string csv;
    auto* stream = app.add_subcommand("stream", "Continuously capture frames");
    stream->add_option("-n,--count", count, "Number of frames to capture")
        ->default_val(10);
    stream->add_flag("--tm30", strTm30, "Include TM30 data");
    stream->add_option("--csv", csv, "Write each frame to a CSV file");

    // set-exposure
    std::uint32_t expoUs = 0;
    auto* setExpo = app.add_subcommand("set-exposure", "Set exposure (microseconds)");
    setExpo->add_option("us", expoUs, "Exposure in microseconds")->required();

    auto* getExpo = app.add_subcommand("get-exposure", "Print current exposure (us)");

    // set-mode
    std::string modeStr;
    auto* setMode = app.add_subcommand("set-mode", "Set exposure mode (auto|manual)");
    setMode->add_option("mode", modeStr, "auto or manual")->required();

    auto* getMode = app.add_subcommand("get-mode", "Print current exposure mode");

    auto* resetCurve = app.add_subcommand("reset-curve", "Reset efficiency curve to factory");

    CLI11_PARSE(app, argc, argv);

    try {
        if (info->parsed())             { cmdInfo(port); }
        else if (capture->parsed())     { cmdCapture(port, capTm30); }
        else if (stream->parsed())      { cmdStream(port, count, strTm30, csv); }
        else if (setExpo->parsed())     { cmdSetExposure(port, expoUs); }
        else if (getExpo->parsed())     { cmdGetExposure(port); }
        else if (setMode->parsed())     { cmdSetMode(port, modeStr); }
        else if (getMode->parsed())     { cmdGetMode(port); }
        else if (resetCurve->parsed())  { cmdResetCurve(port); }
        return 0;
    } catch (const h1::DeviceError& e) {
        std::cerr << "device error (code=0x" << std::hex << static_cast<int>(e.code())
                  << " cmd=0x" << static_cast<int>(e.cmdType()) << "): " << e.what() << "\n";
        return 3;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
}
