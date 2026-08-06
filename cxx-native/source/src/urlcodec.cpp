#include "urlcodec.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <sstream>

namespace bili {

std::string percent_encode(const std::string& value) {
  std::ostringstream out;
  for (unsigned char c : value) {
    if (std::isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') {
      out << c;
    } else if (c == ' ') {
      out << '+';
    } else {
      char buf[4];
      std::snprintf(buf, sizeof(buf), "%%%02X", c);
      out << buf;
    }
  }
  return out.str();
}

std::string build_query_string(
    const std::vector<std::pair<std::string, std::string>>& params) {
	std::vector<std::pair<std::string, std::string>> sorted = params;
	std::sort(sorted.begin(), sorted.end());
	std::ostringstream out;
	bool first = true;
	for (const auto& [k, v] : sorted) {
		if (!first) out << '&';
		first = false;
		out << percent_encode(k) << '=' << percent_encode(v);
	}
	return out.str();
}

std::string percent_decode(const std::string& value) {
	std::string out;
	for (size_t i = 0; i < value.size(); i++) {
		if (value[i] == '+') {
			out += ' ';
		} else if (value[i] == '%' && i + 2 < value.size()) {
			int v = 0;
			if (std::sscanf(value.substr(i + 1, 2).c_str(), "%2x", &v) == 1) {
				out += (char)v;
				i += 2;
			} else {
				out += value[i];
			}
		} else {
			out += value[i];
		}
	}
	return out;
}

}  // namespace bili
