#include "dns.h"

#include "platform.h"

#include <cstring>
#include <random>

namespace bili {
namespace {

const char* kAliyunDns[] = {"223.5.5.5", "223.6.6.6"};
constexpr int kDnsPort = 53;

uint16_t rand_id() {
  std::random_device rd;
  return (uint16_t)((rd() ^ (rd() << 8)) & 0xffff);
}

std::string encode_qname(const std::string& host) {
  std::string out;
  size_t start = 0;
  while (start < host.size()) {
    size_t dot = host.find('.', start);
    if (dot == std::string::npos) dot = host.size();
    size_t len = dot - start;
    out.push_back((char)len);
    out.append(host, start, len);
    start = dot + 1;
  }
  out.push_back(0);
  return out;
}

std::vector<std::string> query_server(const std::string& server, const std::string& host,
                                      int timeout_ms) {
  std::vector<std::string> result;
#ifdef _WIN32
  static bool ws_init = [] {
    WSADATA wsa{};
    WSAStartup(MAKEWORD(2, 2), &wsa);
    return true;
  }();
  (void)ws_init;
#endif
  int fd = socket(AF_INET, SOCK_DGRAM, 0);
  if (fd < 0) return result;

  sockaddr_in addr{};
  addr.sin_family = AF_INET;
  addr.sin_port = htons(kDnsPort);
  if (posix_inet_pton(server.c_str(), &addr.sin_addr) != 1) {
    posix_close(fd);
    return result;
  }

  std::string query;
  uint16_t id = rand_id();
  uint16_t id_be = htons(id);
  query.append((const char*)&id_be, 2);
  uint16_t flags = htons(0x0100);  // RD
  query.append((const char*)&flags, 2);
  uint16_t counts[4] = {htons(1), 0, 0, 0};
  query.append((const char*)counts, 8);
  query += encode_qname(host);
  uint16_t qtype = htons(1);  // A
  uint16_t qclass = htons(1);
  query.append((const char*)&qtype, 2);
  query.append((const char*)&qclass, 2);

  if (sendto(fd, query.data(), (int)query.size(), 0, (sockaddr*)&addr, sizeof(addr)) < 0) {
    posix_close(fd);
    return result;
  }

#ifdef _WIN32
  fd_set rset;
  FD_ZERO(&rset);
  FD_SET((SOCKET)fd, &rset);
  timeval tv{timeout_ms / 1000, (timeout_ms % 1000) * 1000};
  if (select(0, &rset, nullptr, nullptr, &tv) <= 0) {
    posix_close(fd);
    return result;
  }
#else
  pollfd pfd{fd, POLLIN, 0};
  if (poll(&pfd, 1, timeout_ms) <= 0) {
    posix_close(fd);
    return result;
  }
#endif

  char buf[4096];
  socklen_t alen = sizeof(addr);
  ssize_t n = recvfrom(fd, buf, sizeof(buf), 0, (sockaddr*)&addr, &alen);
  posix_close(fd);
  if (n < 12) return result;

  if ((unsigned char)buf[0] != (unsigned char)(id >> 8) ||
      (unsigned char)buf[1] != (unsigned char)(id & 0xff)) {
    return result;
  }

  uint16_t ancount = ntohs(*(uint16_t*)(buf + 6));
  size_t pos = 12;
  while (pos < (size_t)n && buf[pos] != 0) {
    pos += (unsigned char)buf[pos] + 1;
  }
  pos += 5;

  for (uint16_t i = 0; i < ancount && pos + 12 <= (size_t)n; ++i) {
    while (pos < (size_t)n) {
      unsigned char c = (unsigned char)buf[pos];
      if (c == 0) {
        pos++;
        break;
      }
      if ((c & 0xc0) == 0xc0) {
        pos += 2;
        break;
      }
      pos += 1 + c;
    }
    if (pos + 10 > (size_t)n) break;
    uint16_t type = ntohs(*(uint16_t*)(buf + pos));
    uint16_t rdlen = ntohs(*(uint16_t*)(buf + pos + 8));
    pos += 10;
    if (type == 1 && rdlen == 4 && pos + 4 <= (size_t)n) {
      char ip[INET_ADDRSTRLEN] = {0};
#ifdef _WIN32
      snprintf(ip, sizeof(ip), "%u.%u.%u.%u", (unsigned char)buf[pos],
               (unsigned char)buf[pos + 1], (unsigned char)buf[pos + 2],
               (unsigned char)buf[pos + 3]);
#else
      inet_ntop(AF_INET, buf + pos, ip, sizeof(ip));
#endif
      result.emplace_back(ip);
    }
    pos += rdlen;
  }
  return result;
}

}  // namespace

std::vector<std::string> resolve_aliyun_v4(const std::string& host, int timeout_ms) {
  for (const char* server : kAliyunDns) {
    std::vector<std::string> ips = query_server(server, host, timeout_ms);
    if (!ips.empty()) return ips;
  }
  return {};
}

}  // namespace bili
