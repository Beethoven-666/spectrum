// examples/02_capture_once.cpp -- single-frame capture; print key
// photometric numbers and a 5-line spectrum preview.
//
// Usage: 02_capture_once <serial-port-path> [--tm30]
#include <cstdlib>
#include <iostream>
#include <string>

#include "h1/Device.hpp"

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: " << argv[0] << " <serial-port> [--tm30]\n";
        return 2;
    }
    const bool tm30 = (argc >= 3 && std::string(argv[2]) == "--tm30");
    try {
        h1::Device dev(h1::openSerialPort(argv[1]));
        auto wr = dev.getWavelengthRange();
        std::cout << "Capturing " << (tm30 ? "with" : "without") << " TM30 ...\n";
        auto frame = dev.captureSingle(tm30);

        const char* statusStr = "?";
        switch (frame.exposureStatus) {
            case h1::ExposureStatus::Normal: statusStr = "normal"; break;
            case h1::ExposureStatus::Over:   statusStr = "OVER";   break;
            case h1::ExposureStatus::Under:  statusStr = "UNDER";  break;
        }
        std::cout << "Exposure : " << frame.exposureTimeUs << " us  ["
                  << statusStr << "]\n";
        std::cout << "CCT      : " << frame.photometric.CCT << " K\n";
        std::cout << "Ra       : " << frame.photometric.Ra << "\n";
        std::cout << "lux      : " << frame.photometric.lux << "\n";
        std::cout << "DUV      : " << frame.photometric.DUV << "\n";
        std::cout << "Lp       : " << frame.photometric.Lp << " nm\n";
        std::cout << "PAR      : " << frame.plant.PAR << "\n";
        std::cout << "PPFD     : " << frame.plant.PPFD << "\n";

        // Show a sparse spectrum preview.
        auto actual = frame.actualSpectrum();
        std::cout << "Spectrum coefficient: " << frame.spectrumCoefficient
                  << " (actual = raw / 10^N)\n";
        const std::size_t step = actual.size() / 5;
        for (std::size_t i = 0; step > 0 && i < actual.size(); i += step) {
            const auto wl = wr.start + static_cast<std::uint16_t>(i);
            std::cout << "  " << wl << " nm: actual=" << actual[i]
                      << "  (raw=" << frame.rawSpectrum[i] << ")\n";
        }
        if (frame.tm30.has_value()) {
            std::cout << "TM30 Rf  : " << frame.tm30->Rf << "\n";
            std::cout << "TM30 Rg  : " << frame.tm30->Rg << "\n";
        }
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
}
