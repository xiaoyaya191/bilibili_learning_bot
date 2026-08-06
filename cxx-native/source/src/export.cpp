#include "export.h"

#include <algorithm>
#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include <cstdio>
#include <sstream>
#include <vector>

#include "kb.h"
#include "zipwriter.h"
#include "version_history.h"

namespace fs = std::filesystem;

namespace bili {
namespace {

std::string read_file(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return "";
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

bool write_file(const std::string& path, const std::string& content) {
  fs::create_directories(fs::path(path).parent_path());
  std::ofstream out(path, std::ios::binary);
  if (!out) return false;
  out << content;
  return out.good();
}

std::string xml_escape(const std::string& s) {
  std::string out;
  for (char c : s) {
    switch (c) {
      case '&': out += "&amp;"; break;
      case '<': out += "&lt;"; break;
      case '>': out += "&gt;"; break;
      case '"': out += "&quot;"; break;
      case '\'': out += "&apos;"; break;
      default: out += c;
    }
  }
  return out;
}

std::vector<std::string> lines_of(const std::string& s) {
	std::vector<std::string> out;
	std::istringstream iss(s);
	std::string line;
	while (std::getline(iss, line)) out.push_back(line);
	return out;
}

std::string trim_copy(const std::string& s);
std::string json_escape(const std::string& s);

std::string sanitize_name(const std::string& s) {
  std::string out = s;
  for (char& c : out) {
    if (c == '/' || c == '\\' || c == ':' || c == '*' || c == '?' || c == '"' ||
        c == '<' || c == '>' || c == '|') {
      c = '_';
    }
  }
  if (out.empty()) out = "note";
  return out;
}

std::string build_docx(const std::string& title, const std::string& content) {
  std::string body;
  auto paragraphs = lines_of(content);
  if (!title.empty()) {
    body += "<w:p><w:pPr><w:pStyle w:val=\"Heading1\"/></w:pPr><w:r><w:t>" +
            xml_escape(title) + "</w:t></w:r></w:p>";
  }
  for (const auto& line : paragraphs) {
    if (line.empty()) continue;
    body += "<w:p><w:r><w:t>" + xml_escape(line) + "</w:t></w:r></w:p>";
  }

  std::string content_types =
      "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
      "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
      "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
      "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
      "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
      "</Types>";

  std::string rels =
      "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
      "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
      "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>"
      "</Relationships>";

  std::string document =
      "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
      "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
      "<w:body>" +
      body +
      "<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/><w:pgMar w:top=\"1440\" w:right=\"1440\" "
      "w:bottom=\"1440\" w:left=\"1440\"/></w:sectPr></w:body></w:document>";

  return build_zip({{"[Content_Types].xml", content_types},
                    {"_rels/.rels", rels},
                    {"word/document.xml", document}});
}

std::string build_pdf(const std::string& title, const std::string& content) {
  auto paragraphs = lines_of(content);
  std::string pages;
  int line_index = 0;
  int page_num = 1;
  std::ostringstream stream;
  std::vector<std::string> objects;

  auto esc = [](const std::string& s) {
    std::string out;
    for (unsigned char c : s) {
      if (c < 32 || c > 126) {
        // Non-ASCII (e.g. Chinese) kept as UTF-16BE hex escapes; viewers need
        // a matching embedded font to render them.
        std::ostringstream hex;
        hex << "<";
        const char* hexd = "0123456789ABCDEF";
        hex << hexd[(c >> 4) & 0xF] << hexd[c & 0xF];
        out += hex.str();
      } else if (c == '\\' || c == '(' || c == ')') {
        out += '\\';
        out += (char)c;
      } else {
        out += (char)c;
      }
    }
    return out;
  };

  // Build one page with up to 45 lines.
  std::string content_stream;
  for (size_t i = 0; i < paragraphs.size(); i++) {
    if (!paragraphs[i].empty()) {
      content_stream += "BT /F1 11 Tf 50 " +
                        std::to_string(800 - (line_index % 45) * 16) + " Td (" +
                        esc(paragraphs[i]) + ") Tj ET\n";
    }
    line_index++;
    if (line_index % 45 == 0 && i + 1 < paragraphs.size()) {
      pages += std::to_string(objects.size() + 3) + " 0 R ";
      page_num++;
    }
  }
  if (pages.empty()) pages = "3 0 R ";
  // Simplify: one page, pagination TODO.
  std::string page_stream = "BT /F1 16 Tf 50 810 Td (" + esc(title) + ") Tj ET\n" + content_stream;
  std::string page_obj = "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                         "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>";
  std::string catalog = "<< /Type /Catalog /Pages 2 0 R >>";
  std::string pages_obj = "<< /Type /Pages /Kids [3 0 R] /Count 1 >>";
  std::string font = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>";

  objects = {catalog, pages_obj, page_obj, page_stream, font};
  std::ostringstream pdf;
  pdf << "%PDF-1.4\n";
  std::vector<size_t> offsets;
  for (size_t i = 0; i < objects.size(); i++) {
    offsets.push_back((size_t)pdf.tellp());
    pdf << (i + 1) << " 0 obj\n" << objects[i] << "\nendobj\n";
  }
  size_t xref = (size_t)pdf.tellp();
  pdf << "xref\n0 " << (objects.size() + 1) << "\n0000000000 65535 f \n";
  for (size_t off : offsets) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%010zu 00000 n \n", off);
    pdf << buf;
  }
  pdf << "trailer\n<< /Size " << (objects.size() + 1) << " /Root 1 0 R >>\nstartxref\n"
      << xref << "\n%%EOF\n";
  return pdf.str();
}

std::string build_html(const std::string& title, const std::string& content) {
  std::string body;
  auto paragraphs = lines_of(content);
  for (const auto& line : paragraphs) {
    if (line.rfind("# ", 0) == 0) {
      body += "<h1>" + xml_escape(line.substr(2)) + "</h1>";
    } else if (line.rfind("## ", 0) == 0) {
      body += "<h2>" + xml_escape(line.substr(3)) + "</h2>";
    } else if (line.empty()) {
      body += "<p></p>";
    } else {
      body += "<p>" + xml_escape(line) + "</p>";
    }
  }
  return "<!doctype html><html><head><meta charset=\"utf-8\"><title>" +
         xml_escape(title) +
         "</title></head><body><h1>" + xml_escape(title) + "</h1>" + body +
         "</body></html>";
}

std::string build_ppt_html(const std::string& title, const std::string& content) {
  auto paragraphs = lines_of(content);
  std::string slides;
  int index = 0;
  std::string current = "<section><h2>" + xml_escape(title) + "</h2>";
  for (const auto& line : paragraphs) {
    if (line.empty()) continue;
    current += "<p>" + xml_escape(line) + "</p>";
    if (++index % 8 == 0) {
      current += "</section>";
      slides += current;
      current = "<section>";
    }
  }
  if (current != "<section>") {
    current += "</section>";
    slides += current;
  }
  return "<!doctype html><html><head><meta charset=\"utf-8\"><title>" +
         xml_escape(title) +
         "</title><style>section{min-height:90vh;padding:8vh 6vw;}h2{color:#d97706;}"
         "p{font-size:1.4rem;line-height:1.8;}</style></head><body>" + slides +
         "</body></html>";
}

std::string build_mindmap_html(const std::string& title, const std::string& content) {
  auto paragraphs = lines_of(content);
  std::string children;
  for (const auto& line : paragraphs) {
    std::string t = line;
    while (t.rfind('#', 0) == 0) t = t.substr(1);
    t = trim_copy(t);
    if (t.empty()) continue;
    children += "{\"type\":\"paragraph\",\"content\":\"" + json_escape(t) + "\"},";
  }
  if (!children.empty()) children.pop_back();
  std::string root = "{\"content\":\"" + json_escape(title) +
                     "\",\"children\":[" + children + "]}";
  return "<!doctype html><html><head><meta charset=\"utf-8\"><title>" +
         xml_escape(title) +
         "</title></head><body><svg id=\"mindmap\"></svg>"
         "<script src=\"https://cdn.jsdelivr.net/npm/d3@7\"></script>"
         "<script src=\"https://cdn.jsdelivr.net/npm/markmap-view@0.15\"></script>"
         "<script>const root=" +
         root +
         ";const mm=markmap.Markmap.create('#mindmap',{autoFit:true},root);"
         "mm.setData(root);</script></body></html>";
}

std::string trim_copy(const std::string& s) {
  size_t a = s.find_first_not_of(" \t\r\n");
  if (a == std::string::npos) return "";
  size_t b = s.find_last_not_of(" \t\r\n");
  return s.substr(a, b - a + 1);
}

std::string json_escape(const std::string& s) {
  std::string out;
  for (unsigned char c : s) {
    switch (c) {
      case '"': out += "\\\""; break;
      case '\\': out += "\\\\"; break;
      case '\n': out += "\\n"; break;
      case '\r': out += "\\r"; break;
      case '\t': out += "\\t"; break;
      default: out += (char)c;
    }
  }
  return out;
}

}  // namespace

std::string export_note(const App& app, const std::string& bvid, const std::string& fmt,
                        std::string& error) {
  KnowledgeBase kb(app.paths.knowledge_metadata_file, app.paths.knowledge_base_dir);
  if (!kb.load()) {
    error = "knowledge metadata load failed";
    return "";
  }

  std::string rel, title, content;
  const auto& idx = kb.metadata().value("file_index", nlohmann::json::object());
  for (const auto& [cat, entries] : idx.items()) {
    if (!entries.is_array()) continue;
    for (const auto& e : entries) {
      if (e.value("bvid", "") == bvid) {
        rel = e.value("path", "");
        title = e.value("title", "");
        break;
      }
    }
  }
  if (rel.empty()) {
    error = "note not found for " + bvid;
    return "";
  }
  content = read_file(app.paths.knowledge_base_dir + "/" + rel);
  if (content.empty()) {
    error = "note file empty: " + rel;
    return "";
  }

  std::string data;
  std::string ext = fmt;
  if (fmt == "txt" || fmt == "md") {
    data = content;
    ext = fmt;
  } else if (fmt == "html") {
    data = build_html(title, content);
  } else if (fmt == "docx") {
    data = build_docx(title, content);
    ext = "docx";
  } else if (fmt == "pdf") {
    data = build_pdf(title, content);
  } else if (fmt == "ppt") {
    data = build_ppt_html(title, content);
    ext = "html";  // project convention: PPT is an HTML deck
  } else if (fmt == "mm") {
    data = build_mindmap_html(title, content);
    ext = "html";  // markmap standalone page
  } else {
    error = "unsupported format: " + fmt;
    return "";
  }

  fs::path dir = fs::path(app.paths.data_dir) / "exports";
  std::string fname = sanitize_name(bvid);
  if (fmt == "ppt") fname += ".ppt.html";
  else if (fmt == "mm") fname += ".mindmap.html";
  else fname += "." + ext;
  std::string out_path = (dir / fname).string();
  save_note_version(out_path, data, app.config);
  if (!write_file(out_path, data)) {
    error = "write failed: " + out_path;
    return "";
  }
  return out_path;
}

}  // namespace bili
