#include "psycho.h"

#include <algorithm>
#include <chrono>
#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include "platform.h"
#include <sstream>

namespace fs = std::filesystem;
#include <vector>

#include "api.h"

namespace bili {
namespace {

using json = nlohmann::json;

std::string read_file(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return "";
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

bool write_file(const std::string& path, const std::string& content) {
  std::error_code ec;
  fs::create_directories(fs::path(path).parent_path(), ec);
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) return false;
  out << content;
  return out.good();
}

json read_json(const std::string& path) {
  std::string raw = read_file(path);
  if (raw.empty()) return json::object();
  try {
    auto j = json::parse(raw);
    return j.is_object() ? j : json::object();
  } catch (...) {
    return json::object();
  }
}

bool write_json(const std::string& path, const json& v) {
  return write_file(path, v.dump(2));
}

std::string now_iso() {
  std::time_t t = std::time(nullptr);
  std::tm tm{};
  localtime_r(&t, &tm);
  char buf[32];
  std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &tm);
  return buf;
}

json default_profile() {
  return {{"surface_interests", {{"tags", json::object()}, {"categories", json::object()}}},
          {"cocoon_metrics", {{"cocoon_risk", "unknown"}, {"diversity_score", 1.0},
                              {"dominant_categories", json::array()},
                              {"underrepresented_areas", json::array()}}},
          {"counts", json::object()}, {"last_action_at", ""}};
}


std::string utf8_truncate(const std::string& s, size_t max_bytes) {
  if (s.size() <= max_bytes) return s;
  size_t cut = max_bytes;
  while (cut > 0 && ((unsigned char)s[cut] & 0xC0) == 0x80) cut--;
  return s.substr(0, cut);
}

const char* kAversionKeywords[] = {"恐怖", "血腥", "惊悚", "引战", "钓鱼", "诈骗", "刷屏"};

}  // namespace

json psycho_status(const App& app) {
  json profile = read_json(app.paths.data_dir + "/psycho_profile.json");
  if (!profile.is_object()) profile = default_profile();
  json actions = read_json(app.paths.data_dir + "/psycho_actions.json");
  json items = actions.value("items", json::array());
  json aversions = read_json(app.paths.data_dir + "/content_aversions.json");
  return {{"ok", true},
          {"profile", profile},
          {"action_count", items.size()},
          {"aversion_keywords", aversions.value("keywords", json::array())},
          {"last_action_at", profile.value("last_action_at", "")}};
}

json psycho_record_action(App& app, const std::string& action_type,
                          const std::string& bvid, const std::string& title,
                          const std::string& category) {
  std::string actions_path = app.paths.data_dir + "/psycho_actions.json";
  json actions = read_json(actions_path);
  json items = actions.value("items", json::array());
  if (!items.is_array()) items = json::array();
  items.push_back({{"at", now_iso()}, {"type", action_type}, {"bvid", bvid},
                   {"title", utf8_truncate(title, 200)}, {"category", category}});
  if (items.size() > 1000) items.erase(items.begin(), items.end() - 1000);
  actions["items"] = items;
  write_json(actions_path, actions);

  json profile = read_json(app.paths.data_dir + "/psycho_profile.json");
  if (!profile.is_object()) profile = default_profile();
  if (!profile.contains("surface_interests") || !profile["surface_interests"].is_object()) {
    profile["surface_interests"] = json::object();
  }
  if (!profile["surface_interests"].contains("categories") ||
      !profile["surface_interests"]["categories"].is_object()) {
    profile["surface_interests"]["categories"] = json::object();
  }
  if (!profile["surface_interests"].contains("tags") ||
      !profile["surface_interests"]["tags"].is_object()) {
    profile["surface_interests"]["tags"] = json::object();
  }
  if (!profile.contains("counts") || !profile["counts"].is_object()) {
    profile["counts"] = json::object();
  }
  json counts = profile["counts"];
  counts[action_type] = counts.value(action_type, 0);
  counts[action_type] = counts[action_type].get<long long>() + 1;
  profile["counts"] = counts;
  profile["last_action_at"] = now_iso();

  if (!category.empty()) {
    json cats = profile["surface_interests"]["categories"];
    cats[category] = cats.value(category, 0);
    cats[category] = cats[category].get<long long>() + 1;
    profile["surface_interests"]["categories"] = cats;
  }
  if (!title.empty()) {
    json tags = profile["surface_interests"]["tags"];
    std::string key = utf8_truncate(title, 16);
    tags[key] = tags.value(key, 0);
    tags[key] = tags[key].get<long long>() + 1;
    profile["surface_interests"]["tags"] = tags;
  }

  json aversions = read_json(app.paths.data_dir + "/content_aversions.json");
  json kws = aversions.value("keywords", json::array());
  for (const char* kw : kAversionKeywords) {
    if (title.find(kw) != std::string::npos) {
      bool exists = false;
      for (const auto& k : kws) if (k.get<std::string>() == kw) exists = true;
      if (!exists) kws.push_back(kw);
    }
  }
  aversions["keywords"] = kws;
  write_json(app.paths.data_dir + "/content_aversions.json", aversions);

  // Simple cocoon heuristic: if one category dominates recent actions.
  json dominant = json::array();
  std::vector<std::pair<std::string, long long>> cat_counts;
  for (auto& [k, v] : profile["surface_interests"]["categories"].items()) {
    cat_counts.emplace_back(k, v.get<long long>());
  }
  std::sort(cat_counts.begin(), cat_counts.end(),
            [](const auto& a, const auto& b) { return a.second > b.second; });
  for (size_t i = 0; i < cat_counts.size() && i < 3; i++) dominant.push_back(cat_counts[i].first);
  profile["cocoon_metrics"]["dominant_categories"] = dominant;
  profile["cocoon_metrics"]["diversity_score"] =
      cat_counts.empty() ? 1.0 : std::min(1.0, (double)cat_counts.size() / 5.0);
  profile["cocoon_metrics"]["cocoon_risk"] =
      profile["cocoon_metrics"]["diversity_score"].get<double>() < 0.3 ? "high" : "low";
  write_json(app.paths.data_dir + "/psycho_profile.json", profile);
  return {{"ok", true}, {"profile", profile}};
}

json curiosity_status(const App& app) {
  json st = read_json(app.paths.data_dir + "/curiosity_state.json");
  json candidates = read_json(app.paths.data_dir + "/curiosity_candidates.json");
  return {{"enabled", get_bool(app, "curiosity_search", "enabled", false)},
          {"interval_minutes", get_int(app, "curiosity_search", "interval_minutes", 240)},
          {"last_run_at", st.value("last_run_at", "")},
          {"candidate_count", candidates.value("items", json::array()).size()}};
}

json curiosity_run(App& app, NetClient& net, AiClient& ai, bool force) {
  (void)ai;
  if (!force && !get_bool(app, "curiosity_search", "enabled", false)) {
    return {{"ok", false}, {"message", "curiosity disabled"}};
  }
  json profile = read_json(app.paths.data_dir + "/psycho_profile.json");
  json tags = profile.value("surface_interests", json::object()).value("tags", json::object());
  std::vector<std::string> queries;
  for (auto& [k, v] : tags.items()) {
    queries.push_back(k + " 冷门宝藏");
    if (queries.size() >= 3) break;
  }
  queries.insert(queries.end(), {"跨学科 科普", "思维模型", "认知科学 入门", "设计思维"});
  json state = read_json(app.paths.data_dir + "/curiosity_state.json");
  json used = state.value("used_queries", json::array());
  std::string query;
  for (const auto& q : queries) {
    bool seen = false;
    for (const auto& u : used) if (u.get<std::string>() == q) seen = true;
    if (!seen) { query = q; break; }
  }
  if (query.empty()) query = queries[0];

  NetResponse resp = net.get("https://api.bilibili.com/x/web-interface/search/type",
                             {{"search_type", "video"}, {"keyword", query}, {"page", "1"}},
                             {{"Referer", "https://search.bilibili.com/"}});
  json items = json::array();
  try {
    auto j = json::parse(resp.body);
    const auto& result = j.value("data", json::object()).value("result", json::array());
    for (const auto& v : result) {
      if ((int)items.size() >= 8) break;
      std::string bvid = v.value("bvid", "");
      if (bvid.empty()) continue;
      items.push_back({{"bvid", bvid}, {"title", v.value("title", "")},
                       {"author", v.value("author", "")}, {"query", query}});
    }
  } catch (...) {
  }
  json candidates = read_json(app.paths.data_dir + "/curiosity_candidates.json");
  json list = candidates.value("items", json::array());
  for (const auto& it : items) list.push_back(it);
  if (list.size() > 500) list.erase(list.begin(), list.end() - 500);
  candidates["items"] = list;
  write_json(app.paths.data_dir + "/curiosity_candidates.json", candidates);

  used.push_back(query);
  if (used.size() > 100) used.erase(used.begin(), used.end() - 100);
  state["used_queries"] = used;
  state["last_run_at"] = now_iso();
  write_json(app.paths.data_dir + "/curiosity_state.json", state);
  return {{"ok", true}, {"query", query}, {"items", items.size()}, {"state", state}};
}

json evolution_reflect(App& app, NetClient& net, AiClient& ai, bool force) {
  (void)net;
  if (!force && !get_bool(app, "self_evolution", "enabled", false)) {
    return {{"ok", false}, {"message", "evolution disabled"}};
  }
  json actions = read_json(app.paths.data_dir + "/psycho_actions.json");
  json items = actions.value("items", json::array());
  json growth = read_json(app.paths.data_dir + "/web_growth_log.json");
  json logs = growth.value("items", json::array());
  std::string reflection = "基于最近 " + std::to_string(items.size()) +
                           " 条互动记录，AI 角色应保持自然、克制，优先回应用户真正感兴趣的话题。";
  json profile = read_json(app.paths.data_dir + "/psycho_profile.json");
  std::string ai_reflection = ai.chat({
      {"system", "你是角色成长记录员，只输出温和、可控的性格演化建议，不超过 120 字。"},
      {"user", "当前画像: " + profile.dump() + "\n最近动作: " + std::to_string(items.size()) + " 条"}});
  if (!ai_reflection.empty()) reflection = ai_reflection;
  json entry = {{"raw", reflection}, {"created_at", now_iso()}};
  logs.insert(logs.begin(), entry);
  if (logs.size() > 200) logs.erase(logs.begin() + 200, logs.end());
  growth["items"] = logs;
  write_json(app.paths.data_dir + "/web_growth_log.json", growth);

  json st = read_json(app.paths.data_dir + "/self_evolution.json");
  json reflections = st.value("reflections", json::array());
  reflections.push_back({{"at", now_iso()}, {"type", "reflect"}, {"summary", reflection}});
  if (reflections.size() > 200) reflections.erase(reflections.begin(), reflections.end() - 200);
  st["reflections"] = reflections;
  st["last_reflect_at"] = now_iso();
  write_json(app.paths.data_dir + "/self_evolution.json", st);
  return {{"ok", true}, {"reflection", entry}};
}


json psycho_deep_analyze(App& app, NetClient& net, AiClient& ai) {
  (void)net;
  json profile = read_json(app.paths.data_dir + "/psycho_profile.json");
  if (!profile.is_object()) profile = default_profile();
  std::string summary = profile.dump();
  std::string analysis = ai.chat({
      {"system", "你是心理画像分析师。基于互动记录输出 JSON 字段：interests、aversion、cognitive_style、recommendation_strategy。"},
      {"user", "画像数据: " + summary}});
  if (!analysis.empty()) profile["ai_analysis"] = analysis;
  profile["ai_analyzed_at"] = now_iso();
  write_json(app.paths.data_dir + "/psycho_profile.json", profile);
  return {{"ok", !analysis.empty()}, {"profile", profile}};
}

}  // namespace bili
