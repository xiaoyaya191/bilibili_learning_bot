# BiliLearn Android

BiliLearn 3.1.5 的 Kotlin + Jetpack Compose 原生 Android 工程。当前迁移基线是：

`G:\code\work\apk\BiliLearn-Web-3.1.5-beta-source`

本工程不是旧版 WebView 壳。功能迁移状态见 [MIGRATION_STATUS.md](MIGRATION_STATUS.md)。

## 构建环境

- JDK 17: `G:\code\work\apk\bilibili_learning_bot\_build_tools\jdk17`
- Android SDK: `G:\code\work\apk\bilibili_learning_bot\_build_tools\android-sdk`
- Gradle Wrapper: `gradlew.bat`，Gradle 8.10.2
- compileSdk / targetSdk: 35
- minSdk: 26

PowerShell 构建命令：

```powershell
$env:JAVA_HOME = 'G:\code\work\apk\bilibili_learning_bot\_build_tools\jdk17'
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
.\gradlew.bat :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleRelease
```

已验证的安装包位于：

`dist\BiliLearn-3.1.5-release.apk`

`dist\BiliLearn-3.1.5-debug.apk`

release 包使用项目本地发布证书签名。签名配置保存在被 Git 忽略的 `keystore.properties`，证书位于被 Git 忽略的 `app\bililearn-release.jks`。后续升级必须继续使用同一证书；丢失证书后无法覆盖安装已有版本。APK 校验值见 `dist\SHA256SUMS.txt`。

## 数据与配置

- 模型、人设、自动化和外观配置保存在应用私有 SharedPreferences 中。
- 知识卡片、会话与审批数据保存在 Room 数据库中。
- 自定义背景会复制到应用私有目录，避免临时文件 URI 在重启后失效。
- Android 系统备份和设备迁移包含配置、数据库、知识库镜像及背景图片。
- 非敏感配置导入不会清除 API Key、B 站 Cookie 或登录态。

卸载应用是否恢复数据仍取决于系统备份开关、Google/设备厂商备份能力及同一签名证书。需要确定性迁移时应使用应用内导出功能。

## 验证

每次交付至少运行：

```powershell
.\gradlew.bat :app:testDebugUnitTest :app:compileDebugKotlin :app:lintDebug :app:assembleDebug
```

需要生成签名 release 包时运行：

```powershell
.\gradlew.bat :app:assembleRelease
```

长视频结果必须同时匹配当前 `source_bvid` 和 `request_id` 才能写入知识库；任何身份缺失或不一致都会终止当前任务。

- 手机端 ASR 分区显示暂不支持手机端，音视频和麦克风转写请使用 Web 端。
