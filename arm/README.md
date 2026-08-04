# ARM64 安装与构建说明

这个目录解决“ARM Python 环境不好装依赖”的问题：在这台 x86 开发机上把依赖的
aarch64 编译产物全部准备好，塞进仓库，ARM 设备（Termux / ARM Linux）直接离线安装。

## 目录结构

- `requirements-arm64-wheels.txt` 顶层依赖（有预编译 wheel 的部分）
- `requirements-arm64-sdist.txt` 只有 sdist 的纯 Python 包
- `requirements-arm64.txt` 顶层完整依赖（在线安装用）
- `requirements-arm64-resolved.txt` pip 解析后的精确版本锁
- `build_arm_wheels.py` 在本机生成 ARM64 wheelhouse
- `wheelhouse/` 生成产物，提交到仓库
- `install_arm.sh` ARM 设备安装/运行脚本

## 在开发机（x86）生成 ARM64 wheelhouse

```bash
python arm/build_arm_wheels.py --python 312
```

默认从清华 PyPI 镜像下载 manylinux aarch64 预编译轮子：

- PyYAML / Pillow / pydantic-core / lxml / brotli / yarl / reportlab 等 C 扩展包
  都有官方 aarch64 wheel，无需 ARM 交叉编译器。
- `qrcode-terminal` 只有 sdist（纯 Python），安装时由设备端 pip 现场构建，
  不需要 clang。
- 如果某个包没有 aarch64 wheel，脚本会明确报错并提示用
  `docker buildx build --platform linux/arm64` 补构建。

产物目录 `arm/wheelhouse/` 直接提交到仓库，ARM 端就不需要联网装依赖。

## 在 ARM 设备安装并运行

```bash
# 把仓库放到手机上（git clone / 压缩包）
cd bilibili_learning_bot

# 只安装依赖
bash arm/install_arm.sh

# 安装并启动 Web 面板
bash arm/install_arm.sh web

# 安装并启动机器人菜单
bash arm/install_arm.sh bot

# 安装后把 .venv + wheelhouse 打包成单个 tar.gz
bash arm/install_arm.sh pack
```

Termux 会自动执行 `pkg install python ffmpeg libyaml ...`；
Debian/Ubuntu 自动执行 `apt-get install ...`。

脚本会在项目根目录创建 `.venv` 虚拟环境，依赖全部装进 `.venv`，
Web/bot 都用 `.venv/bin/python` 启动，不污染系统 Python。

## 为什么不需要整机 QEMU

- 依赖产物已经是 aarch64 原生 wheel，运行速度接近原生，不需要 x86 模拟。
- 只有 `qrcode-terminal` 是纯 Python sdist，设备端 pip 直接构建，毫秒级完成。
- 这台开发机只负责“准备产物”，ARM 设备只负责“安装+运行”。
