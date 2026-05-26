// src/Types.cpp -- non-trivial member implementations for public types.
#include "h1/Types.hpp"

#include <cmath>

namespace h1 {

std::vector<double> SpectrumFrame::actualSpectrum() const {
    // pow(10, N) handles negative N too. Pre-compute once.
    const double divisor = std::pow(10.0, static_cast<double>(spectrumCoefficient));
    std::vector<double> out(rawSpectrum.size());
    for (std::size_t i = 0; i < rawSpectrum.size(); ++i) {
        out[i] = static_cast<double>(rawSpectrum[i]) / divisor;
    }
    return out;
}

}  // namespace h1
