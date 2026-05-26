// tests/MockSerialPort.hpp -- in-memory ISerialPort with scripted responses.
//
// The mock records every byte the SUT writes and lets tests pre-queue
// response frames to be delivered to subsequent read() calls. There are
// two ways to script behaviour:
//
//   1. queueResponse(bytes) -- enqueue a chunk that will be delivered on
//      the next read() call (split across multiple reads transparently).
//
//   2. onWrite(handler)     -- register a callback that fires whenever the
//      SUT writes a complete command frame. The handler can call
//      queueResponse() to reply.
//
// Both interfaces are useful: the first is great for "send X expect Y"
// happy-path tests; the second models device behaviour where the reply
// depends on the command.
#pragma once

#include <chrono>
#include <cstdint>
#include <cstring>
#include <deque>
#include <functional>
#include <mutex>
#include <stdexcept>
#include <vector>

#include "h1/ISerialPort.hpp"

namespace h1::testing {

class MockSerialPort : public ISerialPort {
public:
    using WriteHandler = std::function<void(const std::vector<std::uint8_t>&)>;

    std::size_t write(const std::uint8_t* data, std::size_t len) override {
        std::lock_guard<std::mutex> lk(mu_);
        writtenAll_.insert(writtenAll_.end(), data, data + len);
        // Accumulate into a frame-by-frame view: we split on the spec's
        // 0D 0A footer to keep things simple. This is enough for the mock
        // since the SDK always emits whole frames in a single write().
        pendingFrame_.insert(pendingFrame_.end(), data, data + len);
        for (std::size_t i = 1; i < pendingFrame_.size(); ++i) {
            if (pendingFrame_[i - 1] == 0x0D && pendingFrame_[i] == 0x0A) {
                std::vector<std::uint8_t> frame(pendingFrame_.begin(),
                                                pendingFrame_.begin() + i + 1);
                writtenFrames_.push_back(frame);
                if (writeHandler_) {
                    auto h = writeHandler_;
                    // Release the lock so the handler can call back into
                    // queueResponse() without deadlocking.
                    mu_.unlock();
                    try {
                        h(frame);
                    } catch (...) {
                        mu_.lock();
                        throw;
                    }
                    mu_.lock();
                }
                pendingFrame_.erase(pendingFrame_.begin(),
                                    pendingFrame_.begin() + i + 1);
                i = 0;
            }
        }
        return len;
    }

    std::size_t read(std::uint8_t* buf, std::size_t max_len,
                     std::chrono::milliseconds /*timeout*/) override {
        std::lock_guard<std::mutex> lk(mu_);
        if (readBuf_.empty()) return 0;  // simulate timeout
        const std::size_t n = std::min(max_len, readBuf_.size());
        std::memcpy(buf, readBuf_.data(), n);
        readBuf_.erase(readBuf_.begin(), readBuf_.begin() + n);
        return n;
    }

    void close() override { closed_ = true; }

    // ----- test helpers --------------------------------------------------
    void queueResponse(const std::vector<std::uint8_t>& bytes) {
        std::lock_guard<std::mutex> lk(mu_);
        readBuf_.insert(readBuf_.end(), bytes.begin(), bytes.end());
    }
    void queueResponse(const std::uint8_t* bytes, std::size_t len) {
        std::lock_guard<std::mutex> lk(mu_);
        readBuf_.insert(readBuf_.end(), bytes, bytes + len);
    }
    void onWrite(WriteHandler h) {
        std::lock_guard<std::mutex> lk(mu_);
        writeHandler_ = std::move(h);
    }
    std::vector<std::uint8_t> allWritten() const {
        std::lock_guard<std::mutex> lk(mu_);
        return writtenAll_;
    }
    std::vector<std::vector<std::uint8_t>> writtenFrames() const {
        std::lock_guard<std::mutex> lk(mu_);
        return writtenFrames_;
    }
    bool closed() const { return closed_; }

private:
    mutable std::mutex mu_;
    std::vector<std::uint8_t> readBuf_;
    std::vector<std::uint8_t> writtenAll_;
    std::vector<std::uint8_t> pendingFrame_;
    std::vector<std::vector<std::uint8_t>> writtenFrames_;
    WriteHandler writeHandler_;
    bool closed_ = false;
};

}  // namespace h1::testing
