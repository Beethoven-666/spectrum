// src/Framing.cpp -- frame assembly from serial reads.
#include "Framing.hpp"

#include <algorithm>

#include "Protocol.hpp"
#include "h1/Errors.hpp"

namespace h1::framing {
namespace {

using Clock = std::chrono::steady_clock;

// Read exactly `n` bytes into `dst`, honouring the supplied deadline.
// Throws TimeoutError if not enough bytes arrive before the deadline.
void readExact(ISerialPort& port, std::uint8_t* dst, std::size_t n,
               Clock::time_point deadline) {
    std::size_t got = 0;
    while (got < n) {
        const auto now = Clock::now();
        if (now >= deadline) {
            throw TimeoutError("timed out waiting for " + std::to_string(n - got) +
                               " more bytes of frame");
        }
        const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(
            deadline - now);
        const std::size_t r = port.read(dst + got, n - got, remaining);
        if (r == 0) {
            // The port itself returned with no data and no error; treat as
            // timeout to avoid spinning.
            throw TimeoutError("timed out waiting for " + std::to_string(n - got) +
                               " more bytes of frame");
        }
        got += r;
    }
}

// Read bytes one at a time until the 2-byte response header (CC 81) is seen,
// then return with `preamble[0..1]` holding the header. This resync loop lets
// us tolerate leading stray bytes -- e.g. a trailing post-stop stream frame or
// line noise -- instead of tearing down the stream, mirroring the Python and
// Node SDKs (Python's _read_response_header, Node's drain() header scan).
void syncToHeader(ISerialPort& port, std::uint8_t preamble[5],
                  Clock::time_point deadline) {
    // Slide a 2-byte window across the input until it matches the header.
    // Start empty; `matched` counts how many header bytes are in place.
    std::size_t matched = 0;
    while (matched < 2) {
        std::uint8_t b = 0;
        readExact(port, &b, 1, deadline);
        if (matched == 0) {
            if (b == proto::kFrameHeader0) {
                preamble[0] = b;
                matched = 1;
            }
            // else: not a header start -- discard and keep scanning.
        } else {  // matched == 1, expecting kRespHeader1
            if (b == proto::kRespHeader1) {
                preamble[1] = b;
                matched = 2;
            } else if (b == proto::kFrameHeader0) {
                // Second 0xCC -- treat it as a fresh header start.
                preamble[0] = b;
                matched = 1;
            } else {
                matched = 0;
            }
        }
    }
}

}  // namespace

std::vector<std::uint8_t> readFrame(ISerialPort& port,
                                    std::chrono::milliseconds timeout) {
    const auto deadline = Clock::now() + timeout;

    // 1) Sync to the 2-byte header (resyncing past any stray leading bytes),
    //    then read the 3-byte totalLen that follows it.
    std::uint8_t preamble[5] = {0};
    syncToHeader(port, preamble, deadline);
    readExact(port, preamble + 2, 3, deadline);

    const std::size_t totalLen = proto::readTotalLen(preamble, 5);
    if (totalLen < proto::kFrameOverhead) {
        throw ProtocolError("nonsense totalLen=" + std::to_string(totalLen));
    }
    // Sanity cap to avoid runaway allocations on a confused stream. Single
    // TM30 frame at the spec's max (M=711) is ~4162 bytes; an order of
    // magnitude headroom is more than enough.
    if (totalLen > 64 * 1024) {
        throw ProtocolError("totalLen=" + std::to_string(totalLen) +
                            " exceeds sanity cap (64 KiB)");
    }

    std::vector<std::uint8_t> frame(totalLen);
    std::copy(std::begin(preamble), std::end(preamble), frame.begin());
    // 2) Read the rest.
    readExact(port, frame.data() + 5, totalLen - 5, deadline);
    return frame;
}

void drain(ISerialPort& port, std::chrono::milliseconds quietPeriod, std::size_t maxBytes) {
    std::uint8_t scratch[256];
    std::size_t total = 0;
    while (total < maxBytes) {
        std::size_t got = port.read(scratch, sizeof(scratch), quietPeriod);
        if (got == 0) return;
        total += got;
    }
}

}  // namespace h1::framing
