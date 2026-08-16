#include "zipwriter.h"

#include <cstring>

namespace bili {

static uint32_t crc_table[256];
static bool crc_init = false;

uint32_t crc32(const std::string& data) {
  if (!crc_init) {
    for (uint32_t i = 0; i < 256; i++) {
      uint32_t c = i;
      for (int k = 0; k < 8; k++) {
        c = (c & 1) ? (0xEDB88320 ^ (c >> 1)) : (c >> 1);
      }
      crc_table[i] = c;
    }
    crc_init = true;
  }
  uint32_t c = 0xFFFFFFFF;
  for (unsigned char b : data) {
    c = crc_table[(c ^ b) & 0xFF] ^ (c >> 8);
  }
  return c ^ 0xFFFFFFFF;
}

static void put16(std::string& out, uint16_t v) {
  out.push_back((char)(v & 0xFF));
  out.push_back((char)((v >> 8) & 0xFF));
}

static void put32(std::string& out, uint32_t v) {
  out.push_back((char)(v & 0xFF));
  out.push_back((char)((v >> 8) & 0xFF));
  out.push_back((char)((v >> 16) & 0xFF));
  out.push_back((char)((v >> 24) & 0xFF));
}

std::string build_zip(const std::vector<ZipEntry>& entries) {
  std::string out;
  std::string central;
  uint32_t offset = 0;
  uint16_t count = (uint16_t)entries.size();

  for (const auto& e : entries) {
    uint32_t crc = crc32(e.data);
    uint32_t size = (uint32_t)e.data.size();

    // Local file header
    put32(out, 0x04034B50);
    put16(out, 20);        // version needed
    put16(out, 0);         // flags
    put16(out, 0);         // method: store
    put16(out, 0);         // mod time
    put16(out, 0x21);      // mod date
    put32(out, crc);
    put32(out, size);      // compressed size
    put32(out, size);      // uncompressed size
    put16(out, (uint16_t)e.name.size());
    put16(out, 0);         // extra len
    out += e.name;
    out += e.data;

    // Central directory header
    put32(central, 0x02014B50);
    put16(central, 20);    // version made by
    put16(central, 20);    // version needed
    put16(central, 0);
    put16(central, 0);
    put16(central, 0);
    put16(central, 0x21);
    put32(central, crc);
    put32(central, size);
    put32(central, size);
    put16(central, (uint16_t)e.name.size());
    put16(central, 0);
    put16(central, 0);
    put16(central, 0);
    put16(central, 0);
    put32(central, 0);     // external attrs
    put32(central, offset);
    central += e.name;

    offset += 30 + (uint32_t)e.name.size() + size;
  }

  uint32_t central_offset = (uint32_t)out.size();
  out += central;

  // End of central directory
  put32(out, 0x06054B50);
  put16(out, 0);
  put16(out, 0);
  put16(out, count);
  put16(out, count);
  put32(out, (uint32_t)central.size());
  put32(out, central_offset);
  put16(out, 0);
  return out;
}

}  // namespace bili
