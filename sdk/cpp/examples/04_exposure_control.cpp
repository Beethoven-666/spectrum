// examples/04_exposure_control.cpp -- exercise the exposure-mode + time
// commands. Switch to manual, set 50 ms exposure, capture once, then go
// back to auto.
//
// Usage: 04_exposure_control <serial-port>
#include <cstdlib>
#include <iostream>
#include <string>

#include "h1/Device.hpp"

namespace {
const char* modeName(h1::ExposureMode m) {
    return m == h1::ExposureMode::Manual ? "manual" : "auto";
}
}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: " << argv[0] << " <serial-port>\n";
        return 2;
    }
    try {
        h1::Device dev(h1::openSerialPort(argv[1]));

        std::cout << "current mode  : " << modeName(dev.getExposureMode()) << "\n";
        std::cout << "current expo  : " << dev.getExposureTimeUs() << " us\n";

        std::cout << "-> switching to manual\n";
        dev.setExposureMode(h1::ExposureMode::Manual);
        std::cout << "-> setting exposure to 50000 us (50 ms)\n";
        dev.setExposureTimeUs(50000);
        std::cout << "verified mode : " << modeName(dev.getExposureMode()) << "\n";
        std::cout << "verified expo : " << dev.getExposureTimeUs() << " us\n";

        std::cout << "-> capturing one frame\n";
        auto f = dev.captureSingle(false);
        std::cout << "captured exposure was " << f.exposureTimeUs
                  << " us, CCT=" << f.photometric.CCT << " K\n";

        std::cout << "-> back to auto\n";
        dev.setExposureMode(h1::ExposureMode::Auto);
        std::cout << "final mode    : " << modeName(dev.getExposureMode()) << "\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
}
