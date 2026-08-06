#include "monitor.h"

#include <algorithm>
#include "platform.h"
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <map>
#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include <random>
#include <regex>
#include <set>
#include <sstream>
#include <thread>

#include "cookies.h"
#include "logbuf.h"
#include "urlcodec.h"

namespace bili {
namespace {

std::string now_ts() {
  std::time_t t = std::time(nullptr);
  std::tm tm{};
  localtime_r(&t, &tm);
  char buf[32];
  std::strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tm);
  return buf;
}

std::string trim(const std::string& s) {
  size_t a = s.find_first_not_of(" \t\r\n");
  if (a == std::string::npos) return "";
  size_t b = s.find_last_not_of(" \t\r\n");
  return s.substr(a, b - a + 1);
}

std::string lower(const std::string& s) {
  std::string out = s;
  std::transform(out.begin(), out.end(), out.begin(),
                 [](unsigned char c) { return std::tolower(c); });
  return out;
}

std::string truncate(const std::string& s, size_t n) {
  if (s.size() <= n) return s;
  return s.substr(0, n) + "...";
}

std::string safe_preview(const std::string& s, size_t max) {
  std::string out;
  for (unsigned char c : s.substr(0, max)) {
    if (c == '\n') {
      out += "\\n";
    } else if (c == '\r') {
      out += "\\r";
    } else if (c == '\t') {
      out += "\\t";
    } else if (c >= 32 && c < 127) {
      out += static_cast<char>(c);
    } else {
      char buf[8];
      std::snprintf(buf, sizeof(buf), "\\x%02x", c);
      out += buf;
    }
  }
  return out;
}

double rand01() {
  static std::random_device rd;
  static std::mt19937 gen(rd());
  return std::generate_canonical<double, 10>(gen);
}

std::string json_str(const nlohmann::json& v) { return v.dump(); }

std::string read_file_text(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return "";
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

nlohmann::json read_json_file(const std::string& path) {
  std::string raw = read_file_text(path);
  if (raw.empty()) return nlohmann::json::object();
  try {
    return nlohmann::json::parse(raw);
  } catch (...) {
    return nlohmann::json::object();
  }
}

bool write_json_file(const std::string& path, const nlohmann::json& v) {
  std::error_code ec;
  std::filesystem::create_directories(std::filesystem::path(path).parent_path(), ec);
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) return false;
  out << v.dump(2);
  return out.good();
}

}  // namespace

Monitor::Monitor(App& app)
    : app_(app),
      net_(app),
      ai_(app, net_),
      cmt_(app.paths.comment_log_file),
      at_(app.paths.monitor_at_state) {
  cmt_.load();
  at_.load();
  ensure_buvid4(app_, net_);
  std::error_code ec;
  at_baseline_ = std::filesystem::exists(app.paths.monitor_at_state, ec);
}

void Monitor::log(const char* level, const std::string& msg) const {
	std::printf("%s [%s] %s\n", now_ts().c_str(), level, msg.c_str());
	std::fflush(stdout);
	std::string line = std::string(now_ts()) + " [" + level + "] " + msg;
	LogBuffer::instance().append(line);
	std::ofstream out(app_.paths.log_dir + "/web_monitor_runtime.log", std::ios::binary | std::ios::app);
	if (out) out << line << "\n";
}

std::string Monitor::csrf() const { return cookie_value(app_, "bili_jct"); }

bool Monitor::auto_reply_enabled() const {
  if (app_.monitor.contains("auto_reply")) {
    return app_.monitor["auto_reply"].get<bool>();
  }
  return true;
}

int Monitor::max_replies() const {
  if (app_.monitor.contains("max_replies_per_check")) {
    return (int)app_.monitor["max_replies_per_check"].get<long long>();
  }
  return 5;
}

std::string Monitor::ensure_marker(std::string text) const {
  text = trim(text);
  if (text.empty()) return "";
  if (!get_bool(app_, "behavior", "ai_marker_enabled", true)) return text;
  std::string marker = get_str(app_, "behavior", "ai_marker", "（内容由AI生成并由AI回复）");
  if (text.find(marker) != std::string::npos ||
      text.find("（内容由AI生成并由AI回复）") != std::string::npos) {
    return text;
  }
  return text + marker;
}

std::string Monitor::build_comment_prompt(const Comment& c) const {
  std::string marker = get_str(app_, "behavior", "ai_marker", "（内容由AI生成并由AI回复）");
  std::string out = "用户评论: " + c.content + "\n";
  out += "请判断是否值得回复，再根据这条评论生成一个自然回复。\n";
  out += "要求：\n";
  out += "1. 对方只是表情、路过、结束语、无实质内容时返回 END\n";
  out += "2. 回复要自然、亲切，可以适当幽默，但不要客服腔\n";
  out += "3. 字数控制在 50 字以内\n";
  out += "4. 不要每次都反问\n";
  out += "5. 必须用 B 站原生表情（[表情名] 格式，不是 emoji），通常只加 1 个\n";
  if (get_bool(app_, "behavior", "ai_marker_enabled", true)) out += "6. 结尾带上 " + marker + "\n";
  out += "7. 对方询问视频简介、字幕、评论区的相关内容时，没有可靠证据就如实说明，不能假装已经看完视频\n";
  out += "8. 只返回回复内容，不要有其他文字\n";
  return out;
}

std::string Monitor::build_at_prompt(const nlohmann::json& n,
                                     const std::string& evidence) const {
  std::string user = n.value("user", "未知");
  std::string content = n.value("content", "");
  return "Reply to this Bilibili @ mention naturally and briefly. Use only the supplied evidence.\n"
         "A playback heartbeat was reported when evidence exists; base the reply only on supplied evidence.\n"
         "If evidence is missing, say that it cannot be confirmed. Reply in the language used by the commenter.\n\n"
         "Commenter: " +
         user + "\nComment: " + content + "\nEvidence: " + evidence;
}

Comment Monitor::parse_reply_notification(const nlohmann::json& item) const {
  Comment c;
  const auto& it = item.value("item", nlohmann::json::object());
  std::string business = lower(it.value("business", ""));
  if (business != "reply" && business != "comment" && business != "评论") return c;
  c.aid = num(it.value("subject_id", nlohmann::json()));
  c.id = num(it.value("source_id", nlohmann::json()));
  if (c.aid == 0 || c.id == 0) return c;
  std::string content = trim(it.value("source_content", ""));
  if (content.empty()) content = trim(it.value("target_reply_content", ""));
  if (content.empty()) content = trim(it.value("desc", ""));
  if (content.empty()) content = trim(it.value("content", ""));
  if (content.empty()) return c;
  c.root = num(it.value("root_id", nlohmann::json()));
  if (c.root == 0) c.root = c.id;
  c.parent = c.id;
  c.force = true;
  c.source = "reply_notification";
  c.content = content;
  const auto& user = item.value("user", nlohmann::json::object());
  c.user = user.value("nickname", user.value("uname", "未知用户"));
  c.user_id = num(user.value("mid", nlohmann::json()));
  return c;
}

nlohmann::json Monitor::parse_at_notification(const nlohmann::json& item) const {
  nlohmann::json out = nlohmann::json::object();
  const auto& it = item.value("item", nlohmann::json::object());
  std::string content =
      trim(it.value("desc", it.value("content", it.value("title", it.value("uri", "")))));
  std::string uri = it.value("uri", "");
  out["content"] = content;
  out["uri"] = uri;

  std::string bvid;
  std::smatch m;
  std::string combined = content + " " + uri;
  if (std::regex_search(combined, m, std::regex("BV[0-9A-Za-z]+"))) bvid = m[0];
  out["bvid"] = bvid;

  long long aid = num(it.value("subject_id", nlohmann::json()));
  if (aid == 0) aid = num(it.value("oid", nlohmann::json()));
  if (aid == 0) {
    if (std::regex_search(uri, m, std::regex("(?:av|aid=)(\\d+)", std::regex::icase))) {
      aid = std::stoll(m[1]);
    }
  }
  out["aid"] = aid;

  long long comment_id = num(it.value("rpid", nlohmann::json()));
  if (comment_id == 0) comment_id = num(it.value("reply_id", nlohmann::json()));
  if (comment_id == 0) {
    long long sid = num(it.value("source_id", nlohmann::json()));
    if (sid > 100) comment_id = sid;
  }
  if (comment_id == 0) comment_id = num(it.value("target_id", nlohmann::json()));
  if (comment_id == 0) {
    long long bid = num(it.value("business_id", nlohmann::json()));
    if (bid > 100) comment_id = bid;
  }
  if (comment_id == 0) comment_id = num(it.value("source_id", nlohmann::json()));
  out["comment_id"] = comment_id;
  out["root_id"] = num(it.value("root_id", nlohmann::json()));

  const auto& user = item.value("user", nlohmann::json::object());
  out["user"] = user.value("nickname", user.value("uname", "未知"));
  long long user_id = num(user.value("mid", nlohmann::json()));
  if (user_id == 0) user_id = num(user.value("uid", nlohmann::json()));
  out["user_id"] = user_id;
  out["source_id"] = num(it.value("source_id", nlohmann::json()));
  out["business_id"] = num(it.value("business_id", nlohmann::json()));

  std::string nid;
  if (item.contains("id")) nid = std::to_string(num(item.value("id", nlohmann::json())));
  if (nid.empty() || nid == "0") nid = std::to_string(comment_id);
  out["id"] = nid;
  return out;
}

bool Monitor::handle_comment(const Comment& c) {
  if (trim(c.content).empty()) return false;
  if (c.force) {
    // reply path
    std::string prompt = build_comment_prompt(c);
    std::string reply = ai_.chat({{"system", "你是一个友好的B站用户，正在回复别人的评论。"},
                                  {"user", prompt}});
    reply = trim(reply);
    if (reply.empty()) {
      log("WARN", "AI returned empty reply, skip @" + c.user);
      return true;
    }
    if (reply == "END" || reply == "end" || reply == "End") {
      log("INFO", "AI judged no reply needed @" + c.user);
      return true;
    }
    reply = ensure_marker(reply);
    const auto& pi_cfg = app_.config.value("prompt_injection", nlohmann::json::object());
    if (pi_cfg.value("enabled", true)) {
      for (const auto& term : pi_cfg.value("custom_terms", nlohmann::json::array())) {
        if (term.is_string() && reply.find(term.get<std::string>()) != std::string::npos) {
          log("WARN", "prompt injection term blocked in reply");
          return true;
        }
      }
    }
    if (!auto_reply_enabled()) {
      log("COMMENT", "AI draft (not sent) @" + c.user + ": " + truncate(reply, 80));
      return true;
    }
    std::string err = send_comment(net_, csrf(), reply, c.aid, c.root, c.parent);
    if (!err.empty()) {
      log("ERROR", "send comment rpid=" + std::to_string(c.id) + ": " + err);
      return false;
    }
    cmt_.mark_replied(std::to_string(c.id));
    cmt_.mark_user_replied(std::to_string(c.user_id));
    cmt_.log_interaction(std::to_string(c.id), "reply", reply, c.user);
    log("SUCCESS", "replied @" + c.user + " rpid=" + std::to_string(c.id) +
                      " aid=" + std::to_string(c.aid) + ": " + truncate(reply, 60));
    one_click_three(c.aid, c.bvid, c.user);
    return true;
  }

  double prob = get_double(app_, "interaction", "prob_comment_others", 0.3);
  double roll = rand01();
  std::string action;
  if (roll < prob) {
    action = "reply";
  } else if (roll < prob + 0.3) {
    action = "like";
  } else {
    action = "none";
  }

  if (action == "reply") {
    int cooldown = (int)get_int(app_, "behavior", "comment_user_cooldown_minutes", 60);
    std::string reason;
    if (!cmt_.should_reply_user(std::to_string(c.user_id), c.content, cooldown, reason)) {
      log("INFO", "pacing skip @" + c.user + ": " + reason);
      return true;
    }
    Comment copy = c;
    copy.force = true;
    return handle_comment(copy);
  }
  if (action == "like") {
    std::string err = like_comment(net_, csrf(), c.aid, c.id);
    if (!err.empty()) {
      log("ERROR", "like comment rpid=" + std::to_string(c.id) + ": " + err);
      return false;
    }
    cmt_.mark_liked(std::to_string(c.id));
    cmt_.log_interaction(std::to_string(c.id), "like", "点赞", c.user);
    log("SUCCESS", "liked comment @" + c.user + " rpid=" + std::to_string(c.id));
    return true;
  }
  log("INFO", "skip comment @" + c.user + " rpid=" + std::to_string(c.id) + " (none)");
  return true;
}

void Monitor::one_click_three(long long aid, const std::string& bvid,
                              const std::string& user) {
  const auto& cfg = get_json(app_, "interaction", "comment_reply_three_actions");
  if (!cfg.is_object() || !cfg.value("enabled", false)) return;
  std::string b = bvid;
  if (b.empty() && aid != 0) {
    std::string err;
    VideoInfo info = video_info(net_, "", aid, err);
    b = info.bvid;
  }
  if (b.empty()) return;
  if (cmt_.three_action_done(b)) return;

  nlohmann::json results = nlohmann::json::object();
  if (cfg.value("like", true)) {
    if (!has_liked_video(net_, aid, b)) {
      std::string err = like_video(net_, csrf(), aid, b);
      results["like"] = err.empty() ? "ok" : "error";
    } else {
      results["like"] = "already_liked";
    }
  }
  if (cfg.value("coin", true)) {
    int max_coins = (int)get_int(app_, "interaction", "max_coins_daily", 2);
    if (cmt_.coin_used_today() >= max_coins) {
      results["coin"] = "daily_limit";
    } else {
      std::string err = pay_coin(net_, csrf(), aid, b);
      if (err.empty()) {
        results["coin"] = "ok";
      } else if (err.find("34002") != std::string::npos ||
                 err.find("up主") != std::string::npos ||
                 err.find("自己投币") != std::string::npos) {
        results["coin"] = "up_owner_skip";
      } else if (err.find("重复投币") != std::string::npos ||
                 err.find("不能重复") != std::string::npos) {
        results["coin"] = "already_coined";
      } else {
        results["coin"] = "error:" + truncate(err, 160);
      }
    }
  }
  if (cfg.value("favorite", true)) {
    std::string err;
    long long folder = first_favorite_folder(net_, aid, app_.uid, err);
    if (folder == 0) {
      results["favorite"] = err.empty() ? "no_folder" : "error";
    } else {
      std::string ferr = add_favorite(net_, csrf(), aid, folder);
      results["favorite"] = ferr.empty() ? "ok" : "error";
    }
  }
  if (results.value("like", "") == "ok" || results.value("coin", "") == "ok" ||
      results.value("favorite", "") == "ok") {
    cmt_.mark_three_action(b, results);
  }
  log("COMMENT", "three actions " + b + ": " + json_str(results) + " @" + user);
}

int Monitor::scan_video_comments() {
  std::string err;
  auto videos = user_videos(net_, app_.uid, err);
  if (!err.empty()) {
    log("WARN", "get user videos failed: " + err);
    return 0;
  }
  std::vector<Comment> candidates;
  for (const auto& [aid, bvid] : videos) {
    if (comment_risk_pause_sec_ > 0) break;
    auto cmts = video_comments(net_, aid, err);
    if (!err.empty()) {
      log("WARN", "get comments failed aid=" + std::to_string(aid) + ": " + err);
      if (err.find("412") != std::string::npos) {
        comment_risk_pause_sec_ = 60;
        log("WARN", "bilibili risk control 412, pause comment scan 60s");
        break;
      }
      err.clear();
      continue;
    }
    for (const auto& c : cmts) {
      if (c.member_mid == app_.uid) continue;
      std::string id = std::to_string(c.rpid);
      if (cmt_.is_processed(id)) continue;
      Comment cc;
      cc.id = c.rpid;
      cc.aid = aid;
      cc.bvid = bvid;
      cc.content = trim(c.message);
      cc.user = c.member_uname;
      cc.user_id = c.member_mid;
      cc.root = c.rpid;
      cc.parent = c.rpid;
      cc.source = "comment_scan";
      candidates.push_back(cc);
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(500 + (int)(rand01() * 1000)));
  }

  std::set<long long> seen;
  std::vector<Comment> unique;
  for (const auto& c : candidates) {
    if (seen.insert(c.id).second) unique.push_back(c);
  }
  if (unique.empty()) return 0;
  log("SUCCESS", "found " + std::to_string(unique.size()) + " new comments");

  int limit = max_replies();
  int count = 0;
  for (size_t i = 0; i < unique.size(); i++) {
    if (count >= limit) break;
    bool handled = handle_comment(unique[i]);
    if (handled) count++;
    cmt_.mark_processed(std::to_string(unique[i].id));
    if (i + 1 < unique.size()) {
      std::this_thread::sleep_for(std::chrono::milliseconds(1000 + (int)(rand01() * 2000)));
    }
  }
  return count;
}

int Monitor::check_reply_feed() {
  std::string err;
  auto items = reply_feed(net_, err);
  if (!err.empty()) {
    log("WARN", "get reply feed failed: " + err);
    return 0;
  }
  std::vector<Comment> candidates;
  for (const auto& item : items) {
    Comment c = parse_reply_notification(item);
    if (c.id != 0) candidates.push_back(c);
  }
  if (!cmt_.reply_feed_baseline()) {
    std::vector<std::string> ids;
    for (const auto& c : candidates) ids.push_back(std::to_string(c.id));
    cmt_.set_reply_feed_baseline(ids);
    log("COMMENT", "reply feed baseline initialized (" + std::to_string(ids.size()) +
                       " historical replies)");
    return 0;
  }
  int limit = max_replies();
  int count = 0;
  for (const auto& c : candidates) {
    if (count >= limit) break;
    std::string id = std::to_string(c.id);
    if (cmt_.is_processed(id)) continue;
    bool handled = handle_comment(c);
    if (handled) count++;
    cmt_.mark_processed(id);
  }
  return count;
}

std::string Monitor::generate_at_reply(const nlohmann::json& n) {
  nlohmann::json evidence = {{"status", "no associated video"}};
  std::string bvid = n.value("bvid", "");
  long long aid = n.value("aid", nlohmann::json());
  std::string err;
  VideoInfo info;
  if (bvid.empty() && aid != 0) {
    info = video_info(net_, "", aid, err);
    if (!info.bvid.empty()) bvid = info.bvid;
  }
  if (!bvid.empty()) {
    std::string herr = report_history(net_, app_, bvid, 30);
    if (herr.empty()) {
      log("MENTION", "@ playback heartbeat reported " + bvid);
    }
    if (info.bvid.empty()) info = video_info(net_, bvid, 0, err);
    if (!info.bvid.empty()) {
      evidence = {{"status", "video_info"},
                  {"bvid", info.bvid},
                  {"title", info.title},
                  {"desc", truncate(info.desc, 1200)}};
      std::string summary = video_ai_summary(net_, info);
      if (!summary.empty()) evidence["ai_summary"] = truncate(summary, 4000);
    }
  }
  std::string prompt = build_at_prompt(n, json_str(evidence));
  std::string reply =
      ai_.chat({{"system", "You are a concise, factual Bilibili AI comment assistant."},
                {"user", prompt}});
  return trim(reply);
}

int Monitor::check_mentions() {
  if (app_.monitor.contains("at_mentions_enabled") &&
      !app_.monitor["at_mentions_enabled"].get<bool>()) {
    return 0;
  }
  std::string err;
  auto items = at_feed(net_, err);
  if (!err.empty()) {
    log("WARN", "get at feed failed: " + err);
    return 0;
  }
  std::vector<nlohmann::json> notifications;
  for (const auto& item : items) {
    nlohmann::json n = parse_at_notification(item);
    if (!n.value("id", "").empty()) notifications.push_back(n);
  }
  if (!at_baseline_) {
    for (const auto& n : notifications) at_.mark_processed(n.value("id", ""));
    at_baseline_ = true;
    log("MENTION", "@ baseline initialized (" + std::to_string(notifications.size()) +
                       " historical notifications)");
    return 0;
  }

  int limit = max_replies();
  int count = 0;
  for (const auto& n : notifications) {
    if (count >= limit) break;
    std::string nid = n.value("id", "");
    if (at_.processed(nid)) continue;
    long long comment_id = n.value("comment_id", nlohmann::json());
    if (comment_id != 0 && cmt_.is_processed(std::to_string(comment_id))) {
      log("INFO", "@ already handled by comment channel notification=" + nid +
                      " rpid=" + std::to_string(comment_id));
      at_.mark_processed(nid);
      count++;
      continue;
    }
    std::string reply = generate_at_reply(n);
    bool sent = false;
    bool terminal = false;
    long long aid = n.value("aid", nlohmann::json());
    if (!reply.empty() && auto_reply_enabled() && aid != 0 && comment_id != 0) {
      std::string final = ensure_marker(reply);
      const auto& pi_cfg = app_.config.value("prompt_injection", nlohmann::json::object());
      if (pi_cfg.value("enabled", true)) {
        for (const auto& term : pi_cfg.value("custom_terms", nlohmann::json::array())) {
          if (term.is_string() && final.find(term.get<std::string>()) != std::string::npos) {
            log("WARN", "prompt injection term blocked in @ reply");
            terminal = true;
            sent = false;
            break;
          }
        }
      }
      std::string err2 = send_comment(net_, csrf(), final, aid, comment_id, comment_id);
      if (err2.empty()) {
        sent = true;
        cmt_.mark_replied(std::to_string(comment_id));
        cmt_.log_interaction(std::to_string(comment_id), "reply", final, n.value("user", ""));
        log("SUCCESS", "@ replied aid=" + std::to_string(aid) +
                           " rpid=" + std::to_string(comment_id) + " to " +
                           n.value("user", ""));
        one_click_three(aid, n.value("bvid", ""), n.value("user", ""));
      } else {
        terminal = err2.find("12006") != std::string::npos;
        log("WARN", "send @ reply failed notification=" + nid + ": " + err2);
      }
    }
    if (!sent && !terminal) {
      int attempts = at_.record_attempt(nid);
      if (attempts >= 3) {
        at_.mark_processed(nid);
        count++;
        log("WARN", "@ delivery abandoned after 3 attempts: " + n.value("user", ""));
      }
      continue;
    }
    at_.mark_processed(nid);
    if (comment_id != 0 && (sent || terminal)) {
      cmt_.mark_processed(std::to_string(comment_id));
    }
    count++;
  }
  return count;
}

int Monitor::browse_recommendations() {
  if (!get_bool(app_, "interaction", "browse_enabled", true)) return 0;
  long long interval = get_int(app_, "interaction", "browse_interval_seconds", 300);
  long long now = std::chrono::duration_cast<std::chrono::seconds>(
                      std::chrono::system_clock::now().time_since_epoch())
                      .count();
  if (last_browse_ != 0 && now - last_browse_ < interval) return 0;
  last_browse_ = now;

  NetResponse resp = net_.get(
      "https://api.bilibili.com/x/web-interface/wbi/index/top/feed/rcmd",
      {}, {}, true);
  nlohmann::json j;
  try {
    j = nlohmann::json::parse(resp.body);
  } catch (...) {
    log("WARN", "recommend feed parse failed: http=" + std::to_string(resp.http_code) +
              " size=" + std::to_string(resp.body.size()) +
              " encoding=" + resp.content_encoding + " err=" + resp.curl_error +
              " head=" + safe_preview(resp.body, 240));
    return 0;
  }
  if (j.value("code", -1) != 0) {
    log("WARN", "recommend feed failed: " + j.value("message", "unknown"));
    return 0;
  }
  const auto& items = j.value("data", nlohmann::json::object()).value("item", nlohmann::json::array());
  if (!items.is_array() || items.empty()) return 0;

  std::string history_path = app_.paths.data_dir + "/history_videos.json";
  nlohmann::json history = read_json_file(history_path);
  if (!history.is_object()) history = nlohmann::json::object();
  if (!history.contains("videos") || !history["videos"].is_array()) history["videos"] = nlohmann::json::array();
  std::set<std::string> seen;
  for (const auto& v : history["videos"]) {
    if (v.is_object()) seen.insert(v.value("bvid", ""));
  }

  nlohmann::json meta_path = app_.paths.data_dir + "/watch_history_metadata.json";
  nlohmann::json meta = read_json_file(meta_path);
  if (!meta.is_object()) meta = nlohmann::json::object();

  int added = 0;
  for (const auto& item : items) {
    if (!item.is_object()) continue;
    std::string bvid = item.value("bvid", "");
    if (bvid.empty() || seen.count(bvid)) continue;
    const auto& owner = item.value("owner", nlohmann::json::object());
    const auto& stat = item.value("stat", nlohmann::json::object());
    nlohmann::json entry = {
        {"bvid", bvid}, {"title", item.value("title", bvid)},
        {"up", owner.value("name", "")}, {"pic", item.value("pic", "")},
        {"duration", item.value("duration", 0)}, {"category", item.value("tname", "")},
        {"source", "recommendation"}, {"result", "watched"}, {"score", 0.0},
        {"time", now_ts()}, {"action", "view"}};
    history["videos"].push_back(entry);
    meta[bvid] = {{"pic", item.value("pic", "")}, {"duration", item.value("duration", 0)},
                  {"category", item.value("tname", "")}, {"title", item.value("title", "")},
                  {"up", owner.value("name", "")},
                  {"view_count", stat.value("view", 0)}, {"like_count", stat.value("like", 0)},
                  {"coin_count", stat.value("coin", 0)}, {"favorite_count", stat.value("favorite", 0)}};
    seen.insert(bvid);
    added++;
    std::string herr = report_history(net_, app_, bvid, 30);
    if (!herr.empty()) log("WARN", "browse heartbeat failed " + bvid + ": " + herr);
    nlohmann::json runtime = read_json_file(app_.paths.data_dir + "/bot_runtime_state.json");
    runtime["video_observation"] = {{"bvid", bvid}, {"title", item.value("title", "")},
                                    {"up", owner.value("name", "")}, {"pic", item.value("pic", "")},
                                    {"duration", item.value("duration", 0)},
                                    {"category", item.value("tname", "")}, {"updated_at", now_ts()}};
    write_json_file(app_.paths.data_dir + "/bot_runtime_state.json", runtime);
    std::this_thread::sleep_for(std::chrono::milliseconds(800 + (int)(rand01() * 1200)));
  }
  write_json_file(history_path, history);
  write_json_file(meta_path, meta);
  log("SUCCESS", "browsed " + std::to_string(added) + " recommended videos");
  return added;
}

int Monitor::check_once() {
  int total = browse_recommendations();
  total += scan_video_comments();
  total += check_reply_feed();
  total += check_mentions();
  log("INFO", "one-shot check done, processed=" + std::to_string(total));
  return 0;
}

int Monitor::check_video(const std::string& bvid) {
  std::string err;
  VideoInfo info = video_info(net_, bvid, 0, err);
  if (!err.empty()) {
    log("ERROR", "video info failed: " + err);
    return 1;
  }
  auto cmts = video_comments(net_, info.aid, err);
  if (!err.empty()) {
    log("ERROR", "video comments failed: " + err);
    return 1;
  }
  std::vector<Comment> candidates;
  for (const auto& c : cmts) {
    if (c.member_mid == app_.uid) continue;
    std::string id = std::to_string(c.rpid);
    if (cmt_.is_processed(id)) continue;
    Comment cc;
    cc.id = c.rpid;
    cc.aid = info.aid;
    cc.bvid = info.bvid;
    cc.content = trim(c.message);
    cc.user = c.member_uname;
    cc.user_id = c.member_mid;
    cc.root = c.rpid;
    cc.parent = c.rpid;
    cc.source = "video_check";
    candidates.push_back(cc);
  }
  log("SUCCESS", "video " + bvid + " (" + info.title + ") comments=" +
                     std::to_string(cmts.size()) + " candidates=" +
                     std::to_string(candidates.size()));
  int limit = max_replies();
  int count = 0;
  for (size_t i = 0; i < candidates.size(); i++) {
    if (count >= limit) break;
    bool handled = handle_comment(candidates[i]);
    if (handled) count++;
    cmt_.mark_processed(std::to_string(candidates[i].id));
    if (i + 1 < candidates.size()) {
      std::this_thread::sleep_for(std::chrono::milliseconds(1000 + (int)(rand01() * 2000)));
    }
  }
  log("INFO", "video check done, replied=" + std::to_string(count));
  return 0;
}

int Monitor::check_coin(const std::string& bvid) {
  std::string err;
  VideoInfo info = video_info(net_, bvid, 0, err);
  if (!err.empty()) {
    log("ERROR", "video info failed: " + err);
    return 1;
  }
  std::string cerr = pay_coin(net_, csrf(), info.aid, bvid);
  if (!cerr.empty()) {
    log("ERROR", "coin check failed: " + cerr);
    return 1;
  }
  log("SUCCESS", "coin ok " + bvid);
  return 0;
}

std::string Monitor::chat(const std::string& prompt) {
  return ai_.chat({{"system", "You are a concise assistant."}, {"user", prompt}});
}

}  // namespace bili
