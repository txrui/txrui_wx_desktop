# txrui_wx_desktop

`txrui_wx_desktop` 是独立运行的 Windows 微信桌面连接器，通过窗口截图、光学字符识别（OCR）和鼠标键盘操作收发消息，并通过 WebSocket 将微信接入消息服务端。项目包含本地网页控制台、视觉区域标定、会话过滤和媒体诊断工具。

支持两种服务端连接目标：

- **core**：支持 Connector 1.0 协议的消息服务端，默认地址为 `ws://127.0.0.1:8000/api/v1/connector/ws`。
- **AstrBot**：运行 `astrbot_plugin_txrui` 插件的 AstrBot 实例，默认地址为 `ws://127.0.0.1:8788`。

客户端通过网络协议与服务端交互，无需导入服务端 Python 模块。这里的“账号标识”和“连接器标识”是协议配置字段，不代表客户端能够读取微信内部账号或消息数据库。

## 运行要求

- Windows 桌面环境，Python 3.11 或更高版本。
- 微信 PC 客户端已登录，主窗口可被识别和操作。
- 可连接的 core 或 AstrBot 服务端，以及对应连接令牌。
- 桌面窗口依赖 pywebview；Windows 上通常还需要可用的 WebView2 运行环境。缺少 pywebview 时程序保留本地 HTTP 服务，可使用浏览器访问。
- 首次使用 OCR 时，需要确保 RapidOCR 的模型资源可用。

本项目会操作真实微信窗口并使用系统剪贴板。建议在专用桌面环境运行，避免采集和发送期间手动切换会话、移动窗口或覆盖剪贴板。

## 快速启动

在 PowerShell 或命令提示符中执行：

```bat
cd txrui_wx_desktop
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy config.toml.example config.toml
python run.py
```

随后完成以下步骤：

1. 登录微信并打开主窗口。
2. 在控制台“设置”中选择服务端，填写 WebSocket 地址、连接器标识、账号标识和令牌。
3. 使用连接测试确认服务端配置，再点击“启动采集”。
4. 用另一个账号发送测试消息，检查控制台事件和服务端接收结果。

本地控制台默认地址为 `http://127.0.0.1:17880/`。默认启动过程会检查微信窗口、应用窗口尺寸及缩放设置，但不会自动开始采集。

### 启动方式

```bat
python run.py
python run.py --debug
python run.py --headless
```

- 默认模式提供桌面控制台和托盘。关闭桌面窗口会隐藏到托盘，托盘“退出”菜单用于结束运行。
- `--debug` 为桌面网页窗口开启开发者工具。
- `--headless` 直接启动采集和 WebSocket 连接，不提供控制台，但仍然依赖已登录的 Windows 桌面和微信窗口。

**无界面模式的发送能力与控制台模式不同**：当前 `run.py` 仅为无界面模式绑定文本发送回调；控制台模式使用 `Runtime`，另行绑定媒体发送回调和会话复验逻辑。需要媒体下行时使用默认模式，并先进行实际收发测试。

## Windows EXE 启动器

构建好的启动器位于 `dist\txrui\txrui.exe`。双击即可打开控制台，目标电脑无需安装 Python，但仍需要 Windows 桌面、微信和 Microsoft Edge WebView2 运行环境。

请复制或分发**整个 `dist\txrui` 目录**，包括 `_internal` 子目录，不能只复制 EXE。建议放在当前用户有写入权限的目录，不要放在 `Program Files` 下。

- 桌面窗口、系统托盘和 EXE 均使用 `logo.png` 品牌图标；构建脚本自动生成带多尺寸图像的 Windows ICO。
- 首次运行自动从空令牌示例生成 EXE 同目录的 `config.toml`，随后在控制台设置连接信息。
- 视觉标定保存为 EXE 同目录的 `regions.json`；运行日志位于 `logs\txrui.log`。
- 默认关闭窗口后隐藏到托盘，使用托盘菜单“退出”结束程序。
- 支持 `txrui.exe --debug` 和 `txrui.exe --headless`；无界面模式日志同样写入 `logs`。
- `txrui.exe --self-test` 检查网页资源、配置路径及 OCR 初始化，不操作微信；成功后生成 `self-test.json`，进程返回码为 0。
- 升级时保留自己的 `config.toml` 和 `regions.json`，整体替换程序及 `_internal` 资源。

### 从源码重新构建

在 Windows、Python 3.11+ 环境执行：

```bat
python -m pip install -r requirements-build.txt
python build_exe.py
```

也可在安装依赖后双击 `build_exe.bat`。构建前会初始化 OCR，并在需要时下载模型；模型、网页及运行依赖一并打包。构建不会复制开发机器的实际令牌和视觉标定。重复构建会清理并覆盖输出目录，自己的配置请另行备份。

## 配置

主配置文件为 `config.toml`，示例见 `config.toml.example`。读取优先级为：非空环境变量、配置文件、程序默认值。空环境变量不会覆盖文件配置。

### 连接 core

```toml
[core]
ws_url = "ws://127.0.0.1:8000/api/v1/connector/ws"
connector_id = "txrui_001"
connector_token = "<服务端签发的令牌>"
account_id = "wx_001"

[astrbot]
enabled = "0"
```

令牌签发、账号绑定和会话授权由服务端管理。若部署使用相应管理接口，可在服务端完成连接器令牌签发、微信账号绑定和会话放行，再启动客户端。

### 连接 AstrBot

先在 AstrBot 中安装并启用 `astrbot_plugin_txrui`，然后配置：

```toml
[core]
connector_id = "txrui_001"
account_id = "wx_001"

[astrbot]
enabled = "1"
ws_url = "ws://127.0.0.1:8788"
token = "<与插件一致的令牌>"
```

两种模式共用 `[core]` 中的 `connector_id` 和 `account_id`。AstrBot 令牌为空时使用 `core.connector_token`。切换后需重新启动采集，使连接使用新配置。

AstrBot 下行媒体仅通过 WebSocket `media_fetch` 获取；core 模式还会尝试 HTTP 下载作为后备方式。HTTP 下载能否成功取决于部署的接口和权限，客户端令牌不保证具备媒体下载权限。

### 采集、控制台和媒体配置

- `[collect]`：`poll_sec` 是轮询间隔，默认 2 秒；`heartbeat_sec` 是心跳间隔，默认 25 秒。
- `[web]`：`host` 和 `port` 控制本地 HTTP 服务，默认 `127.0.0.1:17880`。
- `[filter]`：`extra` 为逗号分隔的扩展拦截词，`allow` 为优先放行词。
- `[media]`：`asr_endpoint` 为可选语音识别服务地址；`wechat_file_dirs` 为微信文件搜索目录。

对应环境变量包括 `CORE_WS_URL`、`CONNECTOR_ID`、`CONNECTOR_TOKEN`、`WECHAT_ACCOUNT_ID`、`POLL_SEC`、`HEARTBEAT_SEC`、`WEB_HOST`、`WEB_PORT`、`FILTER_EXTRA`、`FILTER_ALLOW`、`ASR_ENDPOINT`、`WECHAT_FILE_DIRS`、`ASTRBOT_ENABLED`、`ASTRBOT_WS_URL` 和 `ASTRBOT_TOKEN`。

当前文件定位模块直接读取 `WECHAT_FILE_DIRS` 环境变量。控制台保存目录配置时也会更新该变量；仅手动编辑 TOML 后启动时，建议显式设置环境变量并通过文件诊断确认搜索路径。

配置保存后会刷新模块配置，但已建立的网络连接、监听端口和运行任务不会全部自动重建。修改地址、令牌、监听配置后，应重新启动对应采集任务或程序。

## 采集与发送流程

1. 使用 Win32 `PrintWindow` 获取微信整窗图像，应用窗口 DPI 缩放及区域配置。
2. 在会话区通过颜色和连通域识别未读红点，切换会话并检查选中状态。
3. 对标题区和消息区执行 OCR，解析会话名、群人数、消息文本及归属。
4. 检测媒体气泡，并尝试读取媒体内容或生成截图。
5. 应用会话过滤、自身消息排除和时间窗口去重，将消息组织为事件。
6. 通过 WebSocket 上传媒体并上报事件，接收下行指令后操作微信发送。
7. 处理完成后尝试点击输入框清除当前会话未读标记。

下行文本和媒体在控制台运行模式中会先切换目标会话，再校验标题及可识别的会话类型。视觉识别仍可能失败；发送回执表示客户端操作结果，不等同于微信服务端送达确认。

## 消息与媒体能力

以下描述以控制台运行模式为主，具体结果受微信版本、窗口布局和本机依赖影响。

- **文本**：接收使用 OCR；发送通过剪贴板粘贴，再按配置使用回车、Ctrl+Enter 或发送按钮提交。
- **图片**：优先打开查看器并使用 Ctrl+C 获取图片内容，失败时尝试裁剪气泡截图。发送使用剪贴板文件。
- **文件**：按显示文件名在候选目录搜索本体，并结合文件创建时间选择候选文件。找不到时保留占位信息；发送前需从服务端取回文件内容。
- **视频**：接收当前只获取气泡缩略图，不获取视频本体。发送按文件处理。当前上报路径仍使用视频类型及 `video/mp4` 元数据，即使内容实际为缩略图，接收方不能据此认为取得了可播放视频。
- **表情**：通过截图保留当前帧，不能保证获得动画或原始表情文件。上报使用文本段并附加 `extra.emoji` 标记。
- **语音**：可读取微信自动转文字的文本，并尝试按时间窗口搜索最近的音频缓存；时间匹配无法保证音频归属。可选语音识别服务使用 multipart 的 `file` 字段接收文件，并返回纯文本或包含 `text` 字段的 JSON。
- **语音发送**：提供依赖 VB-CABLE、`sounddevice`、`soundfile` 和 `pycaw` 的可选录音发送实现，需正确配置虚拟声卡和微信录音操作。协议能力声明当前固定为 `audio=False`，常规媒体下行按文件发送，不应视为已启用原生语音消息。
- **撤回**：尝试按消息内容定位后，使用右键菜单执行撤回。客户端没有稳定微信消息 ID，重复内容可能定位错误，也无法绕过微信自身撤回限制。

媒体内容获取或上传失败时使用占位信息，通常带有 `extra.placeholder=True`，不会虚构成功上传的 `media_id`。媒体上传大小上限为 20 MiB。可选依赖存在只说明具备尝试条件，不保证实际微信操作成功。

## 控制台与视觉标定

主导航包括“总览”“事件”“拦截过滤”“设置”“调试”和“日志”。前端定时读取运行状态，展示连接、计数、最近事件和错误信息。

调试功能包括窗口截图、OCR 文本框、标题解析、未读红点、媒体气泡、去重、文件目录、语音环境和发送检查。可在“媒体能力”相关操作中检查本机依赖以及协议能力声明；读取状态、能力检查和气泡检测本身不会发送消息。实际发送测试会操作真实会话，请仔细核对目标。

视觉配置保存在 `regions.json`，与包含令牌的主配置分开：

- 支持会话区、消息区和标题区的手动边界。
- 支持输入区域、点击位置、颜色、检测阈值及发送触发方式等参数。
- 手动区域和点位使用相对整窗的归一化坐标；其他阈值的单位以编辑器提示为准。
- 默认会尝试自动检测分隔线和边界；手动覆盖可用于当前布局识别不准确的情况。
- 当前格式支持 `version`、`regions` 和 `visual`，同时可读取仅含三区域的文件。

连接时默认尝试将微信窗口调整为 1500×1000，并根据显示器 DPI 选择缩放档位。这些行为可在视觉设置中调整。完成标定后应重新预览截图，确认标题没有混入消息区、输入区域没有覆盖消息正文。

## 会话过滤

内置规则用于过滤微信团队、微信支付、服务通知、订阅号消息、文件传输助手等会话，也包含公众号、服务号及相关关键词规则。

匹配前会处理部分 OCR 空格和引号变体。`filter.allow` 优先于拦截规则，`filter.extra` 用于扩展拦截词。采集侧跳过被拦截的会话并尝试清除未读；控制台运行模式的文本下行也检查过滤规则。

过滤规则是客户端处理策略，不代替服务端授权。不同下行发送路径的校验范围并不完全相同，媒体操作仍需使用可信服务端并进行目标会话检查。

## 协议与可靠性边界

客户端使用 Connector 1.0 消息帧，主要包括 `hello`、`hello_ack`、`heartbeat`、`event`、`ack`、`media_upload`、`media_ack`、`media_fetch`、`media_fetch_ack`、`outbound` 和 `send_ack`。

- 微信消息没有稳定远程 ID，`platform_message_id` 为空。事件使用消息位置、文本摘要及指纹参与去重。指纹默认保留 120 秒；客户端序号记录仅按容量裁剪，不随该时间窗口过期，因此相同序号可能在更长时间内被判重。
- 上行事件队列默认最多保存 500 项，仅存在内存中；满队列会丢弃最旧项，进程退出会丢失队列。
- 当前没有基于事件确认的持久化重试机制。未读标记清除后不能依赖自动重读恢复未送达事件。
- 下行在当前进程中按 `request_id` 缓存处理结果，默认最多保留 500 项。重启或缓存淘汰后不保证同一指令不会再次执行。
- OCR 可能误认文本、群人数或会话名，消息位置也会随滚动和窗口变化而变化。客户端不提供完整历史同步、稳定引用映射或严格的一次性投递保证。
- 图片回退截图、表情当前帧和视频缩略图都不等同于原始媒体。服务端应结合实际内容处理，不能仅凭段类型推断媒体完整性。

## 目录说明

```text
txrui_wx_desktop/
  run.py                  启动入口与无界面运行流程
  config.toml.example     不含实际令牌的配置示例
  regions.json            当前视觉区域和参数配置
  requirements.txt        Python 运行依赖
  webui/                  控制台页面、样式、接口封装和区域编辑器
  tests/                  Python 回归测试及区域编辑器 JavaScript 测试
  txrui/
    config.py             配置读取、环境变量覆盖和原子保存
    capture.py            窗口发现、DPI、窗口调整和截图
    regions.py            自动区域计算、标题及会话类型解析
    region_settings.py    手动区域和视觉配置持久化
    visual_settings.py    视觉参数定义、校验与读取
    scale.py              DPI 档位和基准像素换算
    badge.py              未读红点检测
    ocr.py                RapidOCR 初始化和文本清理
    message_layout.py     消息归属、文字框和媒体框关联
    backend.py            微信窗口读取、会话切换与消息识别
    media.py              媒体气泡检测和裁剪
    media_vision.py       媒体图像连通域及边界分析
    media_grab.py         图片复制、屏幕裁剪和文件定位
    voice.py              语音时长、转写、缓存和识别服务支持
    voice_send.py         可选虚拟声卡录音发送
    sender.py             文本与媒体文件发送操作
    recall.py             按内容定位并尝试撤回
    filters.py            会话过滤
    dedup.py              时间窗口去重和指纹
    payload.py            消息段与入站事件构造
    collector.py          未读轮询、媒体上传和事件入队
    ws_client.py          WebSocket 连接、协议帧与回执
    runtime.py            控制台模式的后台线程和发送回调
    state.py              线程安全状态、计数和日志
    webbridge.py          控制台操作与诊断接口
    webserver.py          本地 HTTP 服务
    web.py                桌面窗口与托盘生命周期
```

## 测试

在项目目录执行：

```bat
python -m pip install pytest
python -m pytest tests/ -q
node --test tests/test_region_editor.cjs
```

JavaScript 测试需要安装 Node.js。自动化测试大量使用模拟对象，不能代替真实微信环境中的窗口截图、会话切换、媒体获取和发送验收。

## 安全与使用注意事项

- `config.toml` 中令牌以明文保存，应避免提交、截图公开或复制到日志中。
- 本地控制台默认只监听回环地址。HTTP 操作接口没有独立的登录认证，包含配置和发送等敏感能力，应限制为可信本机访问。
- AstrBot 插件也应设置连接令牌；跨机器连接时限制防火墙来源，并按部署条件使用加密连接。
- 截图、OCR 结果、日志和服务端事件可能含有聊天隐私，分享排障材料前应脱敏。
- 本项目依赖微信桌面界面，微信升级、主题、缩放或布局变化都可能影响识别。请遵守相关平台规则，并在获授权的账号和会话范围内使用。
