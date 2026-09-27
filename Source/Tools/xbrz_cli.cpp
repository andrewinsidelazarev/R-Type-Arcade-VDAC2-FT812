// Build-time xBRZ bridge for R-Type VDAC2.
//
// This small wrapper is original project code.  It is linked with the
// unmodified xBRZ 1.9 sources downloaded by xbrz_offline.py.  xBRZ itself is
// GPLv3; its complete source archive and License.txt stay beside the binary.

#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

#include "xbrz.h"

namespace {

bool parse_positive(const char* text, int& value) {
    char* end = nullptr;
    const long parsed = std::strtol(text, &end, 10);
    if (!text[0] || (end && *end) || parsed <= 0 ||
        parsed > std::numeric_limits<int>::max()) {
        return false;
    }
    value = static_cast<int>(parsed);
    return true;
}

bool read_exact(const std::string& path, std::vector<std::uint32_t>& pixels) {
    std::ifstream input(path, std::ios::binary | std::ios::ate);
    if (!input) {
        std::cerr << "cannot open input: " << path << '\n';
        return false;
    }
    const std::streamsize actual = input.tellg();
    const std::streamsize expected =
        static_cast<std::streamsize>(pixels.size() * sizeof(std::uint32_t));
    if (actual != expected) {
        std::cerr << "input size " << actual << ", expected " << expected << '\n';
        return false;
    }
    input.seekg(0);
    return static_cast<bool>(input.read(
        reinterpret_cast<char*>(pixels.data()), expected));
}

bool write_exact(const std::string& path,
                 const std::vector<std::uint32_t>& pixels) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        std::cerr << "cannot open output: " << path << '\n';
        return false;
    }
    const std::streamsize size =
        static_cast<std::streamsize>(pixels.size() * sizeof(std::uint32_t));
    output.write(reinterpret_cast<const char*>(pixels.data()), size);
    return static_cast<bool>(output);
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 7) {
        std::cerr << "usage: xbrz_cli INPUT.bgra WIDTH HEIGHT FACTOR "
                     "rgb|argb OUTPUT.bgra\n";
        return 2;
    }

    int width = 0;
    int height = 0;
    int factor = 0;
    if (!parse_positive(argv[2], width) || !parse_positive(argv[3], height) ||
        !parse_positive(argv[4], factor) || factor < 2 ||
        factor > xbrz::SCALE_FACTOR_MAX) {
        std::cerr << "invalid width, height, or xBRZ factor\n";
        return 2;
    }

    const std::size_t source_count =
        static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
    const std::size_t target_count = source_count *
        static_cast<std::size_t>(factor) * static_cast<std::size_t>(factor);
    if (source_count == 0 || target_count / source_count !=
            static_cast<std::size_t>(factor * factor)) {
        std::cerr << "image size overflow\n";
        return 2;
    }

    std::vector<std::uint32_t> source(source_count);
    std::vector<std::uint32_t> target(target_count);
    if (!read_exact(argv[1], source)) {
        return 1;
    }

    // ColorFormat::argb uses BGRA byte order on little-endian machines.  The
    // Python side supplies and consumes that exact byte order.
    const std::string color_format = argv[5];
    const bool opaque = color_format == "rgb";
    if (!opaque && color_format != "argb") {
        std::cerr << "color format must be rgb or argb\n";
        return 2;
    }
    xbrz::scale(static_cast<std::size_t>(factor), source.data(), target.data(),
                width, height,
                opaque ? xbrz::ColorFormat::rgb : xbrz::ColorFormat::argb);
    if (opaque) {
        for (std::uint32_t& pixel : target) {
            pixel |= 0xFF000000U;
        }
    }

    if (!write_exact(argv[6], target)) {
        return 1;
    }
    return 0;
}
