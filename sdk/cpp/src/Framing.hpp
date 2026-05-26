// src/Framing.hpp -- reads one complete response frame from an ISerialPort.
//
// The framing layer is the only place that knows how to compose multiple
// short reads into a single complete frame: it reads the 5-byte preamble,
// extracts totalLen, then reads exactly the remaining bytes.
#pragma once

#include <chrono>
#include <cstdint>
#include <vector>

#include "h1/ISerialPort.hpp"

namespace h1::framing {

// Read one frame from `port`, blocking up to `timeout` total. Returns the
// raw bytes including header/footer/checksum. Throws ProtocolError if the
// preamble bytes are malformed, or TimeoutError if the wait expires
// before a complete frame arrives.
//
// This function performs deadline-based reads: the supplied timeout is the
// total budget for the call, not per-read.
std::vector<std::uint8_t> readFrame(ISerialPort& port,
                                    std::chrono::milliseconds timeout);

// Drain any pending bytes from the port without blocking (useful after a
// stop-streaming to swallow trailing frames). Limits to `maxBytes` to
// avoid runaway loops.
void drain(ISerialPort& port, std::chrono::milliseconds quietPeriod = std::chrono::milliseconds(50),
           std::size_t maxBytes = 64 * 1024);

}  // namespace h1::framing
