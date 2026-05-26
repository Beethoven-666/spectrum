// examples/01_device_info.cpp -- connect to the spectrometer and print
// its serial number + wavelength range.
//
// Usage: 01_device_info <serial-port-path>
//   e.g. 01_device_info /dev/tty.usbserial-XXXX
//        01_device_info COM5
#include <cstdlib>
#include <iostream>
#include <string>

#include "h1/Device.hpp"

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: " << argv[0] << " <serial-port-path>\n";
        return 2;
    }
    try {
        h1::Device dev(h1::openSerialPort(argv[1]));
        auto info = dev.getDeviceInfo();
        auto wr = dev.getWavelengthRange();
        std::cout << "Serial number  : " << info.serialNumber << "\n";
        std::cout << "Wavelength rng : " << wr.start << " .. " << wr.end
                  << " nm  (" << wr.count() << " samples)\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
}
