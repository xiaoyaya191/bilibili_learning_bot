#pragma once

#include <string>

namespace bili {

// Renders a QR code to a PNG file (qrcodegen + stb_image_write).
bool render_qr_png(const std::string& text, const std::string& path, int scale = 4);

// Prints a simple ASCII QR preview to stdout.
void print_ascii_qr(const std::string& text);

}  // namespace bili
