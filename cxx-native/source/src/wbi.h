#pragma once

#include <string>
#include <utility>
#include <vector>

#include "md5.h"
namespace bili {

class NetClient;

// Adds wts / web_location / w_rid to params using the cached WBI keys.
std::vector<std::pair<std::string, std::string>> sign_params(
    NetClient& net, const std::vector<std::pair<std::string, std::string>>& params);

// Pure helper for tests: computes the WBI digest from an already-urlencoded
// query string and the mixin key.

}  // namespace bili
