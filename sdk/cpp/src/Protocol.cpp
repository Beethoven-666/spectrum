// src/Protocol.cpp -- byte-level codec implementation. See PROTOCOL.md for
// the authoritative description of every field. This file is intentionally
// boring: just packing/unpacking with bounds checks.
#include "Protocol.hpp"

#include <cstring>
#include <sstream>
#include <stdexcept>
#include <string>

#include "h1/Errors.hpp"

namespace h1::proto {
namespace {

// Tiny helpers for little-endian read/write. We avoid memcpy of a struct
// directly because the spec is little-endian but we make no assumption
// about host byte order.

void writeU24LE(std::uint8_t* dst, std::uint32_t v) {
    dst[0] = static_cast<std::uint8_t>(v & 0xFF);
    dst[1] = static_cast<std::uint8_t>((v >> 8) & 0xFF);
    dst[2] = static_cast<std::uint8_t>((v >> 16) & 0xFF);
}

std::uint16_t readU16LE(const std::uint8_t* p) {
    return static_cast<std::uint16_t>(p[0]) |
           static_cast<std::uint16_t>(static_cast<std::uint16_t>(p[1]) << 8);
}

std::uint32_t readU24LE(const std::uint8_t* p) {
    return static_cast<std::uint32_t>(p[0]) |
           (static_cast<std::uint32_t>(p[1]) << 8) |
           (static_cast<std::uint32_t>(p[2]) << 16);
}

std::uint32_t readU32LE(const std::uint8_t* p) {
    return static_cast<std::uint32_t>(p[0]) |
           (static_cast<std::uint32_t>(p[1]) << 8) |
           (static_cast<std::uint32_t>(p[2]) << 16) |
           (static_cast<std::uint32_t>(p[3]) << 24);
}

std::int16_t readI16LE(const std::uint8_t* p) {
    return static_cast<std::int16_t>(readU16LE(p));
}

float readF32LE(const std::uint8_t* p) {
    // IEEE 754 binary32 little-endian. The spec only describes the wire
    // format; on every platform we target the host is also IEEE 754 little
    // endian, so a memcpy is correct.
    float out = 0;
    std::memcpy(&out, p, sizeof(out));
    return out;
}

void decodePhotometric(const std::uint8_t* p, PhotometricParams& out) {
    auto take = [&](std::size_t i) { return readF32LE(p + i * 4); };
    out.X = take(0);
    out.Y = take(1);
    out.Z = take(2);
    out.x = take(3);
    out.y = take(4);
    out.uk = take(5);
    out.vk = take(6);
    out.u_prime = take(7);
    out.v_prime = take(8);
    out.CCT = take(9);
    out.Nit = take(10);
    out.r_ratio = take(11);
    out.g_ratio = take(12);
    out.b_ratio = take(13);
    out.DUV = take(14);
    out.Ra = take(15);
    for (std::size_t i = 0; i < 15; ++i) out.R[i] = take(16 + i);
    out.Lp = take(31);
    out.HW = take(32);
    out.Ld = take(33);
    out.purity = take(34);
    out.SP = take(35);
    out.SDCM_k = take(36);
    out.k = take(37);
    out.lux = take(38);
    out.Ee = take(39);
    out.fc = take(40);
    out.CQS = take(41);
    out.GAI_EES = take(42);
    out.GAI_BB_8 = take(43);
    out.GAI_BB_15 = take(44);
    out.EML = take(45);
    out.M_EDI = take(46);
}

void decodePlant(const std::uint8_t* p, PlantParams& out) {
    auto take = [&](std::size_t i) { return readF32LE(p + i * 4); };
    out.PAR = take(0);
    out.Eca = take(1);
    out.Ecb = take(2);
    out.Eb = take(3);
    out.Ey = take(4);
    out.Er = take(5);
    out.Erb_ratio = take(6);
    out.PPFD = take(7);
    out.PPFDb = take(8);
    out.PPFDy = take(9);
    out.PPFDr = take(10);
    out.PPFDfr = take(11);
    out.PPFDr_ratio = take(12);
    out.PPFDy_ratio = take(13);
    out.PPFDb_ratio = take(14);
    out.YPFD = take(15);
}

void decodeTm30(const std::uint8_t* p, Tm30Params& out) {
    // 614 floats laid out per PROTOCOL.md §5.5.
    auto take = [&](std::size_t i) { return readF32LE(p + i * 4); };
    std::size_t idx = 0;
    for (auto& v : out.referenceSpectrum) v = take(idx++);  // 0..400
    for (auto& v : out.Eab) v = take(idx++);                // 401..499
    out.Rf = take(idx++);                                   // 500
    out.Rg = take(idx++);                                   // 501
    for (auto& v : out.chromaShift) v = take(idx++);        // 502..517
    for (auto& v : out.hueShift) v = take(idx++);           // 518..533
    for (auto& v : out.colorFidelity) v = take(idx++);      // 534..549
    for (auto& pair : out.cesAbTest) {                      // 550..581
        pair[0] = take(idx++);
        pair[1] = take(idx++);
    }
    for (auto& pair : out.cesAbReference) {                 // 582..613
        pair[0] = take(idx++);
        pair[1] = take(idx++);
    }
    // idx should equal 614 here.
}

std::string hexByte(std::uint8_t b) {
    static const char* digits = "0123456789ABCDEF";
    std::string out(2, '0');
    out[0] = digits[(b >> 4) & 0xF];
    out[1] = digits[b & 0xF];
    return out;
}

}  // namespace

std::uint8_t checksum(const std::uint8_t* bytes, std::size_t len) {
    std::uint32_t sum = 0;
    for (std::size_t i = 0; i < len; ++i) sum += bytes[i];
    return static_cast<std::uint8_t>(sum & 0xFF);
}

std::vector<std::uint8_t> buildCommand(std::uint8_t cmdType,
                                       const std::uint8_t* cmdData,
                                       std::size_t cmdDataLen) {
    // Total frame = 2 (hdr) + 3 (len) + 1 (cmdType) + N + 1 (checksum) + 2 (footer)
    const std::size_t total = kFrameOverhead + cmdDataLen;
    std::vector<std::uint8_t> out(total);
    out[0] = kFrameHeader0;
    out[1] = kCmdHeader1;
    writeU24LE(out.data() + 2, static_cast<std::uint32_t>(total));
    out[5] = cmdType;
    if (cmdDataLen > 0 && cmdData != nullptr) {
        std::memcpy(out.data() + 6, cmdData, cmdDataLen);
    }
    // checksum covers bytes [0 .. checksumPos)
    const std::size_t checksumPos = 6 + cmdDataLen;
    out[checksumPos] = checksum(out.data(), checksumPos);
    out[checksumPos + 1] = kFooter0;
    out[checksumPos + 2] = kFooter1;
    return out;
}

std::size_t readTotalLen(const std::uint8_t* frame, std::size_t frameLen) {
    if (frameLen < 5) return 0;
    return readU24LE(frame + 2);
}

void parseResponse(const std::uint8_t* frame, std::size_t frameLen,
                   std::uint8_t expectedCmdType,
                   const std::uint8_t** validDataOut, std::size_t* validDataLenOut) {
    if (frameLen < kFrameOverhead) {
        throw ProtocolError("response frame too short: " + std::to_string(frameLen) +
                            " bytes (need >= " + std::to_string(kFrameOverhead) + ")");
    }
    if (frame[0] != kFrameHeader0 || frame[1] != kRespHeader1) {
        std::ostringstream oss;
        oss << "bad response header: expected CC 81, got "
            << hexByte(frame[0]) << " " << hexByte(frame[1]);
        throw ProtocolError(oss.str());
    }
    const std::uint32_t totalLen = readU24LE(frame + 2);
    if (totalLen != frameLen) {
        throw ProtocolError("totalLen=" + std::to_string(totalLen) +
                            " does not match received " + std::to_string(frameLen) +
                            " bytes");
    }
    const std::uint8_t dataType = frame[5];
    if (expectedCmdType != 0 && dataType != expectedCmdType) {
        std::ostringstream oss;
        oss << "dataType mismatch: expected " << hexByte(expectedCmdType)
            << ", got " << hexByte(dataType);
        throw ProtocolError(oss.str());
    }
    // Footer
    if (frame[frameLen - 2] != kFooter0 || frame[frameLen - 1] != kFooter1) {
        throw ProtocolError("bad frame footer (expected 0D 0A)");
    }
    // Checksum is the byte immediately before the footer.
    const std::size_t checksumPos = frameLen - 3;
    const std::uint8_t expected = checksum(frame, checksumPos);
    if (expected != frame[checksumPos]) {
        std::ostringstream oss;
        oss << "checksum mismatch: computed " << hexByte(expected)
            << ", got " << hexByte(frame[checksumPos]);
        throw ProtocolError(oss.str());
    }
    *validDataOut = frame + 6;
    *validDataLenOut = checksumPos - 6;  // bytes between cmdType and checksum
}

void parseStatusResponse(const std::uint8_t* frame, std::size_t frameLen,
                         std::uint8_t expectedCmdType) {
    const std::uint8_t* valid = nullptr;
    std::size_t validLen = 0;
    parseResponse(frame, frameLen, expectedCmdType, &valid, &validLen);
    if (validLen != 1) {
        throw ProtocolError("expected 1-byte status response, got " +
                            std::to_string(validLen) + " bytes");
    }
    const std::uint8_t status = valid[0];
    if (status == kStatusOk) return;
    if (status == kStatusInvalid) {
        throw DeviceError(status, expectedCmdType,
                          "device returned 0x15 (invalid command) for cmd 0x" +
                              hexByte(expectedCmdType));
    }
    if (status == kStatusUnsupported) {
        throw DeviceError(status, expectedCmdType,
                          "device returned 0xFF (unsupported or out of range) for cmd 0x" +
                              hexByte(expectedCmdType));
    }
    // Any non-zero status that isn't explicitly defined: still treat as
    // a device error so callers don't silently swallow it.
    throw DeviceError(status, expectedCmdType,
                      "device returned unknown status 0x" + hexByte(status) +
                          " for cmd 0x" + hexByte(expectedCmdType));
}

SpectrumFrame decodeSpectrumFrame(const std::uint8_t* validData,
                                  std::size_t validDataLen,
                                  std::size_t wavelengthCount,
                                  bool includeTm30) {
    // Required layout sizes (see PROTOCOL.md §4.1 / §4.2).
    constexpr std::size_t kPhotometricBytes = 47 * 4;  // 188
    constexpr std::size_t kBlueHazardBytes = 1 * 4;    // 4
    constexpr std::size_t kNirBytes = 3 * 4;           // 12
    constexpr std::size_t kPlantBytes = 16 * 4;        // 64
    constexpr std::size_t kTm30Bytes = 614 * 4;        // 2456
    constexpr std::size_t kHeaderBytes = 1 + 4;        // status + exposure us
    constexpr std::size_t kCoefBytes = 2;

    const std::size_t prefixBytes = kHeaderBytes + kPhotometricBytes +
                                    kBlueHazardBytes + kNirBytes + kPlantBytes +
                                    (includeTm30 ? kTm30Bytes : 0);
    const std::size_t rawBytes = 2 * wavelengthCount;
    const std::size_t expected = prefixBytes + kCoefBytes + rawBytes;
    if (validDataLen != expected) {
        throw ProtocolError(
            "spectrum validData length mismatch: expected " + std::to_string(expected) +
            " bytes (wavelengthCount=" + std::to_string(wavelengthCount) +
            ", includeTm30=" + (includeTm30 ? "true" : "false") + "), got " +
            std::to_string(validDataLen));
    }

    SpectrumFrame frame;
    std::size_t off = 0;
    const std::uint8_t status = validData[off];
    off += 1;
    if (status > 2) {
        // Defensive: the spec defines 0/1/2 only. Tolerate but log via
        // exception-free path by clamping to Normal? No -- protocol violation.
        throw ProtocolError("unknown exposureStatus value 0x" + hexByte(status));
    }
    frame.exposureStatus = static_cast<ExposureStatus>(status);
    frame.exposureTimeUs = readU32LE(validData + off);
    off += 4;

    decodePhotometric(validData + off, frame.photometric);
    off += kPhotometricBytes;
    frame.blueHazard.Eb = readF32LE(validData + off);
    off += kBlueHazardBytes;
    frame.nir.redEe = readF32LE(validData + off);
    frame.nir.nirEeA = readF32LE(validData + off + 4);
    frame.nir.nirEeB = readF32LE(validData + off + 8);
    off += kNirBytes;
    decodePlant(validData + off, frame.plant);
    off += kPlantBytes;
    if (includeTm30) {
        Tm30Params tm;
        decodeTm30(validData + off, tm);
        frame.tm30 = std::move(tm);
        off += kTm30Bytes;
    }
    frame.spectrumCoefficient = readI16LE(validData + off);
    off += kCoefBytes;
    frame.rawSpectrum.resize(wavelengthCount);
    for (std::size_t i = 0; i < wavelengthCount; ++i) {
        frame.rawSpectrum[i] = readU16LE(validData + off + 2 * i);
    }
    return frame;
}

}  // namespace h1::proto
