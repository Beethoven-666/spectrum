// tests/HexUtils.hpp -- small helpers for hex literals and byte comparisons.
#pragma once

#include <cctype>
#include <cstdint>
#include <doctest/doctest.h>
#include <iomanip>
#include <sstream>
#include <string>
#include <vector>

namespace h1::testing {

// Parse "CC 01 09 ..." (whitespace insensitive) into a byte vector.
inline std::vector<std::uint8_t> hex(const std::string& s) {
    std::vector<std::uint8_t> out;
    std::uint8_t cur = 0;
    int nibble = 0;
    for (char c : s) {
        if (std::isspace(static_cast<unsigned char>(c))) continue;
        std::uint8_t v;
        if (c >= '0' && c <= '9') v = static_cast<std::uint8_t>(c - '0');
        else if (c >= 'a' && c <= 'f') v = static_cast<std::uint8_t>(c - 'a' + 10);
        else if (c >= 'A' && c <= 'F') v = static_cast<std::uint8_t>(c - 'A' + 10);
        else throw std::invalid_argument(std::string("bad hex char: ") + c);
        cur = static_cast<std::uint8_t>((cur << 4) | v);
        nibble++;
        if (nibble == 2) {
            out.push_back(cur);
            cur = 0;
            nibble = 0;
        }
    }
    if (nibble != 0) throw std::invalid_argument("odd nibble count in hex string");
    return out;
}

inline std::string toHex(const std::vector<std::uint8_t>& v) {
    std::ostringstream oss;
    oss << std::hex << std::uppercase << std::setfill('0');
    for (std::size_t i = 0; i < v.size(); ++i) {
        if (i > 0) oss << ' ';
        oss << std::setw(2) << static_cast<int>(v[i]);
    }
    return oss.str();
}

inline void requireBytesEqual(const std::vector<std::uint8_t>& got,
                              const std::vector<std::uint8_t>& expected) {
    INFO("got:      ", toHex(got));
    INFO("expected: ", toHex(expected));
    REQUIRE(got == expected);
}

}  // namespace h1::testing
