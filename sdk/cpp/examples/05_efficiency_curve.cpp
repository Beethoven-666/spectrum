// examples/05_efficiency_curve.cpp -- upload an all-1.0 efficiency curve
// (a no-op identity correction), then commit it. Useful for verifying the
// upload path end-to-end without changing device behaviour.
//
// Usage: 05_efficiency_curve <serial-port> [count=711]
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

#include "h1/Device.hpp"

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: " << argv[0] << " <serial-port> [count=711]\n";
        return 2;
    }
    const std::size_t n = (argc >= 3) ? static_cast<std::size_t>(std::atoi(argv[2])) : 711;
    try {
        h1::Device dev(h1::openSerialPort(argv[1]));

        std::cout << "uploading identity efficiency curve (" << n << " floats)...\n";
        std::vector<float> ratios(n, 1.0f);
        dev.uploadEfficiencyCurve(ratios);
        std::cout << "verifying + committing...\n";
        dev.verifyAndComputeEfficiencyCurve();
        std::cout << "done. To revert to factory: call resetEfficiencyCurve().\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
}
