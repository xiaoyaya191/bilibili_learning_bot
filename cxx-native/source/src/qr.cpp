#include "qr.h"

#include <cstdio>
#include <vector>

#include "qrcodegen.hpp"
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

namespace bili {

bool render_qr_png(const std::string& text, const std::string& path, int scale) {
  const qrcodegen::QrCode qr =
      qrcodegen::QrCode::encodeText(text.c_str(), qrcodegen::QrCode::Ecc::HIGH);
  const int border = 4;
  const int size = qr.getSize();
  const int dim = (size + border * 2) * scale;
  std::vector<unsigned char> pixels(static_cast<size_t>(dim) * dim, 255);
  for (int y = 0; y < size; y++) {
    for (int x = 0; x < size; x++) {
      if (!qr.getModule(x, y)) continue;
      for (int dy = 0; dy < scale; dy++) {
        for (int dx = 0; dx < scale; dx++) {
          int py = (y + border) * scale + dy;
          int px = (x + border) * scale + dx;
          pixels[static_cast<size_t>(py) * dim + px] = 0;
        }
      }
    }
  }
  return stbi_write_png(path.c_str(), dim, dim, 1, pixels.data(), dim) != 0;
}

void print_ascii_qr(const std::string& text) {
  const qrcodegen::QrCode qr =
      qrcodegen::QrCode::encodeText(text.c_str(), qrcodegen::QrCode::Ecc::LOW);
  const int border = 2;
  const int size = qr.getSize();
  for (int y = -border; y < size + border; y++) {
    std::string line;
    for (int x = -border; x < size + border; x++) {
      bool dark = x >= 0 && x < size && y >= 0 && y < size && qr.getModule(x, y);
      line += dark ? "##" : "  ";
    }
    std::printf("%s\n", line.c_str());
  }
}

}  // namespace bili
