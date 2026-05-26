// tests/test_spectrum_frame.cpp -- builds synthetic spectrum frames and
// checks every field lands at the expected offset, with and without TM30.
#include <doctest/doctest.h>

#include <cmath>
#include <cstdint>
#include <cstring>
#include <vector>

#include "Protocol.hpp"
#include "h1/Errors.hpp"
#include "h1/Types.hpp"

using namespace h1;

namespace {

constexpr std::size_t kPhotometricBytes = 47 * 4;
constexpr std::size_t kBlueHazardBytes = 4;
constexpr std::size_t kNirBytes = 12;
constexpr std::size_t kPlantBytes = 64;
constexpr std::size_t kTm30Bytes = 614 * 4;

void appendU8(std::vector<std::uint8_t>& v, std::uint8_t b) { v.push_back(b); }
void appendU32(std::vector<std::uint8_t>& v, std::uint32_t x) {
    v.push_back(x & 0xFF);
    v.push_back((x >> 8) & 0xFF);
    v.push_back((x >> 16) & 0xFF);
    v.push_back((x >> 24) & 0xFF);
}
void appendI16(std::vector<std::uint8_t>& v, std::int16_t x) {
    auto u = static_cast<std::uint16_t>(x);
    v.push_back(u & 0xFF);
    v.push_back((u >> 8) & 0xFF);
}
void appendU16(std::vector<std::uint8_t>& v, std::uint16_t x) {
    v.push_back(x & 0xFF);
    v.push_back((x >> 8) & 0xFF);
}
void appendFloat(std::vector<std::uint8_t>& v, float f) {
    std::uint8_t b[4];
    std::memcpy(b, &f, 4);
    v.insert(v.end(), b, b + 4);
}

// Build a synthetic validData payload for a no-TM30 frame.
std::vector<std::uint8_t> makeFrame(std::size_t M, bool includeTm30,
                                    std::int16_t coef,
                                    std::uint32_t exposureUs,
                                    std::uint8_t status,
                                    PhotometricParams photo,
                                    BlueHazardParams blue,
                                    NirParams nir,
                                    PlantParams plant,
                                    const std::vector<std::uint16_t>& raw,
                                    const Tm30Params* tm = nullptr) {
    std::vector<std::uint8_t> v;
    appendU8(v, status);
    appendU32(v, exposureUs);
    // photometric (47)
    appendFloat(v, photo.X);
    appendFloat(v, photo.Y);
    appendFloat(v, photo.Z);
    appendFloat(v, photo.x);
    appendFloat(v, photo.y);
    appendFloat(v, photo.uk);
    appendFloat(v, photo.vk);
    appendFloat(v, photo.u_prime);
    appendFloat(v, photo.v_prime);
    appendFloat(v, photo.CCT);
    appendFloat(v, photo.Nit);
    appendFloat(v, photo.r_ratio);
    appendFloat(v, photo.g_ratio);
    appendFloat(v, photo.b_ratio);
    appendFloat(v, photo.DUV);
    appendFloat(v, photo.Ra);
    for (auto r : photo.R) appendFloat(v, r);
    appendFloat(v, photo.Lp);
    appendFloat(v, photo.HW);
    appendFloat(v, photo.Ld);
    appendFloat(v, photo.purity);
    appendFloat(v, photo.SP);
    appendFloat(v, photo.SDCM_k);
    appendFloat(v, photo.k);
    appendFloat(v, photo.lux);
    appendFloat(v, photo.Ee);
    appendFloat(v, photo.fc);
    appendFloat(v, photo.CQS);
    appendFloat(v, photo.GAI_EES);
    appendFloat(v, photo.GAI_BB_8);
    appendFloat(v, photo.GAI_BB_15);
    appendFloat(v, photo.EML);
    appendFloat(v, photo.M_EDI);
    // blue
    appendFloat(v, blue.Eb);
    // nir
    appendFloat(v, nir.redEe);
    appendFloat(v, nir.nirEeA);
    appendFloat(v, nir.nirEeB);
    // plant
    appendFloat(v, plant.PAR);
    appendFloat(v, plant.Eca);
    appendFloat(v, plant.Ecb);
    appendFloat(v, plant.Eb);
    appendFloat(v, plant.Ey);
    appendFloat(v, plant.Er);
    appendFloat(v, plant.Erb_ratio);
    appendFloat(v, plant.PPFD);
    appendFloat(v, plant.PPFDb);
    appendFloat(v, plant.PPFDy);
    appendFloat(v, plant.PPFDr);
    appendFloat(v, plant.PPFDfr);
    appendFloat(v, plant.PPFDr_ratio);
    appendFloat(v, plant.PPFDy_ratio);
    appendFloat(v, plant.PPFDb_ratio);
    appendFloat(v, plant.YPFD);
    if (includeTm30) {
        REQUIRE(tm != nullptr);
        for (auto x : tm->referenceSpectrum) appendFloat(v, x);
        for (auto x : tm->Eab) appendFloat(v, x);
        appendFloat(v, tm->Rf);
        appendFloat(v, tm->Rg);
        for (auto x : tm->chromaShift) appendFloat(v, x);
        for (auto x : tm->hueShift) appendFloat(v, x);
        for (auto x : tm->colorFidelity) appendFloat(v, x);
        for (auto& pair : tm->cesAbTest) { appendFloat(v, pair[0]); appendFloat(v, pair[1]); }
        for (auto& pair : tm->cesAbReference) { appendFloat(v, pair[0]); appendFloat(v, pair[1]); }
    }
    appendI16(v, coef);
    REQUIRE(raw.size() == M);
    for (auto r : raw) appendU16(v, r);
    return v;
}

PhotometricParams makePhotometric() {
    PhotometricParams p;
    p.X = 1.0f; p.Y = 2.0f; p.Z = 3.0f;
    p.x = 0.3f; p.y = 0.32f;
    p.uk = 0.2f; p.vk = 0.3f;
    p.u_prime = 0.21f; p.v_prime = 0.47f;
    p.CCT = 4000.0f;
    p.Nit = 100.0f;
    p.r_ratio = 33.3f; p.g_ratio = 33.3f; p.b_ratio = 33.4f;
    p.DUV = -0.001f;
    p.Ra = 80.0f;
    for (int i = 0; i < 15; ++i) p.R[i] = 70.0f + static_cast<float>(i);
    p.Lp = 555.0f; p.HW = 10.0f; p.Ld = 590.0f; p.purity = 50.0f;
    p.SP = 1.5f; p.SDCM_k = 2.0f; p.k = 4500.0f;
    p.lux = 500.0f; p.Ee = 0.8f; p.fc = 46.45f;
    p.CQS = 85.0f; p.GAI_EES = 90.0f; p.GAI_BB_8 = 88.0f; p.GAI_BB_15 = 89.0f;
    p.EML = 250.0f; p.M_EDI = 240.0f;
    return p;
}

PlantParams makePlant() {
    PlantParams p;
    p.PAR = 1.0f; p.Eca = 2.0f; p.Ecb = 3.0f; p.Eb = 4.0f;
    p.Ey = 5.0f; p.Er = 6.0f; p.Erb_ratio = 7.0f;
    p.PPFD = 8.0f; p.PPFDb = 9.0f; p.PPFDy = 10.0f; p.PPFDr = 11.0f;
    p.PPFDfr = 12.0f; p.PPFDr_ratio = 13.0f; p.PPFDy_ratio = 14.0f;
    p.PPFDb_ratio = 15.0f; p.YPFD = 16.0f;
    return p;
}

}  // namespace

TEST_CASE("decode synthetic no-TM30 frame: every field at correct offset") {
    constexpr std::size_t M = 711;  // wavelength count for 340..1050
    const std::int16_t coef = 2;

    auto photo = makePhotometric();
    BlueHazardParams blue; blue.Eb = 12.5f;
    NirParams nir; nir.redEe = 0.1f; nir.nirEeA = 0.2f; nir.nirEeB = 0.3f;
    auto plant = makePlant();

    std::vector<std::uint16_t> raw(M);
    for (std::size_t i = 0; i < M; ++i) raw[i] = static_cast<std::uint16_t>(i);

    auto bytes = makeFrame(M, /*includeTm30=*/false, coef,
                           /*exposureUs=*/2500, /*status=*/0,
                           photo, blue, nir, plant, raw);
    // expected size: 5 (status+exposure) + 188 + 4 + 12 + 64 + 2 + 2*M
    REQUIRE(bytes.size() == 5u + kPhotometricBytes + kBlueHazardBytes + kNirBytes +
                                kPlantBytes + 2u + 2u * M);

    auto f = proto::decodeSpectrumFrame(bytes.data(), bytes.size(), M, false);
    CHECK(f.exposureStatus == ExposureStatus::Normal);
    CHECK(f.exposureTimeUs == 2500u);
    CHECK(f.photometric.X == doctest::Approx(1.0f));
    CHECK(f.photometric.Y == doctest::Approx(2.0f));
    CHECK(f.photometric.CCT == doctest::Approx(4000.0f));
    CHECK(f.photometric.R[0] == doctest::Approx(70.0f));
    CHECK(f.photometric.R[14] == doctest::Approx(84.0f));
    CHECK(f.photometric.M_EDI == doctest::Approx(240.0f));
    CHECK(f.blueHazard.Eb == doctest::Approx(12.5f));
    CHECK(f.nir.redEe == doctest::Approx(0.1f));
    CHECK(f.nir.nirEeA == doctest::Approx(0.2f));
    CHECK(f.nir.nirEeB == doctest::Approx(0.3f));
    CHECK(f.plant.PAR == doctest::Approx(1.0f));
    CHECK(f.plant.YPFD == doctest::Approx(16.0f));
    CHECK(f.spectrumCoefficient == 2);
    REQUIRE(f.rawSpectrum.size() == M);
    CHECK(f.rawSpectrum[0] == 0);
    CHECK(f.rawSpectrum[710] == 710);
    CHECK_FALSE(f.tm30.has_value());

    auto actual = f.actualSpectrum();
    // coef=2 -> divide by 100
    REQUIRE(actual.size() == M);
    CHECK(actual[0] == doctest::Approx(0.0));
    CHECK(actual[100] == doctest::Approx(1.0));
    CHECK(actual[710] == doctest::Approx(7.1));
}

TEST_CASE("decode synthetic TM30 frame: TM30 at correct offset and last spectrum sample matches") {
    constexpr std::size_t M = 4;
    const std::int16_t coef = 0;

    auto photo = makePhotometric();
    BlueHazardParams blue; blue.Eb = 5.0f;
    NirParams nir; nir.redEe = 1.1f; nir.nirEeA = 2.2f; nir.nirEeB = 3.3f;
    auto plant = makePlant();

    Tm30Params tm;
    for (std::size_t i = 0; i < tm.referenceSpectrum.size(); ++i) {
        tm.referenceSpectrum[i] = static_cast<float>(i);
    }
    for (std::size_t i = 0; i < tm.Eab.size(); ++i) {
        tm.Eab[i] = static_cast<float>(1000 + i);
    }
    tm.Rf = 91.5f;
    tm.Rg = 99.0f;
    for (std::size_t i = 0; i < 16; ++i) {
        tm.chromaShift[i] = static_cast<float>(2000 + i);
        tm.hueShift[i] = static_cast<float>(3000 + i);
        tm.colorFidelity[i] = static_cast<float>(4000 + i);
        tm.cesAbTest[i][0] = static_cast<float>(5000 + i);
        tm.cesAbTest[i][1] = static_cast<float>(5500 + i);
        tm.cesAbReference[i][0] = static_cast<float>(6000 + i);
        tm.cesAbReference[i][1] = static_cast<float>(6500 + i);
    }

    std::vector<std::uint16_t> raw(M);
    raw[0] = 0xABCD; raw[1] = 0x1234; raw[2] = 42; raw[3] = 65535;

    auto bytes = makeFrame(M, /*includeTm30=*/true, coef,
                           /*exposureUs=*/12345, /*status=*/1,
                           photo, blue, nir, plant, raw, &tm);
    REQUIRE(bytes.size() == 5u + kPhotometricBytes + kBlueHazardBytes + kNirBytes +
                                kPlantBytes + kTm30Bytes + 2u + 2u * M);

    auto f = proto::decodeSpectrumFrame(bytes.data(), bytes.size(), M, true);
    CHECK(f.exposureStatus == ExposureStatus::Over);
    CHECK(f.exposureTimeUs == 12345u);
    REQUIRE(f.tm30.has_value());
    const auto& dt = *f.tm30;
    CHECK(dt.referenceSpectrum[0] == doctest::Approx(0.0f));
    CHECK(dt.referenceSpectrum[400] == doctest::Approx(400.0f));
    CHECK(dt.Eab[0] == doctest::Approx(1000.0f));
    CHECK(dt.Eab[98] == doctest::Approx(1098.0f));
    CHECK(dt.Rf == doctest::Approx(91.5f));
    CHECK(dt.Rg == doctest::Approx(99.0f));
    CHECK(dt.chromaShift[0] == doctest::Approx(2000.0f));
    CHECK(dt.chromaShift[15] == doctest::Approx(2015.0f));
    CHECK(dt.hueShift[15] == doctest::Approx(3015.0f));
    CHECK(dt.colorFidelity[15] == doctest::Approx(4015.0f));
    CHECK(dt.cesAbTest[0][0] == doctest::Approx(5000.0f));
    CHECK(dt.cesAbTest[0][1] == doctest::Approx(5500.0f));
    CHECK(dt.cesAbTest[15][1] == doctest::Approx(5515.0f));
    CHECK(dt.cesAbReference[15][1] == doctest::Approx(6515.0f));

    CHECK(f.spectrumCoefficient == 0);
    REQUIRE(f.rawSpectrum.size() == M);
    CHECK(f.rawSpectrum[0] == 0xABCDu);
    CHECK(f.rawSpectrum[3] == 65535u);
    auto actual = f.actualSpectrum();
    // coef=0 -> divisor=1
    CHECK(actual[0] == doctest::Approx(static_cast<double>(0xABCD)));
    CHECK(actual[3] == doctest::Approx(65535.0));
}

TEST_CASE("decodeSpectrumFrame rejects size mismatch -> ProtocolError") {
    std::vector<std::uint8_t> tiny(10, 0);
    CHECK_THROWS_AS(proto::decodeSpectrumFrame(tiny.data(), tiny.size(), 711, false),
                    ProtocolError);
}

TEST_CASE("decodeSpectrumFrame typical lengths match PROTOCOL.md examples") {
    // M=711, no TM30: validData = 275 + 1422 = 1697
    // M=711, with TM30: validData = 2731 + 1422 = 4153
    constexpr std::size_t M = 711;
    constexpr std::size_t kHeader = 5;
    constexpr std::size_t kNoTm30Prefix =
        kHeader + kPhotometricBytes + kBlueHazardBytes + kNirBytes + kPlantBytes;
    constexpr std::size_t kCoef = 2;
    CHECK(kNoTm30Prefix + kCoef + 2 * M == 1697u);
    CHECK(kNoTm30Prefix + kTm30Bytes + kCoef + 2 * M == 4153u);
}
