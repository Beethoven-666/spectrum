// examples/03_stream.cpp -- continuous capture, stop after N frames.
//
// Usage: 03_stream <serial-port> [N=10]
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>

#include "h1/Device.hpp"

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: " << argv[0] << " <serial-port> [count=10]\n";
        return 2;
    }
    const int target = (argc >= 3) ? std::atoi(argv[2]) : 10;
    try {
        h1::Device dev(h1::openSerialPort(argv[1]));

        std::mutex mu;
        std::condition_variable cv;
        std::atomic<int> received{0};

        dev.startStreaming(
            [&](h1::SpectrumFrame f) {
                int n = ++received;
                std::cout << "frame #" << n << ": exposure=" << f.exposureTimeUs
                          << "us  CCT=" << f.photometric.CCT
                          << "K  lux=" << f.photometric.lux << "\n";
                if (n >= target) {
                    std::lock_guard<std::mutex> lk(mu);
                    cv.notify_all();
                }
            },
            /*includeTm30=*/false,
            [](std::exception_ptr ep) {
                try { std::rethrow_exception(ep); }
                catch (const std::exception& e) {
                    std::cerr << "stream error: " << e.what() << "\n";
                }
            });

        {
            std::unique_lock<std::mutex> lk(mu);
            cv.wait(lk, [&]() { return received.load() >= target; });
        }
        dev.stopStreaming();
        std::cout << "stopped after " << received.load() << " frames\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
}
