#!/usr/bin/env python3
from pathlib import Path
import json
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: preflight.py <78-xiaozhi-root>")

root = Path(sys.argv[1]).resolve()
main = root / "main"
board = main / "boards" / "spotpear" / "max35-front"
ui = main / "display" / "aurora_max35"

required = [
    root / "scripts" / "build.py",
    main / "application.cc",
    main / "audio" / "audio_service.cc",
    main / "mcp_server.cc",
    ui / "aurora_max35_display.h",
    ui / "aurora_max35_display.cc",
    ui / "ui_pages.h",
    ui / "ui_home.cc",
    ui / "ui_chat.cc",
    board / "config.json",
]
for path in required:
    if not path.exists():
        raise SystemExit(f"missing required file: {path}")
    print("[OK]", path.relative_to(root))

cfg = json.loads((board / "config.json").read_text(encoding="utf-8"))
if cfg.get("manufacturer") != "spotpear" or cfg.get("type") != "max35-front" or cfg.get("target") != "esp32s3":
    raise SystemExit("invalid MAX35 front board identity")
builds = cfg.get("builds") or []
if len(builds) != 1 or builds[0].get("name") != "max35-front-gc0308":
    raise SystemExit("expected exactly one MAX35 front GC0308 build variant")
opts = builds[0].get("sdkconfig_append") or []
joined = "\n".join(opts)
for token in (
    "CONFIG_BOARD_TYPE_SPOTPEAR_MAX35_FRONT=y",
    "CONFIG_ESP_VIDEO_ENABLE_DVP_VIDEO_DEVICE=y",
    "CONFIG_CAMERA_GC0308=y",
    "CONFIG_CAMERA_GC0308_AUTO_DETECT_DVP_INTERFACE_SENSOR=y",
    "CONFIG_CAMERA_GC0308_DVP_YUV422_YUYV_640X480_16FPS=y",
    "CONFIG_CAMERA_OV2640=n",
    "CONFIG_CAMERA_OV5640=n",
    "CONFIG_XIAOZHI_ENABLE_ROTATE_CAMERA_IMAGE=y",
    "CONFIG_XIAOZHI_CAMERA_IMAGE_ROTATION_ANGLE_270=y",
):
    if token not in joined:
        raise SystemExit(f"missing front-camera option: {token}")
if "CONFIG_XIAOZHI_CAMERA_IMAGE_ROTATION_ANGLE_90=y" in joined:
    raise SystemExit("rear-camera 90-degree rotation leaked into front build")
print("[OK] front camera is GC0308 + YUYV + 270-degree rotation")

kconfig = (main / "Kconfig.projbuild").read_text(encoding="utf-8", errors="ignore")
if not re.search(r"(?m)^\s*config\s+BOARD_TYPE_SPOTPEAR_MAX35_FRONT\s*$", kconfig):
    raise SystemExit("MAX35 front Kconfig board registration missing")
cmake = (main / "CMakeLists.txt").read_text(encoding="utf-8", errors="ignore")
if 'set(BOARD_DIR "spotpear/max35-front")' not in cmake:
    raise SystemExit("MAX35 front BOARD_DIR registration missing")
for src in ("aurora_max35_display.cc", "ui_home.cc", "ui_chat.cc"):
    if src not in cmake:
        raise SystemExit(f"AURORA CMake source missing: {src}")
print("[OK] current 78 build system knows MAX35 front + AURORA UI")

board_blob = "\n".join(
    path.read_text(encoding="utf-8", errors="ignore")
    for path in board.rglob("*")
    if path.is_file() and path.suffix.lower() in {".c", ".cc", ".cpp", ".h", ".hpp"}
)
if "AuroraMax35Display" not in board_blob:
    raise SystemExit("vendor board display was not attached to AuroraMax35Display")

old_cam_include = re.compile(r'#\s*include\s*[<"](?:boards/common/)?esp32_camera\.h[>"]')
old_cam_ctor = re.compile(r"new\s+Esp32Camera\s*\(\s*video_config\s*\)")
old_cam_member = re.compile(r"\bEsp32Camera\s*\*\s*camera_\b")
dvp_sources = []
for path in board.rglob("*"):
    if not path.is_file() or path.suffix.lower() not in {".h", ".hpp", ".cc", ".cpp"}:
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not any(token in text for token in (
        "esp_video_init_config_t",
        "esp_video_init_dvp_config_t",
        "esp_video_init_sccb_config_t",
        "esp_cam_ctlr_dvp_pin_config_t",
    )):
        continue
    dvp_sources.append((path, text))
    if old_cam_include.search(text):
        raise SystemExit(f"old esp32_camera.h wrapper include remains: {path}")
    if old_cam_ctor.search(text):
        raise SystemExit(f"old Esp32Camera(video_config) remains: {path}")
    if old_cam_member.search(text):
        raise SystemExit(f"old Esp32Camera* camera_ remains: {path}")
    if '#include "esp_video.h"' not in text:
        raise SystemExit(f"DVP source does not include current esp_video.h: {path}")
if not dvp_sources:
    raise SystemExit("no MAX35 DVP camera source found after import")
dvp_blob = "\n".join(text for _, text in dvp_sources)
if "new EspVideo(video_config)" not in dvp_blob:
    raise SystemExit("MAX35 DVP source does not instantiate EspVideo(video_config)")
print("[OK] MAX35 camera uses current 78 EspVideo wrapper")

legacy_adc = re.compile(r'#\s*include\s*[<"](?:driver/adc\.h|driver/deprecated/driver/adc\.h)[>"]')
if legacy_adc.search(board_blob):
    raise SystemExit("legacy driver/adc.h remains in imported MAX35 board")
shim = board / "legacy_adc_compat.h"
if not shim.exists():
    raise SystemExit("MAX35 IDF6 ADC compatibility shim missing")
for token in ("adc_oneshot_new_unit", "adc_oneshot_config_channel", "adc_oneshot_read"):
    if token not in shim.read_text(encoding="utf-8", errors="ignore"):
        raise SystemExit(f"MAX35 ADC shim incomplete: {token}")
print("[OK] IDF6 ADC compatibility installed")

# Critical product rule: unlike the rear-camera STELLAR repository, this project
# must not patch the native MCP camera tool or wait for a touch shutter.
mcp = (main / "mcp_server.cc").read_text(encoding="utf-8", errors="ignore")
for forbidden in (
    "WaitForTouchShutter",
    "WaitForCameraConsent",
    "stellar_max35::RegisterProductTools",
    "aurora_max35::WaitForCameraConsent",
):
    if forbidden in mcp:
        raise SystemExit(f"unexpected product MCP/touch patch present: {forbidden}")
print("[OK] upstream MCP camera path is untouched; no touch-shutter dependency")

chat = (ui / "ui_chat.cc").read_text(encoding="utf-8", errors="ignore")
for token in (
    "LV_LABEL_LONG_WRAP",
    "ChatUiStartReadableScroll",
    "lv_anim_set_delay",
    "lv_anim_set_duration",
):
    if token not in chat:
        raise SystemExit(f"long-answer UI behavior missing: {token}")
print("[OK] chat page wraps long answers and performs delayed readable scrolling")

print("[done] MAX35 AURORA front/no-touch preflight passed")
