// h1/Types.hpp -- public data structures and enums returned by the SDK.
//
// Field order in the *Params structs matches PROTOCOL.md §5 exactly; the
// decoder relies on this for memcpy-style parsing. Do not reorder fields
// without updating src/Protocol.cpp.
#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace h1 {

enum class ExposureMode : std::uint8_t { Manual = 0, Auto = 1 };
enum class WorkingMode : std::uint8_t { Streaming = 0, Trigger = 1 };
enum class CieMode : std::uint8_t {
    Cie1931_2 = 0,
    Cie1964_10 = 1,
    Cie2015_2 = 2,
    Cie2015_10 = 3,
};
enum class ExposureStatus : std::uint8_t { Normal = 0, Over = 1, Under = 2 };

struct DeviceInfo {
    std::string serialNumber;  // 24 ASCII chars from CMD 0x08
};

struct WavelengthRange {
    std::uint16_t start = 0;  // nm
    std::uint16_t end = 0;    // nm

    // Number of spectrum samples = end - start + 1 (i.e. inclusive range).
    std::size_t count() const noexcept {
        return (end >= start) ? static_cast<std::size_t>(end - start + 1) : 0u;
    }
};

// PROTOCOL.md §5.1 -- 47 floats, order is load-bearing.
struct PhotometricParams {
    float X = 0;
    float Y = 0;
    float Z = 0;
    float x = 0;
    float y = 0;
    float uk = 0;
    float vk = 0;
    float u_prime = 0;
    float v_prime = 0;
    float CCT = 0;
    float Nit = 0;
    float r_ratio = 0;
    float g_ratio = 0;
    float b_ratio = 0;
    float DUV = 0;
    float Ra = 0;
    std::array<float, 15> R{};  // R1..R15 (indices 16..30 in the float stream)
    float Lp = 0;
    float HW = 0;
    float Ld = 0;
    float purity = 0;
    float SP = 0;
    float SDCM_k = 0;
    float k = 0;
    float lux = 0;
    float Ee = 0;
    float fc = 0;
    float CQS = 0;
    float GAI_EES = 0;
    float GAI_BB_8 = 0;
    float GAI_BB_15 = 0;
    float EML = 0;
    float M_EDI = 0;
};

struct BlueHazardParams {
    float Eb = 0;  // W/m^2
};

struct NirParams {
    float redEe = 0;   // 701-780 nm, W/m^2
    float nirEeA = 0;  // 781-800 nm
    float nirEeB = 0;  // >800 nm
};

// PROTOCOL.md §5.4 -- 16 floats, order is load-bearing.
struct PlantParams {
    float PAR = 0;
    float Eca = 0;
    float Ecb = 0;
    float Eb = 0;
    float Ey = 0;
    float Er = 0;
    float Erb_ratio = 0;
    float PPFD = 0;
    float PPFDb = 0;
    float PPFDy = 0;
    float PPFDr = 0;
    float PPFDfr = 0;
    float PPFDr_ratio = 0;
    float PPFDy_ratio = 0;
    float PPFDb_ratio = 0;
    float YPFD = 0;
};

// PROTOCOL.md §5.5 -- 614 floats total, organised as labelled arrays.
struct Tm30Params {
    std::array<float, 401> referenceSpectrum{};
    std::array<float, 99> Eab{};
    float Rf = 0;
    float Rg = 0;
    std::array<float, 16> chromaShift{};
    std::array<float, 16> hueShift{};
    std::array<float, 16> colorFidelity{};
    std::array<std::array<float, 2>, 16> cesAbTest{};       // (a', b') per CES bin
    std::array<std::array<float, 2>, 16> cesAbReference{};  // reference illuminant
};

struct SpectrumFrame {
    ExposureStatus exposureStatus = ExposureStatus::Normal;
    std::uint32_t exposureTimeUs = 0;
    PhotometricParams photometric;
    BlueHazardParams blueHazard;
    NirParams nir;
    PlantParams plant;
    std::optional<Tm30Params> tm30;  // present only for cmdType 0x34/0x35
    std::int16_t spectrumCoefficient = 0;
    std::vector<std::uint16_t> rawSpectrum;  // size = wavelengthCount

    // actualSpectrum[i] = rawSpectrum[i] / 10^spectrumCoefficient
    // Returned as a fresh vector for ergonomics; tight loops may prefer to
    // compute on demand.
    std::vector<double> actualSpectrum() const;
};

}  // namespace h1
