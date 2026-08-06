#include <cstdio>
#include <string>
#include <iostream>
#include <algorithm>

#include "config.h"
#include "cookies.h"
#include "export.h"
#include "login.h"
#include "monitor.h"
#include "ai.h"
#include "analysis.h"
#include "kb.h"
#include "net.h"
#include "web.h"

namespace {

void usage(const char* argv0) {
  std::printf(
      "bili_native P1\n"
      "Usage:\n"
      "  %s -data <dir> -check                 verify cookie + WBI + basic API\n"
      "  %s -data <dir> -login -qr <png>       QR login and save cookies\n"
      "  %s -data <dir> -once                  monitor one cycle\n"
      "  %s -data <dir> -video BVxxxx          scan one video comments\n"
      "  %s -data <dir> -chat <prompt>         test AI once\n"
      "  %s -data <dir> -coin BVxxxx           test coin once\n",
      "  %s -data <dir> -analyze BVxxxx        fetch subtitles/danmaku + AI summary\n"
      "  %s -data <dir> -kb search <query>     search knowledge base\n"
      "  %s -data <dir> -kb list               list knowledge base notes\n",
      "  %s -data <dir> -export BVxxxx -fmt <fmt>  export note (txt/md/html/docx/pdf/ppt/mm)\n",
      argv0, argv0, argv0, argv0, argv0, argv0, argv0, argv0, argv0);
}

int cmd_check(bili::App& app) {
  if (bili::cookie_value(app, "SESSDATA").empty() || app.uid == 0) {
    std::fprintf(stderr, "[ERR] no valid bilibili_cookies.json, run -login first\n");
    return 1;
  }
  bili::ensure_buvid3(app);
  bili::NetClient prenet(app);
  bili::ensure_buvid4(app, prenet);

  bili::NetClient net(app);
  bili::NetResponse nav = net.get("https://api.bilibili.com/x/web-interface/nav");
  bili::ensure_buvid4(app, net);
  try {
    auto j = nlohmann::json::parse(nav.body);
    std::printf("[OK] nav code=%d isLogin=%d mid=%lld uname=%s\n", j.value("code", -1),
                (long long)j.value("data", nlohmann::json()).value("isLogin", false),
                (long long)j.value("data", nlohmann::json()).value("mid", 0),
                j.value("data", nlohmann::json()).value("uname", "").c_str());
    if (j.value("code", -1) != 0) return 1;
  } catch (...) {
    std::fprintf(stderr, "[ERR] nav parse failed\n");
    return 1;
  }

  bili::NetResponse view = net.get("https://api.bilibili.com/x/web-interface/view",
                                   {{"bvid", "BV1dQTt6dEsq"}}, {}, true);
  try {
    auto j = nlohmann::json::parse(view.body);
    std::printf("[OK] wbi view code=%d aid=%lld title=%s\n", j.value("code", -1),
                j.at("data").value("aid", 0LL),
                j.value("data", nlohmann::json()).value("title", "").c_str());
    return j.value("code", -1) == 0 ? 0 : 1;
  } catch (...) {
    std::fprintf(stderr, "[ERR] view parse failed\n");
    return 1;
  }
}

}  // namespace

int cmd_menu(bili::App& app) {
  while (true) {
    std::printf("\n=== bili_native 菜单 ===\n");
    std::printf("1. 检查账号\n2. 跑一轮监控\n3. 分析视频\n4. 知识库检索\n");
    std::printf("5. 导出笔记\n6. Web 面板\n0. 退出\n请选择: ");
    std::string line;
    std::getline(std::cin, line);
    if (line == "0") return 0;
    if (line == "1") { cmd_check(app); continue; }
    if (line == "2") { bili::Monitor monitor(app); monitor.check_once(); continue; }
    if (line == "3") {
      std::printf("BV号: ");
      std::getline(std::cin, line);
      bili::NetClient net(app); bili::AiClient ai(app, net);
      bili::VideoAnalysis result; std::string err;
      if (bili::analyze_video(app, net, ai, line, result, err)) {
        std::printf("AI 总结:\n%s\n", result.ai_summary.c_str());
      } else {
        std::printf("[ERR] %s\n", err.c_str());
      }
      continue;
    }
    if (line == "4") {
      std::printf("关键词: ");
      std::getline(std::cin, line);
      bili::KnowledgeBase kb(app.paths.knowledge_metadata_file, app.paths.knowledge_base_dir);
      kb.load();
      for (const auto& h : kb.search(line)) {
        std::printf("[%.2f] %s (%s)\n    %s\n", h.score, h.title.c_str(), h.path.c_str(),
                    h.snippet.c_str());
      }
      continue;
    }
    if (line == "5") {
      std::printf("BV号: "); std::getline(std::cin, line);
      std::string err, path = bili::export_note(app, line, "md", err);
      std::printf("%s\n", path.empty() ? err.c_str() : path.c_str());
      continue;
    }
    if (line == "6") {
      bili::Monitor monitor(app);
      bili::WebServer web(app, monitor);
      web.serve(8080);
      return 0;
    }
  }
}

int main(int argc, char** argv) {
  std::string data_dir;
  std::string qr_path = "login_qrcode.png";
  std::string video_bvid;
  std::string chat_text;
  std::string coin_bvid;
  std::string analyze_bvid;
  std::string deep_keyword;
  int deep_count = 3;
  std::string export_bvid;
  std::string export_fmt;
  int web_port = 0;
  std::string html_path;
  std::string kb_action;
  std::string kb_query;
  bool do_login = false;
  bool do_check = false;
  bool do_once = false;
  bool do_menu = false;

  for (int i = 1; i < argc; i++) {
    std::string arg = argv[i];
    if (arg == "-data" && i + 1 < argc) {
      data_dir = argv[++i];
    } else if (arg == "-qr" && i + 1 < argc) {
      qr_path = argv[++i];
    } else if (arg == "-login") {
      do_login = true;
    } else if (arg == "-check") {
      do_check = true;
    } else if (arg == "-once") {
      do_once = true;
    } else if (arg == "-menu") {
      do_menu = true;
    } else if (arg == "-video" && i + 1 < argc) {
      video_bvid = argv[++i];
    } else if (arg == "-chat" && i + 1 < argc) {
      chat_text = argv[++i];
    } else if (arg == "-coin" && i + 1 < argc) {
      coin_bvid = argv[++i];
    } else if (arg == "-analyze" && i + 1 < argc) {
      analyze_bvid = argv[++i];
    } else if (arg == "-deep" && i + 1 < argc) {
      deep_keyword = argv[++i];
    } else if (arg == "-count" && i + 1 < argc) {
      deep_count = std::max(1, std::stoi(argv[++i]));
    } else if (arg == "-export" && i + 1 < argc) {
      export_bvid = argv[++i];
    } else if (arg == "-fmt" && i + 1 < argc) {
      export_fmt = argv[++i];
    } else if (arg == "-web" && i + 1 < argc) {
      web_port = std::stoi(argv[++i]);
    } else if (arg == "-html" && i + 1 < argc) {
      html_path = argv[++i];
    } else if (arg == "-kb" && i + 1 < argc) {
      kb_action = argv[++i];
      if (kb_action == "search" && i + 1 < argc) kb_query = argv[++i];
    } else if (arg == "-h" || arg == "--help") {
      usage(argv[0]);
      return 0;
    }
  }

  bili::App app = bili::load_app(data_dir);

  if (do_login) {
    return bili::run_login(app, qr_path) ? 0 : 1;
  }
  if (do_check) {
    return cmd_check(app);
  }
  if (web_port > 0) {
    bili::Monitor monitor(app);
    bili::WebServer web(app, monitor, html_path);
    return web.serve(web_port) ? 0 : 1;
  }
  if (app.uid == 0 || bili::cookie_value(app, "SESSDATA").empty()) {
    std::fprintf(stderr, "[ERR] no valid bilibili_cookies.json, run -login first\n");
    return 1;
  }
  bili::ensure_buvid3(app);

  if (!analyze_bvid.empty()) {
    bili::NetClient net(app);
    bili::AiClient ai(app, net);
    bili::VideoAnalysis result;
    std::string err;
    if (!bili::analyze_video(app, net, ai, analyze_bvid, result, err)) {
      std::fprintf(stderr, "[ERR] analyze failed: %s\n", err.c_str());
      return 1;
    }
    std::printf("标题: %s\n", result.info.title.c_str());
    std::printf("字幕: %zu 行, 弹幕: %zu 行, B站总结: %zu 字\n",
                std::count(result.subtitles.begin(), result.subtitles.end(), '\n'),
                std::count(result.danmaku.begin(), result.danmaku.end(), '\n'),
                result.bili_summary.size());
    std::printf("AI 总结:\n%s\n", result.ai_summary.c_str());
    bili::KnowledgeBase kb(app.paths.knowledge_metadata_file, app.paths.knowledge_base_dir);
    kb.load();
    kb.add_note(bili::detect_category(result.info.title, result.ai_summary), result.info.title,
                analyze_bvid, result.ai_summary, app.config);
    std::printf("[OK] 已保存到知识库 (总笔记 %zu 条)\n", kb.note_count());
    return 0;
  }

  if (!deep_keyword.empty()) {
    bili::NetClient net(app);
    bili::AiClient ai(app, net);
    std::vector<bili::DeepResult> results;
    std::string err;
    if (!bili::deep_dive(app, net, ai, deep_keyword, deep_count, results, err)) {
      std::fprintf(stderr, "[ERR] deep dive failed: %s\n", err.c_str());
      return 1;
    }
    std::printf("深度研究完成，共 %zu 条笔记:\n", results.size());
    for (const auto& r : results) {
      std::printf("[%s] %s\n    %s\n", r.bvid.c_str(), r.title.c_str(), r.summary.c_str());
    }
    return 0;
  }

  if (!kb_action.empty()) {
    bili::KnowledgeBase kb(app.paths.knowledge_metadata_file, app.paths.knowledge_base_dir);
    if (!kb.load()) {
      std::fprintf(stderr, "[ERR] knowledge metadata load failed\n");
      return 1;
    }
    if (kb_action == "search") {
      auto hits = kb.search(kb_query);
      std::printf("命中 %zu 条:\n", hits.size());
      for (const auto& h : hits) {
        std::printf("  [%.2f] %s (%s)\n    %s\n", h.score, h.title.c_str(),
                    h.path.c_str(), h.snippet.c_str());
      }
    } else if (kb_action == "list") {
      std::printf("知识库笔记总数: %zu\n", kb.note_count());
    }
    return 0;
  }
  if (!export_bvid.empty()) {
    if (export_fmt.empty()) export_fmt = "md";
    std::string err, path = bili::export_note(app, export_bvid, export_fmt, err);
    if (path.empty()) {
      std::fprintf(stderr, "[ERR] export failed: %s\n", err.c_str());
      return 1;
    }
    std::printf("[OK] exported %s (%s) -> %s\n", export_bvid.c_str(), export_fmt.c_str(),
                path.c_str());
    return 0;
  }

  bili::Monitor monitor(app);
  if (do_menu) return cmd_menu(app);
  if (do_once) return monitor.check_once();
  if (!video_bvid.empty()) return monitor.check_video(video_bvid);
  if (!coin_bvid.empty()) return monitor.check_coin(coin_bvid);
  if (!chat_text.empty()) {
    std::string reply = monitor.chat(chat_text);
    std::printf("%s\n", reply.empty() ? "(empty)" : reply.c_str());
    return reply.empty() ? 1 : 0;
  }
  usage(argv[0]);
  return 0;
}
