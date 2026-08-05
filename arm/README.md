# ARM64 / Termux 离线安装与构建说明

这个目录解决“ARM Python 环境不好装依赖”的问题：在这台 x86 开发机上把
aarch64 的 Python 轮子、Termux 的 .deb 闭包全部提前准备好，塞进仓库，
ARM 设备（Termux）直接用本地文件安装，不需要联网。

## 目录结构

- `requirements-arm64-wheels.txt` 顶层依赖（有预编译 wheel 的部分）
- `requirements-arm64-sdist.txt` 只有 sdist 的纯 Python 包
- `requirements-arm64.txt` 顶层完整依赖（在线安装用）
- `requirements-arm64-resolved.txt` pip 解析后的精确版本锁
- `build_arm_wheels.py` 在本机生成 ARM64 Python wheelhouse
- `build_termux_offline.py` 在本机下载 Termux aarch64 .deb 依赖闭包
- `build_arm_sdists.py` 下载全部依赖源码包到 `wheelhouse-src/`（Termux 源码构建用）
- `wheelhouse/` Python 编译产物（默认 CPython 3.14，和 Termux 当前版本一致）
- `termux-debs/` Termux .deb 闭包 + 安装顺序
- `install_arm.sh` 在线/半离线安装运行脚本（自动创建 .venv）
- `install_offline.sh` 全离线安装：本地 .deb + 本地 wheel

## 生成 Python wheelhouse（开发机 x86）

```bash
python arm/build_arm_wheels.py --python 314
```

默认从清华 PyPI 镜像下载 manylinux aarch64 预编译轮子：

- PyYAML / Pillow / pydantic-core / lxml / brotli / yarl / reportlab 等 C 扩展包
  都有官方 aarch64 wheel，无需 ARM 交叉编译器。
- `qrcode-terminal` 只有 sdist（纯 Python），安装时由设备端 pip 现场构建，
  不需要 clang。
- 如果某个包没有 aarch64 wheel，脚本会明确报错并提示用
  `docker buildx build --platform linux/arm64` 补构建。
- 产物目录 `arm/wheelhouse/` 直接提交到仓库，ARM 端不需要联网装依赖。

> Termux 当前稳定源默认 Python 3.14，所以默认用 `--python 314`。
> 如果你的 Termux 还是旧 Python 3.12，用 `--python 312` 重新生成。

## 生成 Termux .deb 闭包（开发机 x86）

```bash
python arm/build_termux_offline.py
```

脚本从清华 Termux 镜像读取 aarch64 包索引，自动解析
`python / python-pip / libyaml` 的依赖闭包，下载所有 .deb 并校验 SHA256，
同时生成 `termux-debs-order.txt`（依赖在前，安装顺序）。

当前闭包约 19 个包、10.7MB，包含 Python 3.14、pip、libyaml 及系统库。
ffmpeg 不需要系统包：`imageio-ffmpeg` 的 aarch64 wheel 已自带 ARM ffmpeg。

## 在 Termux 全离线安装并运行

把仓库传到手机（含 `arm/wheelhouse/` 和 `arm/termux-debs/`），然后：

```bash
cd bilibili_learning_bot

# 全离线：先 dpkg 本地 .deb，再建 .venv 离线装 wheel
bash arm/install_offline.sh

# 全离线安装并启动 Web 面板
bash arm/install_offline.sh web

# 全离线安装并启动机器人菜单
bash arm/install_offline.sh bot
```

`install_arm.sh` 也可以单独用：

```bash
bash arm/install_arm.sh            # 创建 .venv 并安装
bash arm/install_arm.sh web        # 安装后启动 Web 面板
bash arm/install_arm.sh bot        # 安装后启动机器人
bash arm/install_arm.sh pack       # 安装后把 .venv + wheelhouse 打包
```

脚本会在项目根目录创建 `.venv` 虚拟环境，依赖全部装进 `.venv`，
Web/bot 都用 `.venv/bin/python` 启动，不污染系统 Python。

## 日志位置

- 安装脚本日志：`logs/offline-install-*.log`、`logs/arm-install-*.log`
- Python 运行时日志：`$HOME/AppData/Local/BiliLearn/Data/bot_console.log`（Termux）
- Web 面板子进程日志：`$HOME/AppData/Local/BiliLearn/Data/web_bot_runtime.log`

## 为什么不需要整机 QEMU

- 依赖产物已经是 aarch64 原生 wheel / deb，运行速度接近原生，不需要 x86 模拟。
- 只有 `qrcode-terminal` 是纯 Python sdist，设备端 pip 直接构建，毫秒级完成。
- 这台开发机只负责“准备产物”，ARM 设备只负责“安装+运行”。
