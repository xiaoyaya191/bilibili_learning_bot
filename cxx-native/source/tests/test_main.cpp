#include <cstdio>
#include <filesystem>
#include <fstream>
#include <string>

#include "config.h"
#include "cookies.h"
#include "dns.h"
#include "kb.h"
#include "state.h"
#include "zipwriter.h"
#include "export.h"
#include "urlcodec.h"
#include "wbi.h"

namespace fs = std::filesystem;

static int g_failures = 0;

#define CHECK(cond)                                                     \
  do {                                                                  \
    if (!(cond)) {                                                      \
      std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
      g_failures++;                                                     \
    }                                                                   \
  } while (0)

static void write_file(const std::string& path, const std::string& content) {
  std::ofstream out(path, std::ios::binary);
  out << content;
}

int main() {
  // urlcodec
  CHECK(bili::percent_encode("a b[]") == "a+b%5B%5D");
  CHECK(bili::percent_encode("BV1xx411c7mD") == "BV1xx411c7mD");
  CHECK(bili::percent_decode("a+b%5B%5D") == "a b[]");
  auto q = bili::build_query_string({{"zab", "1 2"}, {"bar", "514"}});
  CHECK(q == "bar=514&zab=1+2");

  // md5
  CHECK(bili::md5_hex("abc") == "900150983cd24fb0d6963f7d28e17f72");

  // config + cookies roundtrip with BOM
  fs::path dir = fs::temp_directory_path() / "bili_native_test";
  fs::remove_all(dir);
  fs::create_directories(dir / "Data");
  write_file((dir / "Data" / "bilibili_cookies.json").string(),
             "\xEF\xBB\xBF{\"DedeUserID\":\"1928778168\",\"SESSDATA\":\"s\",\"bili_jct\":\"j\"}");
  write_file((dir / "Data" / "config.json").string(),
             "{\"api\":{\"unified_base_url\":\"http://192.168.3.170:3000/v1\"}}");
  bili::App app = bili::load_app(dir.string());
  CHECK(app.uid == 1928778168);
  CHECK(bili::get_str(app, "api", "unified_base_url") == "http://192.168.3.170:3000/v1");
  CHECK(bili::cookie_value(app, "SESSDATA") == "s");

  // buvid3 generation
  bili::App app2 = bili::load_app(dir.string());
  CHECK(bili::ensure_buvid3(app2));
  std::string buvid3 = bili::cookie_value(app2, "buvid3");
  CHECK(buvid3.size() == 41);  // UUID(36) + "infoc"(5)
  CHECK(buvid3.rfind("infoc") == 36);

  std::string mixin =
      "7cd084941338484aae1ad9425b84077c4932caff0ff746eab6f01bf08b70ac45";
  std::string digest = bili::md5_hex("bar=514&wts=1702204723&zab=1+2" + mixin);
  CHECK(digest.size() == 32);

  // Aliyun DNS: must return an IPv4 record for a public host.
  auto ips = bili::resolve_aliyun_v4("api.bilibili.com");
  CHECK(!ips.empty());
  if (!ips.empty()) {
    std::printf("[OK] dns api.bilibili.com -> %s\n", ips[0].c_str());
  }

  // CommentLog: processed/replied/liked all participate in dedup.
  fs::path state_dir = fs::temp_directory_path() / "bili_state_test";
  fs::remove_all(state_dir);
  fs::create_directories(state_dir);
  bili::CommentLog cl((state_dir / "comment_log.json").string());
  CHECK(cl.load());
  cl.mark_replied("1001");
  cl.mark_liked("1002");
  cl.mark_processed("1003");
  CHECK(cl.is_processed("1001"));
  CHECK(cl.is_processed("1002"));
  CHECK(cl.is_processed("1003"));
  bili::CommentLog cl2((state_dir / "comment_log.json").string());
  CHECK(cl2.load());
  CHECK(cl2.is_processed("1002"));  // survives restart

  // Reply feed baseline marks historical replies processed.
  bili::CommentLog bl((state_dir / "baseline.json").string());
  CHECK(bl.load());
  CHECK(!bl.reply_feed_baseline());
  bl.set_reply_feed_baseline({"1", "2", "3"});
  CHECK(bl.reply_feed_baseline());
  CHECK(bl.is_processed("2"));

  // Three-action dedup + daily coin count.
  bili::CommentLog tl((state_dir / "three.json").string());
  CHECK(tl.load());
  CHECK(!tl.three_action_done("BV1xx"));
  tl.mark_three_action("BV1xx", {{"like", "ok"}});
  CHECK(tl.three_action_done("BV1xx"));
  CHECK(tl.coin_used_today() == 0);
  tl.mark_three_action("BV1yy", {{"coin", "ok"}});
  CHECK(tl.coin_used_today() == 1);

  // AtState attempts + processed.
  bili::AtState at((state_dir / "at.json").string());
  CHECK(at.load());
  CHECK(at.record_attempt("n1") == 1);
  CHECK(at.record_attempt("n1") == 2);
  at.mark_processed("n1");
  CHECK(at.processed("n1"));

  // KnowledgeBase: Python-compatible metadata + markdown notes + search.
  fs::path kb_dir = fs::temp_directory_path() / "bili_kb_test";
  fs::remove_all(kb_dir);
  bili::KnowledgeBase kb((kb_dir / "knowledge_metadata.json").string(),
                        (kb_dir / "KnowledgeBase").string());
  CHECK(kb.load());
  CHECK(kb.add_note("视频学习", "C++ 视频学习笔记", "BV1xx", "讲解并发编程与内存模型"));
  CHECK(kb.note_count() == 1);
  auto hits = kb.search("并发");
  CHECK(hits.size() == 1);
  CHECK(hits[0].title == "C++ 视频学习笔记");
  CHECK(kb.search("量子纠缠xyz").empty());
  auto bad = kb.search("量子纠缠xyz");
  if (!bad.empty()) std::printf("[DBG] bad hit score=%.2f title=%s\n", bad[0].score,
                               bad[0].title.c_str());
  CHECK(bad.empty());
  std::ifstream meta((kb_dir / "knowledge_metadata.json").string());
  std::string meta_raw((std::istreambuf_iterator<char>(meta)), std::istreambuf_iterator<char>());
  CHECK(meta_raw.find("file_index") != std::string::npos);
  CHECK(meta_raw.find("categories") != std::string::npos);

  // ZIP writer + export pipeline.
  CHECK(bili::crc32("123456789") == 0xCBF43926);
  std::string zip = bili::build_zip({{"word/document.xml", "<w:document/>"}});
  CHECK(zip.size() > 4 && zip.substr(0, 4) == std::string("PK\x03\x04", 4));
  CHECK(zip.find("word/document.xml") != std::string::npos);

  fs::path exp_dir = fs::temp_directory_path() / "bili_export_test";
  fs::remove_all(exp_dir);
  bili::App exp_app;
  exp_app.paths.data_dir = (exp_dir / "Data").string();
  exp_app.paths.knowledge_metadata_file = (exp_dir / "knowledge_metadata.json").string();
  exp_app.paths.knowledge_base_dir = (exp_dir / "KnowledgeBase").string();
  bili::KnowledgeBase exp_kb(exp_app.paths.knowledge_metadata_file,
                            exp_app.paths.knowledge_base_dir);
  CHECK(exp_kb.load());
  CHECK(exp_kb.add_note("视频学习", "导出测试", "BVtest", "# 标题\n内容第一行\n内容第二行"));
  std::string err;
  std::string md_path = bili::export_note(exp_app, "BVtest", "md", err);
  CHECK(!md_path.empty() && err.empty());
  std::string docx_path = bili::export_note(exp_app, "BVtest", "docx", err);
  CHECK(!docx_path.empty() && err.empty());
  std::string pdf_path = bili::export_note(exp_app, "BVtest", "pdf", err);
  CHECK(!pdf_path.empty() && err.empty());
  std::ifstream pdf_in(pdf_path, std::ios::binary);
  std::string pdf_head(5, 0);
  pdf_in.read(&pdf_head[0], 5);
  CHECK(pdf_head == "%PDF-");

  std::printf("tests: %s\n", g_failures == 0 ? "PASS" : "FAIL");
  return g_failures == 0 ? 0 : 1;
}
