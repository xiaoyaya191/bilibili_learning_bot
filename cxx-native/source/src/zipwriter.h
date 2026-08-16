#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace bili {

struct ZipEntry {
  std::string name;
  std::string data;
};

// Minimal ZIP writer (store method, no compression) for OOXML exports.
std::string build_zip(const std::vector<ZipEntry>& entries);

uint32_t crc32(const std::string& data);

}  // namespace bili
