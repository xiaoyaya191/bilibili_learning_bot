#include "md5.h"

#include <cstdint>
#include <cstdio>
#include <cstring>

namespace bili {

namespace {

struct MD5Ctx {
  uint32_t a = 0x67452301, b = 0xefcdab89, c = 0x98badcfe, d = 0x10325476;
  uint64_t bits = 0;
  unsigned char buf[64];
  size_t buflen = 0;

  void process_block(const unsigned char* p) {
    uint32_t x[16];
    for (int i = 0; i < 16; i++) {
      x[i] = (uint32_t)p[i * 4] | ((uint32_t)p[i * 4 + 1] << 8) |
             ((uint32_t)p[i * 4 + 2] << 16) | ((uint32_t)p[i * 4 + 3] << 24);
    }
    uint32_t A = a, B = b, C = c, D = d;
    auto F = [](uint32_t x, uint32_t y, uint32_t z) { return (x & y) | (~x & z); };
    auto G = [](uint32_t x, uint32_t y, uint32_t z) { return (x & z) | (y & ~z); };
    auto H = [](uint32_t x, uint32_t y, uint32_t z) { return x ^ y ^ z; };
    auto I = [](uint32_t x, uint32_t y, uint32_t z) { return y ^ (x | ~z); };
    auto ROL = [](uint32_t v, int s) { return (v << s) | (v >> (32 - s)); };
    auto STEP = [&](auto fn, uint32_t& w, uint32_t x, uint32_t y, uint32_t z, uint32_t m,
                    int s, uint32_t k) { w += fn(x, y, z) + m + k; w = ROL(w, s) + x; };

    STEP(F, A, B, C, D, x[0], 7, 0xd76aa478); STEP(F, D, A, B, C, x[1], 12, 0xe8c7b756);
    STEP(F, C, D, A, B, x[2], 17, 0x242070db); STEP(F, B, C, D, A, x[3], 22, 0xc1bdceee);
    STEP(F, A, B, C, D, x[4], 7, 0xf57c0faf); STEP(F, D, A, B, C, x[5], 12, 0x4787c62a);
    STEP(F, C, D, A, B, x[6], 17, 0xa8304613); STEP(F, B, C, D, A, x[7], 22, 0xfd469501);
    STEP(F, A, B, C, D, x[8], 7, 0x698098d8); STEP(F, D, A, B, C, x[9], 12, 0x8b44f7af);
    STEP(F, C, D, A, B, x[10], 17, 0xffff5bb1); STEP(F, B, C, D, A, x[11], 22, 0x895cd7be);
    STEP(F, A, B, C, D, x[12], 7, 0x6b901122); STEP(F, D, A, B, C, x[13], 12, 0xfd987193);
    STEP(F, C, D, A, B, x[14], 17, 0xa679438e); STEP(F, B, C, D, A, x[15], 22, 0x49b40821);

    STEP(G, A, B, C, D, x[1], 5, 0xf61e2562); STEP(G, D, A, B, C, x[6], 9, 0xc040b340);
    STEP(G, C, D, A, B, x[11], 14, 0x265e5a51); STEP(G, B, C, D, A, x[0], 20, 0xe9b6c7aa);
    STEP(G, A, B, C, D, x[5], 5, 0xd62f105d); STEP(G, D, A, B, C, x[10], 9, 0x02441453);
    STEP(G, C, D, A, B, x[15], 14, 0xd8a1e681); STEP(G, B, C, D, A, x[4], 20, 0xe7d3fbc8);
    STEP(G, A, B, C, D, x[9], 5, 0x21e1cde6); STEP(G, D, A, B, C, x[14], 9, 0xc33707d6);
    STEP(G, C, D, A, B, x[3], 14, 0xf4d50d87); STEP(G, B, C, D, A, x[8], 20, 0x455a14ed);
    STEP(G, A, B, C, D, x[13], 5, 0xa9e3e905); STEP(G, D, A, B, C, x[2], 9, 0xfcefa3f8);
    STEP(G, C, D, A, B, x[7], 14, 0x676f02d9); STEP(G, B, C, D, A, x[12], 20, 0x8d2a4c8a);

    STEP(H, A, B, C, D, x[5], 4, 0xfffa3942); STEP(H, D, A, B, C, x[8], 11, 0x8771f681);
    STEP(H, C, D, A, B, x[11], 16, 0x6d9d6122); STEP(H, B, C, D, A, x[14], 23, 0xfde5380c);
    STEP(H, A, B, C, D, x[1], 4, 0xa4beea44); STEP(H, D, A, B, C, x[4], 11, 0x4bdecfa9);
    STEP(H, C, D, A, B, x[7], 16, 0xf6bb4b60); STEP(H, B, C, D, A, x[10], 23, 0xbebfbc70);
    STEP(H, A, B, C, D, x[13], 4, 0x289b7ec6); STEP(H, D, A, B, C, x[0], 11, 0xeaa127fa);
    STEP(H, C, D, A, B, x[3], 16, 0xd4ef3085); STEP(H, B, C, D, A, x[6], 23, 0x04881d05);
    STEP(H, A, B, C, D, x[9], 4, 0xd9d4d039); STEP(H, D, A, B, C, x[12], 11, 0xe6db99e5);
    STEP(H, C, D, A, B, x[15], 16, 0x1fa27cf8); STEP(H, B, C, D, A, x[2], 23, 0xc4ac5665);

    STEP(I, A, B, C, D, x[0], 6, 0xf4292244); STEP(I, D, A, B, C, x[7], 10, 0x432aff97);
    STEP(I, C, D, A, B, x[14], 15, 0xab9423a7); STEP(I, B, C, D, A, x[5], 21, 0xfc93a039);
    STEP(I, A, B, C, D, x[12], 6, 0x655b59c3); STEP(I, D, A, B, C, x[3], 10, 0x8f0ccc92);
    STEP(I, C, D, A, B, x[10], 15, 0xffeff47d); STEP(I, B, C, D, A, x[1], 21, 0x85845dd1);
    STEP(I, A, B, C, D, x[8], 6, 0x6fa87e4f); STEP(I, D, A, B, C, x[15], 10, 0xfe2ce6e0);
    STEP(I, C, D, A, B, x[6], 15, 0xa3014314); STEP(I, B, C, D, A, x[13], 21, 0x4e0811a1);
    STEP(I, A, B, C, D, x[4], 6, 0xf7537e82); STEP(I, D, A, B, C, x[11], 10, 0xbd3af235);
    STEP(I, C, D, A, B, x[2], 15, 0x2ad7d2bb); STEP(I, B, C, D, A, x[9], 21, 0xeb86d391);

    a += A; b += B; c += C; d += D;
  }

  void update(const unsigned char* data, size_t len) {
    bits += (uint64_t)len * 8;
    while (len > 0) {
      size_t take = 64 - buflen;
      if (take > len) take = len;
      std::memcpy(buf + buflen, data, take);
      buflen += take;
      data += take;
      len -= take;
      if (buflen == 64) {
        process_block(buf);
        buflen = 0;
      }
    }
  }

  void finish(unsigned char digest[16]) {
    uint64_t bit_count = bits;
    unsigned char pad = 0x80;
    update(&pad, 1);
    unsigned char zero = 0;
    while (buflen != 56) update(&zero, 1);
    unsigned char len_bytes[8];
    for (int i = 0; i < 8; i++) len_bytes[i] = (unsigned char)(bit_count >> (i * 8));
    update(len_bytes, 8);
    uint32_t vals[4] = {a, b, c, d};
    for (int i = 0; i < 4; i++) {
      digest[i * 4] = (unsigned char)(vals[i] & 0xff);
      digest[i * 4 + 1] = (unsigned char)((vals[i] >> 8) & 0xff);
      digest[i * 4 + 2] = (unsigned char)((vals[i] >> 16) & 0xff);
      digest[i * 4 + 3] = (unsigned char)((vals[i] >> 24) & 0xff);
    }
  }
};

}  // namespace

std::string md5_hex(const std::string& data) {
  MD5Ctx ctx;
  ctx.update((const unsigned char*)data.data(), data.size());
  unsigned char digest[16];
  ctx.finish(digest);
  char out[33];
  for (int i = 0; i < 16; i++) std::snprintf(out + i * 2, 3, "%02x", digest[i]);
  return std::string(out, 32);
}

}  // namespace bili
