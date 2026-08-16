#include "api.h"

#include <chrono>
#include <sstream>
#include <random>

#include "cookies.h"
#include "urlcodec.h"
#include "wbi.h"

namespace bili {
namespace {

std::string error_from(const NetResponse& resp, const std::string& fallback) {
  if (!resp.body.empty()) {
    try {
      auto j = nlohmann::json::parse(resp.body);
      if (j.contains("code")) {
        std::ostringstream out;
        out << "code=" << j.value("code", -1LL) << " msg=" << j.value("message", "");
        return out.str();
      }
    } catch (...) {
    }
  }
  return fallback;
}

std::string random_two_chars() {
  static const char kAlphabet[] = "ABCDEFGHIJK";
  std::random_device rd;
  std::string out;
  out += kAlphabet[rd() % 11];
  out += kAlphabet[rd() % 11];
  return out;
}

long long code_of(const NetResponse& resp) {
  try {
    return nlohmann::json::parse(resp.body).value("code", -1LL);
  } catch (const std::exception& e) {
    return -1;
  }
}

}  // namespace

long long num(const nlohmann::json& v) {
  if (v.is_number_integer()) return v.get<long long>();
  if (v.is_number_float()) return (long long)v.get<double>();
  if (v.is_string()) {
    try {
      return std::stoll(v.get<std::string>());
    } catch (...) {
      return 0;
    }
  }
  return 0;
}

std::vector<std::pair<long long, std::string>> user_videos(NetClient& net, long long uid,
                                                           std::string& error) {
  std::vector<std::pair<long long, std::string>> out;
  NetResponse resp =
      net.get("https://api.bilibili.com/x/space/arc/search",
              {{"mid", std::to_string(uid)}, {"ps", "5"}, {"pn", "1"}, {"order", "pubdate"}});
  if (code_of(resp) != 0) {
    error = error_from(resp, "user videos failed");
    return out;
  }
  try {
    auto j = nlohmann::json::parse(resp.body);
    const auto& vlist = j["data"]["list"]["vlist"];
    for (const auto& v : vlist) {
      out.emplace_back(num(v.value("aid", nlohmann::json())), v.value("bvid", ""));
    }
  } catch (...) {
    error = "user videos parse failed";
  }
  return out;
}

std::vector<VideoComment> video_comments(NetClient& net, long long aid, std::string& error) {
  std::vector<VideoComment> out;
  NetResponse resp = net.get("https://api.bilibili.com/x/v2/reply",
                             {{"type", "1"}, {"oid", std::to_string(aid)},
                             {"sort", "0"}, {"pn", "1"}, {"ps", "20"}},
                             {}, /*signed_request=*/true);
  long long code = code_of(resp);
  if (code == 12002) return out;
  if (code != 0) {
    error = error_from(resp, "comments failed");
    return out;
  }
  try {
    auto j = nlohmann::json::parse(resp.body);
    const auto& replies = j["data"].value("replies", nlohmann::json::array());
    for (const auto& c : replies) {
      VideoComment vc;
      vc.rpid = num(c.value("rpid", nlohmann::json()));
      if (vc.rpid == 0) vc.rpid = num(c.value("id", nlohmann::json()));
      vc.ctime = num(c.value("ctime", nlohmann::json()));
      const auto& member = c.value("member", nlohmann::json::object());
      vc.member_mid = num(member.value("mid", nlohmann::json()));
      vc.member_uname = member.value("uname", "");
      vc.message = c.value("content", nlohmann::json::object()).value("message", "");
      if (vc.rpid != 0) out.push_back(vc);
    }
  } catch (const std::exception& e) {
    error = "comments parse failed";
  }
  return out;
}

nlohmann::json reply_feed(NetClient& net, std::string& error) {
  NetResponse resp = net.get("https://api.bilibili.com/x/msgfeed/reply",
                             {{"platform", "web"}, {"build", "0"}, {"mobi_app", "web"}});
  if (code_of(resp) != 0) {
    error = error_from(resp, "reply feed failed");
    return nlohmann::json::array();
  }
  try {
    auto j = nlohmann::json::parse(resp.body);
    const auto& items = j["data"].value("items", nlohmann::json::array());
    if (items.is_array() && !items.empty()) return items;
    return j["data"].value("list", nlohmann::json::array());
  } catch (...) {
    error = "reply feed parse failed";
    return nlohmann::json::array();
  }
}

nlohmann::json at_feed(NetClient& net, std::string& error) {
  NetResponse resp = net.get("https://api.bilibili.com/x/msgfeed/at",
                             {{"platform", "web"}, {"build", "0"}, {"mobi_app", "web"}});
  if (code_of(resp) != 0) {
    error = error_from(resp, "at feed failed");
    return nlohmann::json::array();
  }
  try {
    auto j = nlohmann::json::parse(resp.body);
    const auto& items = j["data"].value("items", nlohmann::json::array());
    if (items.is_array() && !items.empty()) return items;
    return j["data"].value("list", nlohmann::json::array());
  } catch (...) {
    error = "at feed parse failed";
    return nlohmann::json::array();
  }
}

VideoInfo video_info(NetClient& net, const std::string& bvid, long long aid,
                     std::string& error) {
  VideoInfo out;
  std::vector<std::pair<std::string, std::string>> params;
  if (!bvid.empty()) params.emplace_back("bvid", bvid);
  if (aid != 0) params.emplace_back("aid", std::to_string(aid));
  NetResponse resp =
      net.get("https://api.bilibili.com/x/web-interface/view", params, {}, true);
  if (code_of(resp) != 0) {
    error = error_from(resp, "video info failed");
    return out;
  }
  try {
    auto j = nlohmann::json::parse(resp.body);
    const auto& d = j["data"];
    out.aid = num(d.value("aid", nlohmann::json()));
    out.cid = num(d.value("cid", nlohmann::json()));
    out.bvid = d.value("bvid", "");
    out.title = d.value("title", "");
    out.desc = d.value("desc", "");
    out.up_mid = num(d.value("owner", nlohmann::json::object()).value("mid", nlohmann::json()));
  } catch (...) {
    error = "video info parse failed";
  }
  return out;
}

std::string video_ai_summary(NetClient& net, const VideoInfo& info) {
  if (info.aid == 0 || info.cid == 0) return "";
  NetResponse resp =
      net.get("https://api.bilibili.com/x/web-interface/view/conclusion/get",
              {{"aid", std::to_string(info.aid)},
               {"bvid", info.bvid},
               {"cid", std::to_string(info.cid)},
               {"up_mid", std::to_string(info.up_mid)}},
              {}, true);
  if (code_of(resp) != 0) return "";
  try {
    auto j = nlohmann::json::parse(resp.body);
    return j["data"].value("model_result", nlohmann::json::object()).value("summary", "");
  } catch (...) {
    return "";
  }
}

std::string send_comment(NetClient& net, const std::string& csrf, const std::string& text,
                         long long oid, long long root, long long parent) {
  if (root != 0 && root == parent) parent = 0;
  std::vector<std::pair<std::string, std::string>> form = {
      {"oid", std::to_string(oid)},
      {"type", "1"},
      {"message", text},
      {"plat", "1"},
      {"gaia_source", "main_web"},
      {"statistics", R"({"appId":100,"platform":5})"},
      {"csrf", csrf},
      {"csrf_token", csrf}};
  if (root != 0) form.emplace_back("root", std::to_string(root));
  if (parent != 0) form.emplace_back("parent", std::to_string(parent));
  std::vector<std::pair<std::string, std::string>> wbi_params = {
      {"dm_img_list", "[]"},
      {"dm_img_str", random_two_chars()},
      {"dm_cover_img_str", random_two_chars()},
      {"dm_img_inter", "{\"ds\":[],\"wh\":[0,0,0],\"of\":[0,0,0]}"}};
  std::string query = build_query_string(sign_params(net, wbi_params));
  NetResponse resp = net.post("https://api.bilibili.com/x/v2/reply/add?" + query, form);
  return code_of(resp) == 0 ? "" : error_from(resp, "send comment failed");
}

std::string like_comment(NetClient& net, const std::string& csrf, long long oid,
                         long long rpid) {
  NetResponse resp = net.post("https://api.bilibili.com/x/v2/reply/action",
                              {{"oid", std::to_string(oid)},
                               {"type", "1"},
                               {"action", "1"},
                               {"rpid", std::to_string(rpid)},
                               {"csrf", csrf},
                               {"csrf_token", csrf}});
  return code_of(resp) == 0 ? "" : error_from(resp, "like comment failed");
}

std::string report_history(NetClient& net, const App& app, const std::string& bvid, int played_time) {
  std::string err;
  VideoInfo info = video_info(net, bvid, 0, err);
  if (info.aid == 0 || info.cid == 0) return "video info missing";
  auto ts = std::chrono::duration_cast<std::chrono::seconds>(
                std::chrono::system_clock::now().time_since_epoch())
                .count();
  std::string mid = cookie_value(app, "DedeUserID");
  std::string csrf = cookie_value(app, "bili_jct");
  std::vector<std::pair<std::string, std::string>> start = {
      {"aid", std::to_string(info.aid)},
      {"cid", std::to_string(info.cid)},
      {"bvid", bvid},
      {"mid", mid},
      {"csrf", csrf},
      {"played_time", "0"},
      {"realtime", "0"},
      {"start_ts", std::to_string(ts)},
      {"type", "3"},
      {"dt", "2"},
      {"play_type", "1"}};
  NetResponse r1 =
      net.post("https://api.bilibili.com/x/click-interface/web/heartbeat", start,
              {{"Origin", "https://www.bilibili.com"}, {"Referer", "https://www.bilibili.com/video/" + bvid}});
  (void)r1;
  long long real_start = ts - played_time;
  std::vector<std::pair<std::string, std::string>> final = {
      {"aid", std::to_string(info.aid)},
      {"cid", std::to_string(info.cid)},
      {"bvid", bvid},
      {"mid", mid},
      {"csrf", csrf},
      {"played_time", std::to_string(played_time)},
      {"realtime", std::to_string(played_time)},
      {"start_ts", std::to_string(real_start)},
      {"type", "3"},
      {"dt", "2"},
      {"play_type", "0"}};
  NetResponse r2 =
      net.post("https://api.bilibili.com/x/click-interface/web/heartbeat", final,
              {{"Origin", "https://www.bilibili.com"}, {"Referer", "https://www.bilibili.com/video/" + bvid}});
  return code_of(r2) == 0 ? "" : error_from(r2, "heartbeat failed");
}

std::string like_video(NetClient& net, const std::string& csrf, long long aid,
                       const std::string& bvid) {
  NetResponse resp = net.post("https://api.bilibili.com/x/web-interface/archive/like",
                              {{"aid", std::to_string(aid)},
                               {"bvid", bvid},
                               {"like", "1"},
                                {"csrf", csrf},
                                {"csrf_token", csrf}});
  return code_of(resp) == 0 ? "" : error_from(resp, "like video failed");
}

std::string pay_coin(NetClient& net, const std::string& csrf, long long aid,
                     const std::string& bvid) {
  NetResponse resp = net.post("https://api.bilibili.com/x/web-interface/coin/add",
                              {{"aid", std::to_string(aid)},
                               {"bvid", bvid},
                               {"multiply", "1"},
                               {"select_like", "0"},
                                {"csrf", csrf},
                                {"csrf_token", csrf}});
  return code_of(resp) == 0 ? "" : error_from(resp, "pay coin failed");
}

std::string add_favorite(NetClient& net, const std::string& csrf, long long aid,
                         long long folder_id) {
  NetResponse resp = net.post("https://api.bilibili.com/x/v3/fav/resource/deal",
                              {{"rid", std::to_string(aid)},
                               {"type", "2"},
                               {"add_media_ids", std::to_string(folder_id)},
                               {"del_media_ids", ""},
                                {"csrf", csrf},
                                {"csrf_token", csrf}});
  return code_of(resp) == 0 ? "" : error_from(resp, "add favorite failed");
}

long long first_favorite_folder(NetClient& net, long long aid, long long uid,
                                std::string& error) {
  NetResponse resp = net.get("https://api.bilibili.com/x/v3/fav/folder/created/list-all",
                             {{"rid", std::to_string(aid)},
                              {"up_mid", std::to_string(uid)},
                              {"type", "2"}});
  if (code_of(resp) != 0) {
    error = error_from(resp, "favorite folders failed");
    return 0;
  }
  try {
    auto j = nlohmann::json::parse(resp.body);
    const auto& list = j["data"].value("list", nlohmann::json::array());
    if (list.empty()) return 0;
    return num(list[0].value("id", nlohmann::json()));
  } catch (...) {
    error = "favorite folders parse failed";
    return 0;
  }
}

bool has_liked_video(NetClient& net, long long aid, const std::string& bvid) {
  NetResponse resp = net.get("https://api.bilibili.com/x/web-interface/archive/has/like",
                             {{"aid", std::to_string(aid)}, {"bvid", bvid}});
  try {
    return nlohmann::json::parse(resp.body).value("data", false);
  } catch (...) {
    return false;
  }
}


std::string follow_user(NetClient& net, const App& app, long long uid, bool follow) {
  if (uid <= 0) return "invalid uid";
  NetResponse resp = net.post("https://api.bilibili.com/x/relation/modify",
      {{"fid", std::to_string(uid)}, {"act", follow ? "1" : "2"}, {"re_src", "11"},
       {"csrf", cookie_value(app, "bili_jct")}});
  return code_of(resp) == 0 ? "" : error_from(resp, "follow failed");
}
std::string send_private_message(NetClient& net, const App& app, long long receiver_uid,
                                const std::string& text) {
  if (receiver_uid <= 0 || text.empty()) return "invalid receiver or text";
  std::string sender_uid = app.uid > 0 ? std::to_string(app.uid) : cookie_value(app, "DedeUserID");
  if (sender_uid.empty()) return "not logged in";
  nlohmann::json content = {{"content", text}};
  std::string query = build_query_string(sign_params(net, {}));
  NetResponse resp = net.post("https://api.vc.bilibili.com/web_im/v1/web_im/send_msg?" + query,
      {{"msg[sender_uid]", sender_uid},
       {"msg[receiver_id]", std::to_string(receiver_uid)},
       {"msg[receiver_type]", "1"}, {"msg[msg_type]", "1"}, {"msg[msg_status]", "0"},
       {"msg[content]", content.dump()}, {"msg[dev_id]", "A6716E9A-7CE3-47AF-994B-F0B34178D28D"},
       {"msg[new_face_version]", "0"}, {"msg[timestamp]", std::to_string(
           std::chrono::duration_cast<std::chrono::seconds>(std::chrono::system_clock::now().time_since_epoch()).count())},
       {"from_filework", "0"}, {"build", "0"}, {"mobi_app", "web"},
       {"w_sender_uid", sender_uid}, {"w_receiver_id", std::to_string(receiver_uid)},
       {"csrf", cookie_value(app, "bili_jct")},
       {"csrf_token", cookie_value(app, "bili_jct")}});
  try {
    nlohmann::json j = nlohmann::json::parse(resp.body);
    if (j.value("code", -1) == 0) return "";
    return j.value("message", "send failed");
  } catch (...) {
    return "send failed";
  }
}

}  // namespace bili
