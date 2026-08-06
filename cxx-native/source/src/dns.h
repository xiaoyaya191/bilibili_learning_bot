#pragma once

#include <string>
#include <vector>

namespace bili {

// Minimal DNS A-record lookup over UDP, pinned to Aliyun public DNS
// (223.5.5.5 / 223.6.6.6). Returns IPv4 addresses only.
std::vector<std::string> resolve_aliyun_v4(const std::string& host, int timeout_ms = 3000);

}  // namespace bili
