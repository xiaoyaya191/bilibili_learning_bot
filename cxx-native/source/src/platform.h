#pragma once

// Small platform shim so the same C++ sources build on Linux/WSL and Windows
// MinGW (Winsock + MSVC-compatible time functions).

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0601
#endif
#include <winsock2.h>
#include <ws2tcpip.h>

#include <cstdio>
#include <ctime>

inline void localtime_r(const std::time_t* t, std::tm* out) { localtime_s(out, t); }
inline std::time_t timegm(std::tm* tm) { return _mkgmtime(tm); }
inline int posix_close(int fd) { return closesocket(fd); }
inline int posix_inet_pton(const char* src, in_addr* dst) {
  unsigned int a, b, c, d;
  char extra;
  if (std::sscanf(src, "%u.%u.%u.%u%c", &a, &b, &c, &d, &extra) != 4) return 0;
  if (a > 255 || b > 255 || c > 255 || d > 255) return 0;
  dst->s_addr = htonl((a << 24) | (b << 16) | (c << 8) | d);
  return 1;
}
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/poll.h>
#include <unistd.h>

inline int posix_inet_pton(const char* src, in_addr* dst) {
  return inet_pton(AF_INET, src, dst);
}
inline int posix_close(int fd) { return close(fd); }
#endif
