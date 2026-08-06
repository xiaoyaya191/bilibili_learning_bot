#include "ai.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <chrono>
#include <thread>

namespace bili {
namespace {

std::string env_or(const char* name) {
  const char* v = std::getenv(name);
  return v ? std::string(v) : "";
}

bool is_auto_model(const std::string& model) {
  std::string m = model;
  std::transform(m.begin(), m.end(), m.begin(),
                 [](unsigned char c) { return std::tolower(c); });
  return m.empty() || m == "auto" || model == "模型直接获取" || model == "自动获取";
}

}  // namespace

AiClient::AiClient(const App& app, NetClient& net) : app_(app), net_(net) {}

std::string AiClient::resolve_model() {
  if (!model_.empty()) return model_;
  std::string api_key = get_str(app_, "api", "unified_api_key");
  if (api_key.empty()) api_key = env_or("BILI_AI_API_KEY");
  std::string base = get_str(app_, "api", "unified_base_url");
  if (base.empty()) base = env_or("BILI_AI_BASE_URL");
  if (api_key.empty() || base.empty()) return "";

  NetResponse resp =
      net_.raw_get(base + "/models", {{"Authorization", "Bearer " + api_key}});
  try {
    auto j = nlohmann::json::parse(resp.body);
    const auto& data = j.value("data", nlohmann::json::array());
    for (const auto& m : data) {
      std::string id = m.value("id", "");
      if (!id.empty()) {
        model_ = id;
        return id;
      }
    }
  } catch (...) {
  }
  return "";
}

std::string AiClient::chat(const std::vector<std::pair<std::string, std::string>>& messages,
                           double temperature, int max_tokens) {
  if (std::chrono::steady_clock::now() < cooldown_until_) return "";
  std::string api_key = get_str(app_, "api", "unified_api_key");
  if (api_key.empty()) api_key = env_or("BILI_AI_API_KEY");
  std::string base = get_str(app_, "api", "unified_base_url");
  if (base.empty()) base = env_or("BILI_AI_BASE_URL");
  if (api_key.empty() || base.empty()) return "";

  std::string model = get_str(app_, "api", "model_brain");
  if (model.empty()) model = env_or("BILI_AI_MODEL_BRAIN");
  if (is_auto_model(model)) {
    model = resolve_model();
    if (model.empty()) return "";
  }

  nlohmann::json body = {{"model", model}, {"temperature", temperature},
                         {"max_tokens", max_tokens}, {"messages", nlohmann::json::array()}};
  for (const auto& [role, content] : messages) {
    body["messages"].push_back({{"role", role}, {"content", content}});
  }

  std::string url = base + "/chat/completions";
  std::vector<std::pair<std::string, std::string>> headers = {
      {"Authorization", "Bearer " + api_key}, {"Content-Type", "application/json"}};

  std::string last_error;
  for (int attempt = 0; attempt < 3; attempt++) {
    NetResponse resp = net_.raw_post(url, headers, body.dump());
    if (resp.http_code == 429) {
      std::this_thread::sleep_for(std::chrono::seconds(10));
      cooldown_until_ = std::chrono::steady_clock::now() + std::chrono::seconds(60);
      continue;
    }
    try {
      auto j = nlohmann::json::parse(resp.body);
      const auto& choices = j.value("choices", nlohmann::json::array());
      if (choices.empty()) {
        last_error = "empty choices";
      } else {
        std::string text = choices[0].value("message", nlohmann::json()).value("content", "");
        if (!text.empty()) return text;
        last_error = "empty content";
      }
    } catch (...) {
      last_error = resp.body.substr(0, 200);
    }
    std::this_thread::sleep_for(std::chrono::seconds(2 * (attempt + 1)));
  }
  (void)last_error;
  return "";
}

std::string AiClient::chat_vision(
    const std::vector<std::pair<std::string, std::string>>& messages,
    const std::string& image_url, double temperature, int max_tokens) {
  std::string api_key = get_str(app_, "api", "unified_api_key");
  if (api_key.empty()) api_key = env_or("BILI_AI_API_KEY");
  std::string base = get_str(app_, "api", "unified_base_url");
  if (base.empty()) base = env_or("BILI_AI_BASE_URL");
  if (api_key.empty() || base.empty() || image_url.empty()) return "";
  std::string model = get_str(app_, "api", "model_vision");
  if (model.empty()) model = get_str(app_, "api", "model_brain");
  if (model.empty()) return "";
  nlohmann::json body = {{"model", model}, {"temperature", temperature},
                         {"max_tokens", max_tokens}, {"messages", nlohmann::json::array()}};
  for (const auto& [role, text] : messages) {
    body["messages"].push_back({{"role", role}, {"content", nlohmann::json::array({
        {{"type", "text"}, {"text", text}},
        {{"type", "image_url"}, {"image_url", {{"url", image_url}}}}})}});
  }
  std::string url = base + "/chat/completions";
  std::vector<std::pair<std::string, std::string>> headers = {
      {"Authorization", "Bearer " + api_key}, {"Content-Type", "application/json"}};
  NetResponse resp = net_.raw_post(url, headers, body.dump());
  try {
    auto j = nlohmann::json::parse(resp.body);
    const auto& choices = j.value("choices", nlohmann::json::array());
    if (!choices.empty()) {
      return choices[0].value("message", nlohmann::json()).value("content", "");
    }
  } catch (...) {
  }
  return "";
}


nlohmann::json AiClient::chat_tools(
    const std::vector<std::pair<std::string, std::string>>& messages,
    const nlohmann::json& tools, double temperature, int max_tokens) {
  std::string api_key = get_str(app_, "api", "unified_api_key");
  if (api_key.empty()) api_key = env_or("BILI_AI_API_KEY");
  std::string base = get_str(app_, "api", "unified_base_url");
  if (base.empty()) base = env_or("BILI_AI_BASE_URL");
  if (api_key.empty() || base.empty()) return nlohmann::json::object();
  std::string model = get_str(app_, "api", "model_brain");
  if (model.empty()) model = env_or("BILI_AI_MODEL_BRAIN");
  if (is_auto_model(model)) {
    model = resolve_model();
    if (model.empty()) return nlohmann::json::object();
  }
  nlohmann::json body = {{"model", model}, {"temperature", temperature},
                         {"max_tokens", max_tokens}, {"messages", nlohmann::json::array()},
                         {"tools", tools}, {"tool_choice", "auto"}};
  for (const auto& [role, content] : messages) {
    body["messages"].push_back({{"role", role}, {"content", content}});
  }
  std::string url = base + "/chat/completions";
  std::vector<std::pair<std::string, std::string>> headers = {
      {"Authorization", "Bearer " + api_key}, {"Content-Type", "application/json"}};
  for (int attempt = 0; attempt < 3; attempt++) {
    NetResponse resp = net_.raw_post(url, headers, body.dump());
    try {
      auto j = nlohmann::json::parse(resp.body);
      const auto& choices = j.value("choices", nlohmann::json::array());
      if (!choices.empty()) {
        auto msg = choices[0].value("message", nlohmann::json::object());
        if (msg.is_object()) return msg;
      }
    } catch (...) {
    }
    std::this_thread::sleep_for(std::chrono::seconds(2 * (attempt + 1)));
  }
  return nlohmann::json::object();
}


nlohmann::json AiClient::chat_tools_json(
    const nlohmann::json& messages, const nlohmann::json& tools,
    double temperature, int max_tokens) {
  std::string api_key = get_str(app_, "api", "unified_api_key");
  if (api_key.empty()) api_key = env_or("BILI_AI_API_KEY");
  std::string base = get_str(app_, "api", "unified_base_url");
  if (base.empty()) base = env_or("BILI_AI_BASE_URL");
  if (api_key.empty() || base.empty()) return nlohmann::json::object();
  std::string model = get_str(app_, "api", "model_brain");
  if (model.empty()) model = env_or("BILI_AI_MODEL_BRAIN");
  if (is_auto_model(model)) {
    model = resolve_model();
    if (model.empty()) return nlohmann::json::object();
  }
  nlohmann::json body = {{"model", model}, {"temperature", temperature},
                         {"max_tokens", max_tokens}, {"messages", messages},
                         {"tools", tools}, {"tool_choice", "auto"}};
  std::string url = base + "/chat/completions";
  std::vector<std::pair<std::string, std::string>> headers = {
      {"Authorization", "Bearer " + api_key}, {"Content-Type", "application/json"}};
  for (int attempt = 0; attempt < 3; attempt++) {
    NetResponse resp = net_.raw_post(url, headers, body.dump());
    try {
      auto j = nlohmann::json::parse(resp.body);
      const auto& choices = j.value("choices", nlohmann::json::array());
      if (!choices.empty()) {
        auto msg = choices[0].value("message", nlohmann::json::object());
        if (msg.is_object()) return msg;
      }
    } catch (...) {
    }
    std::this_thread::sleep_for(std::chrono::seconds(2 * (attempt + 1)));
  }
  return nlohmann::json::object();
}

}  // namespace bili
