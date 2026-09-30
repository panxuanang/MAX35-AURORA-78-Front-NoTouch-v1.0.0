# MAX35 AURORA · 78 Upstream · Front Camera · No Touch

面向硬件：**SpotPear / 斑梨 `ESP32S3-MAX35-LCD-FCamera-Case`（前摄像头、无触摸、带外壳）**。

本仓库不是一份冻结的小智源码，而是一个可重复构建的“产品层”：GitHub Actions 每次拉取 `78/xiaozhi-esp32`，再导入 SpotPear MAX35 硬件层，并叠加本项目的 AURORA UI。这样小智的 Application / Audio / Protocol / MCP / Wi-Fi 等核心逻辑仍来自 78 上游。

## 这版做了什么

- **前摄像头固定 270° 旋转**，不是旧后摄项目的 90°。
- **无触摸设计**：不加入触摸快门、不修改 `mcp_server.cc`，拍照/视觉能力保持当前 78 原生流程。
- **全新 AURORA UI**：深色玻璃感主页 + 独立对话页。
- 一进入语音对话，自动从主页切到对话页。
- 用户转写在上方保留上下文，小智回答占据主要显示区域。
- 回答自动换行；如果内容超过可视高度，先停留约 1.6 秒，然后缓慢上移，直到最后一行完整显示。
- 回答读完并回到 Idle 后再延迟返回主页，避免长回答还没看完就跳走。
- 摄像头预览仍使用当前 78 原生 `SetPreviewImage`，显示预览时 AURORA 覆盖层自动隐藏，预览结束后恢复。
- GitHub Actions 最终生成 **从 `0x0` 地址直接烧录的 merged binary**。

## 与旧后摄 STELLAR 项目的关系

旧仓库只作为交互参考。本项目没有复制它的天气、Todo、触摸快门、后摄预览页或额外 MCP 工具。

保留的交互原则只有：

1. 对话开始自动进入独立聊天页面；
2. 长回答使用真正的自动换行；
3. 超长回答按照文本实际高度计算滚动距离，并以较慢速度展示到末尾；
4. 阅读完成后再回主页。

## 目录结构

```text
.github/workflows/build-max35-front.yml
scripts/find_source_root.py
scripts/import_max35_front_to_78.py
scripts/preflight.py
overlay/main/display/aurora_max35/
  aurora_max35_display.h
  aurora_max35_display.cc
  ui_pages.h
  ui_home.cc
  ui_chat.cc
VERSION
MANIFEST.txt
UPLOAD_GUIDE_CN.txt
```

## 最简单的使用方法

### 1. 新建 GitHub 仓库

把本压缩包里的**所有内容**上传到仓库根目录，注意 `.github` 目录也必须上传。

### 2. 运行 GitHub Actions

进入：

`Actions → Build MAX35 AURORA Front NoTouch → Run workflow`

`upstream_ref` 默认保持 `main` 即可。

### 3. 下载固件

构建成功后，在该次 Workflow 页面底部下载 artifact：

`MAX35-AURORA-Front-NoTouch-Firmware`

其中最重要的是：

```text
MAX35_AURORA_FRONT_<版本>_merged-binary.bin
```

它的烧录地址是：

```text
0x0
```

## 首次烧录建议

你之前遇到过热点找不到或连接不上的情况，所以这台前摄机器第一次切换到本固件时，建议**先整片擦除 Flash，再烧 merged binary**，避免旧 NVS、旧分区和旧 Wi-Fi 配置残留。

使用 esptool 时大致流程：

```bash
esptool.py --chip esp32s3 erase_flash
esptool.py --chip esp32s3 --baud 460800 write_flash 0x0 MAX35_AURORA_FRONT_<版本>_merged-binary.bin
```

具体串口名称由你的电脑决定。

## 摄像头说明

本项目当前构建目标固定为：

```text
GC0308
DVP
YUV422 / YUYV
640x480 @ 16fps
Front camera rotation: 270°
```

这是为了让构建和启动行为确定，不在开机时探测多个摄像头型号。

如果你的实际前摄模组是 **OV5640 500 万像素**，请不要直接把“摄像头打不开”当作硬件故障；需要把构建目标改为 OV5640。SpotPear 官方资料同时列出了 GC0308 与 OV5640 的编译选项，因此传感器必须和实际模组一致。

## UI 参数

主要参数在：

```text
overlay/main/display/aurora_max35/aurora_max35_display.cc
```

当前值：

```cpp
kScrollDelayMs = 1600;       // 长回答开始滚动前先停留
kScrollMsPerPixel = 78;      // 数值越大滚动越慢
kReturnHomeDelayUs = 4500000; // 普通回答结束后的主页返回延迟
kAfterScrollDelayUs = 2000000; // 长回答滚完后继续停留
```

视觉布局分别在：

```text
ui_home.cc
ui_chat.cc
```

改 UI 时尽量只改这两个文件；不要去改音频、协议或 MCP。

## 架构原则

```text
78/xiaozhi-esp32
  ├─ Application      原样
  ├─ AudioService     原样
  ├─ Protocol         原样
  ├─ Wi-Fi/配网       原样
  ├─ MCP              原样
  ├─ Camera tool      原样
  └─ Display
       └─ AURORA MAX35 UI   本仓库覆盖

SpotPear vendor source
  └─ MAX35 GPIO / LCD / ES8311 / power / DVP camera wiring
```

导入脚本只做当前 78 / ESP-IDF 6 所需要的两项硬件兼容迁移：

- SpotPear 老的 `Esp32Camera(video_config)` → 当前 78 的 `EspVideo(video_config)`；
- IDF 5 老 `driver/adc.h` → IDF 6 `adc_oneshot` 兼容层。

## 出错时先看哪里

如果 Actions 红了，打开失败步骤，把从第一个 `ERROR:` / `fatal error:` 开始的日志保存下来。

如果固件能烧但热点不稳定，USB 串口用 `115200` 查看是否反复出现 boot/reset、`Guru Meditation`、`assert failed` 或 `ESP_ERROR_CHECK failed`。热点“偶尔出现、马上消失”通常比单纯 UI 问题更像设备在重启。

---

版本：见 `VERSION`。
