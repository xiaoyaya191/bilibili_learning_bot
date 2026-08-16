#pragma once

#include "config.h"
#include "net.h"

#include <string>
#include <nlohmann/json.hpp>
#include <utility>
#include <vector>

namespace bili {

// OpenAI-compatible chat completions client (IPv4 + Aliyun DNS via NetClient).
class AiClient {
 public:
  explicit AiClient(const App& app, NetClient& net);

  // messages: {role, content} pairs. Returns assistant text or "".
  std::string chat(const std::vector<std::pair<std::string, std::string>>& messages,
                   double temperature = 0.7, int max_tokens = 4096);

  // Vision-capable chat: sends text plus one image URL to the vision model.
  std::string chat_vision(const std::vector<std::pair<std::string, std::string>>& messages,
                          const std::string& image_url, double temperature = 0.4,
                          int max_tokens = 2048);

  // Chat with OpenAI-style tool definitions. Returns the full assistant
  // message object (content + tool_calls) or an empty object on failure.
  nlohmann::json chat_tools(const std::vector<std::pair<std::string, std::string>>& messages,
                            const nlohmann::json& tools, double temperature = 0.7,
                            int max_tokens = 4096);

  // Same as chat_tools but accepts a complete OpenAI messages JSON array,
  // including role=function/tool messages with tool_call_id.
  nlohmann::json chat_tools_json(const nlohmann::json& messages,
                                 const nlohmann::json& tools, double temperature = 0.7,
                                 int max_tokens = 4096);

 private:
  std::string resolve_model();

  const App& app_;
  NetClient& net_;
  std::string model_;
  std::chrono::steady_clock::time_point cooldown_until_{};
};

}  // namespace bili
