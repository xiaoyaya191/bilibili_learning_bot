# Termux / Android ARM64 构建与运行

本目录的 C++ 后端在 Termux 上不再使用静态 glibc，改用 bionic 动态链接，所有依赖都走 `.so`：

- libc / libm / libdl / liblog：Android bionic 系统库
- libcurl / libssl / libcrypto / FFmpeg：随包附带在 `lib/`
- libz：随包附带在 `lib/`，libcurl 用它解压 gzip 响应
- 网络层开启 `CURLOPT_ACCEPT_ENCODING`，并带 zlib 手动解压兜底
- 自带 `cacert.pem`，网络层自动设置 CA 证书路径，否则 HTTPS 握手会失败
- libc++_shared.so：随包附带在 `lib/`

## 直接运行预编译包

```bash
cd bilibili-learning-bot-termux-arm64
bash launch.sh
```

`launch.sh` 会自动设置 `LD_LIBRARY_PATH=./lib`，默认数据目录为 `$HOME/BiliLearn`，监听 `8080` 端口。

验证是否真的动态链接 bionic：

```bash
file lib/bili-termux-arm64
readelf -d lib/bili-termux-arm64 | grep NEEDED
ldd lib/bili-termux-arm64
```

预期输出类似：

```text
ELF 64-bit LSB pie executable, ARM aarch64
NEEDED libc++_shared.so
NEEDED libcurl.so.4
NEEDED libssl.so.3
NEEDED libcrypto.so.3
NEEDED libavformat.so.59
...
NEEDED libc.so
```

## 在 Termux 本机重新编译（推荐，能直接吃 Termux 系统库）

```bash
pkg update
pkg install -y curl libcurl openssl ffmpeg cmake make clang pkg-config
bash termux_build.sh
```

编译产物：

```text
build-termux/bili
```

运行：

```bash
./build-termux/bili -data "$HOME/BiliLearn" -web 8080 -html web_panel.html
```

Termux 本机编译的版本直接链接 `$PREFIX/lib` 里的系统 `.so`，不需要把依赖目录一起拷走。
