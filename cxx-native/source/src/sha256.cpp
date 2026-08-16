#include "sha256.h"

#include <cstdint>
#include <cstdio>
#include <cstring>

namespace bili {
namespace {

struct SHA256 {
  uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                   0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
  uint64_t bits = 0;
  unsigned char buf[64];
  size_t buflen = 0;

  static const uint32_t k[64];

  void block(const unsigned char* p) {
    uint32_t w[64];
    for (int i = 0; i < 16; i++) {
      w[i] = ((uint32_t)p[i * 4] << 24) | ((uint32_t)p[i * 4 + 1] << 16) |
             ((uint32_t)p[i * 4 + 2] << 8) | (uint32_t)p[i * 4 + 3];
    }
    for (int i = 16; i < 64; i++) {
      uint32_t s0 = ((w[i - 15] >> 7) | (w[i - 15] << 25)) ^
                    ((w[i - 15] >> 18) | (w[i - 15] << 14)) ^ (w[i - 15] >> 3);
      uint32_t s1 = ((w[i - 2] >> 17) | (w[i - 2] << 15)) ^
                    ((w[i - 2] >> 19) | (w[i - 2] << 13)) ^ (w[i - 2] >> 10);
      w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6],
             hh = h[7];
    for (int i = 0; i < 64; i++) {
      uint32_t S1 = ((e >> 6) | (e << 26)) ^ ((e >> 11) | (e << 21)) ^
                    ((e >> 25) | (e << 7));
      uint32_t ch = (e & f) ^ (~e & g);
      uint32_t temp1 = hh + S1 + ch + k[i] + w[i];
      uint32_t S0 = ((a >> 2) | (a << 30)) ^ ((a >> 13) | (a << 19)) ^
                    ((a >> 22) | (a << 10));
      uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
      uint32_t temp2 = S0 + maj;
      hh = g;
      g = f;
      f = e;
      e = d + temp1;
      d = c;
      c = b;
      b = a;
      a = temp1 + temp2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d;
    h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
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
        block(buf);
        buflen = 0;
      }
    }
  }

  void finish(unsigned char digest[32]) {
    uint64_t bit_count = bits;
    unsigned char pad = 0x80;
    update(&pad, 1);
    unsigned char zero = 0;
    while (buflen != 56) update(&zero, 1);
    unsigned char len_bytes[8];
    for (int i = 0; i < 8; i++) len_bytes[i] = (unsigned char)(bit_count >> (8 * (7 - i)));
    update(len_bytes, 8);
    for (int i = 0; i < 8; i++) {
      digest[i * 4] = (unsigned char)(h[i] >> 24);
      digest[i * 4 + 1] = (unsigned char)(h[i] >> 16);
      digest[i * 4 + 2] = (unsigned char)(h[i] >> 8);
      digest[i * 4 + 3] = (unsigned char)h[i];
    }
  }
};

const uint32_t SHA256::k[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
    0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
    0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
    0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
    0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
    0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
    0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
    0xc67178f2};

}  // namespace

std::string sha256_hex(const std::string& data) {
  SHA256 ctx;
  ctx.update((const unsigned char*)data.data(), data.size());
  unsigned char digest[32];
  ctx.finish(digest);
  char out[65];
  for (int i = 0; i < 32; i++) std::snprintf(out + i * 2, 3, "%02x", digest[i]);
  return std::string(out, 64);
}

}  // namespace bili
