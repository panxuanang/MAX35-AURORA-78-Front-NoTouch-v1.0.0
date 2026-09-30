#!/usr/bin/env python3
"""Import SpotPear MAX35 hardware into current 78/xiaozhi-esp32.

Architecture rule:
- 78/xiaozhi owns Application / AudioService / Protocol / MCP / Wi-Fi behavior.
- SpotPear vendor source contributes only the physical MAX35 board implementation.
- This repository contributes only the AURORA LVGL presentation layer and the
  deterministic front-camera build configuration.

Unlike the older rear-camera STELLAR project, this script deliberately DOES NOT
patch mcp_server.cc and DOES NOT add a touch-shutter gate. The target SKU has no
touch panel and Xiaozhi's native camera tool flow is preserved.
"""

from pathlib import Path
import argparse
import json
import os
import re
import shutil

PRODUCT_BOARD_SYMBOL = "BOARD_TYPE_SPOTPEAR_MAX35_FRONT"
PRODUCT_BOARD_CONFIG = f"CONFIG_{PRODUCT_BOARD_SYMBOL}"
PRODUCT_BOARD_DIR = Path("spotpear/max35-front")
PRODUCT_NAME = "max35-front-gc0308"
PRODUCT_TYPE = "max35-front"
SRC_SUFFIXES = {".c", ".cc", ".cpp", ".h", ".hpp"}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def locate_vendor_board(vendor: Path) -> Path:
    boards = vendor / "main" / "boards"
    preferred = boards / "sp-esp32-s3-lcd-3.5"
    if preferred.is_dir():
        return preferred

    ranked = []
    for d in boards.rglob("*"):
        if not d.is_dir():
            continue
        files = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in SRC_SUFFIXES]
        if not files:
            continue
        blob = "\n".join(read(p) for p in files).lower()
        rel = d.relative_to(boards).as_posix().lower()
        score = 0
        for token, pts in (
            ("sp-esp32-s3-lcd-3.5", 100),
            ("spotpear", 35),
            ("gc0308", 25),
            ("esp_video_init_dvp_config_t", 25),
            ("es8311", 15),
            ("st7796", 12),
            ("3.5", 10),
            ("camera", 4),
        ):
            if token in blob or token in rel:
                score += pts
        if "ml307" in blob or "4g" in rel:
            score -= 30
        if score >= 45:
            ranked.append((score, d))

    if not ranked:
        raise SystemExit("Could not locate SpotPear MAX35 board in vendor source")
    ranked.sort(key=lambda item: (-item[0], len(str(item[1]))))
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        raise SystemExit(
            "Ambiguous SpotPear MAX35 board candidates: "
            + ", ".join(str(item[1]) for item in ranked[:4])
        )
    return ranked[0][1]


def patch_kconfig(upstream: Path) -> None:
    path = upstream / "main" / "Kconfig.projbuild"
    text = read(path)
    if re.search(rf"(?m)^\s*config\s+{PRODUCT_BOARD_SYMBOL}\s*$", text):
        return

    # Current 78 main keeps the two SpotPear boards adjacent. Insert our MAX35
    # choice immediately after the 1.54 MUMA choice, before the next board.
    anchor = re.search(
        r"(?m)^\s*config\s+BOARD_TYPE_SPOTPEAR_ESP32_S3_1_54_MUMA\s*$", text
    )
    if not anchor:
        raise SystemExit("Current 78 Kconfig SpotPear anchor not found")
    remainder = text[anchor.end():]
    next_cfg = re.search(r"(?m)^\s*config\s+BOARD_TYPE_", remainder)
    if not next_cfg:
        raise SystemExit("Could not find insertion point after SpotPear Kconfig anchor")
    pos = anchor.end() + next_cfg.start()
    block = (
        f"    config {PRODUCT_BOARD_SYMBOL}\n"
        "        bool \"SpotPear MAX35 3.5-inch Front Camera No Touch\"\n"
        "        depends on IDF_TARGET_ESP32S3\n"
    )
    text = text[:pos] + block + text[pos:]
    write(path, text)
    print("[patch] registered Kconfig board", PRODUCT_BOARD_SYMBOL)


def patch_cmake(upstream: Path) -> None:
    path = upstream / "main" / "CMakeLists.txt"
    text = read(path)

    board_block = (
        f"elseif(CONFIG_{PRODUCT_BOARD_SYMBOL})\n"
        f"    set(BOARD_DIR \"{PRODUCT_BOARD_DIR.as_posix()}\")\n"
        "    set(BUILTIN_TEXT_FONT font_noto_sans_basic_20_4)\n"
        "    set(BUILTIN_ICON_FONT font_material_symbols_20_4)\n"
        "    set(DEFAULT_EMOJI_COLLECTION noto-color-emoji_64)\n"
    )
    if f"CONFIG_{PRODUCT_BOARD_SYMBOL}" not in text:
        # Verified against current 78 main on 2026-09-30.
        anchor = "elseif(CONFIG_BOARD_TYPE_SPOTPEAR_ESP32_S3_1_54_MUMA)"
        idx = text.find(anchor)
        if idx < 0:
            raise SystemExit("Current 78 CMake SpotPear anchor not found")
        text = text[:idx] + board_block + text[idx:]
        print("[patch] registered CMake BOARD_DIR", PRODUCT_BOARD_DIR)

    sources = [
        "display/aurora_max35/aurora_max35_display.cc",
        "display/aurora_max35/ui_home.cc",
        "display/aurora_max35/ui_chat.cc",
    ]
    missing = [src for src in sources if f'"{src}"' not in text]
    if missing:
        anchor = '            "display/lcd_display.cc"'
        if anchor not in text:
            raise SystemExit("Current 78 CMake display source anchor not found")
        addition = "\n".join(f'            "{src}"' for src in missing)
        text = text.replace(anchor, anchor + "\n" + addition, 1)
        print("[patch] registered AURORA UI sources")

    write(path, text)


def create_current_config(board_dst: Path) -> None:
    # Deterministic front-camera target. SpotPear's board treats a failed camera
    # init as important, so we do not auto-probe unrelated sensors. The product
    # family/source bundle is GC0308-based and the front SKU is rotated 270 deg.
    sdk = [
        f"{PRODUCT_BOARD_CONFIG}=y",
        "CONFIG_USE_DEFAULT_MESSAGE_STYLE=y",
        "CONFIG_USE_WECHAT_MESSAGE_STYLE=n",
        "CONFIG_ESPTOOLPY_FLASHSIZE_16MB=y",
        "CONFIG_LV_FONT_MONTSERRAT_48=y",
        "CONFIG_ESP_VIDEO_ENABLE_DVP_VIDEO_DEVICE=y",
        "CONFIG_CAMERA_OV2640=n",
        "CONFIG_CAMERA_OV2640_AUTO_DETECT_DVP_INTERFACE_SENSOR=n",
        "CONFIG_CAMERA_OV5640=n",
        "CONFIG_CAMERA_OV5640_AUTO_DETECT_DVP_INTERFACE_SENSOR=n",
        "CONFIG_CAMERA_GC0308=y",
        "CONFIG_CAMERA_GC0308_AUTO_DETECT_DVP_INTERFACE_SENSOR=y",
        "CONFIG_CAMERA_GC0308_DVP_YUV422_YUYV_640X480_16FPS=y",
        "CONFIG_CAMERA_GC0308_DVP_DEFAULT_FMT_YUV422_YUYV_640X480_16FPS=y",
        "CONFIG_XIAOZHI_ENABLE_ROTATE_CAMERA_IMAGE=y",
        "CONFIG_XIAOZHI_CAMERA_IMAGE_ROTATION_ANGLE_270=y",
    ]

    custom_ota = os.environ.get("XIAOZHI_OTA_URL", "").strip()
    if custom_ota:
        if '"' in custom_ota or "\n" in custom_ota or "\r" in custom_ota:
            raise SystemExit("XIAOZHI_OTA_URL contains unsupported characters")
        sdk.append(f'CONFIG_OTA_URL="{custom_ota}"')
        print("[config] custom OTA/backend discovery URL enabled")

    cfg = {
        "manufacturer": "spotpear",
        "type": PRODUCT_TYPE,
        "target": "esp32s3",
        "builds": [{"name": PRODUCT_NAME, "sdkconfig_append": sdk}],
    }
    write(board_dst / "config.json", json.dumps(cfg, ensure_ascii=False, indent=4) + "\n")
    print("[config] wrote front-camera GC0308 config.json (270-degree rotation)")


def patch_board_display(board_dst: Path) -> None:
    include = '#include "display/aurora_max35/aurora_max35_display.h"'
    patched = False

    for path in board_dst.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".h", ".hpp", ".cc", ".cpp"}:
            continue
        text = read(path)
        original = text

        if "SpiLcdDisplay" not in text and "AuroraMax35Display" not in text:
            text = text.replace(
                "CONFIG_BOARD_TYPE_SPOTPEAR_ESP32_S3_3_5_LCD", PRODUCT_BOARD_CONFIG
            )
            if text != original:
                write(path, text)
            continue

        if include not in text:
            old_inc = '#include "display/lcd_display.h"'
            if old_inc in text:
                text = text.replace(old_inc, old_inc + "\n" + include, 1)
            else:
                text = include + "\n" + text

        text, count = re.subn(r"new\s+SpiLcdDisplay\s*\(", "new AuroraMax35Display(", text)
        if count:
            patched = True
            print("[patch] direct display construction:", path.name)

        classes = re.findall(
            r"class\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*public\s+SpiLcdDisplay", text
        )
        for cls in classes:
            text = re.sub(
                rf"class\s+{re.escape(cls)}\s*:\s*public\s+SpiLcdDisplay",
                f"class {cls} : public AuroraMax35Display",
                text,
                count=1,
            )
            text = text.replace(
                "using SpiLcdDisplay::SpiLcdDisplay;",
                "using AuroraMax35Display::AuroraMax35Display;",
            )
            text = re.sub(r":\s*SpiLcdDisplay\s*\(", ": AuroraMax35Display(", text)
            text = text.replace(
                "SpiLcdDisplay::SetupUI();", "AuroraMax35Display::SetupUI();"
            )
            patched = True
            print(f"[patch] preserved vendor {cls}, changed display base")

        text = text.replace(
            "CONFIG_BOARD_TYPE_SPOTPEAR_ESP32_S3_3_5_LCD", PRODUCT_BOARD_CONFIG
        )
        if text != original:
            write(path, text)

    if not patched:
        raise SystemExit(
            "Vendor MAX35 board has no SpiLcdDisplay construction/subclass to attach AURORA UI"
        )


def patch_max35_camera(board_dst: Path) -> None:
    """Migrate the SpotPear IDF5-era esp_video wrapper to current 78 EspVideo."""
    patched_files = 0
    migrated_ctor = 0
    migrated_member = 0
    old_include = re.compile(r'#\s*include\s*[<"](?:boards/common/)?esp32_camera\.h[>"]')
    old_ctor = re.compile(r"new\s+Esp32Camera\s*\(\s*video_config\s*\)")
    old_member = re.compile(r"\bEsp32Camera\s*\*\s*camera_\b")
    camera_sources = []

    for path in board_dst.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".h", ".hpp", ".cc", ".cpp"}:
            continue
        text = read(path)
        if not any(
            token in text
            for token in (
                "esp_video_init_config_t",
                "esp_video_init_dvp_config_t",
                "esp_video_init_sccb_config_t",
                "esp_cam_ctlr_dvp_pin_config_t",
            )
        ):
            continue

        camera_sources.append(path)
        original = text
        text, inc_count = old_include.subn('#include "esp_video.h"', text)
        if inc_count == 0 and '#include "esp_video.h"' not in text:
            match = re.search(r"(?m)^#\s*include[^\n]*$", text)
            if not match:
                raise SystemExit(f"MAX35 camera source has no include block: {path}")
            text = text[:match.end()] + '\n#include "esp_video.h"' + text[match.end():]

        text, member_count = old_member.subn("EspVideo* camera_", text)
        text, ctor_count = old_ctor.subn("new EspVideo(video_config)", text)
        migrated_member += member_count
        migrated_ctor += ctor_count

        if text != original:
            write(path, text)
            patched_files += 1
            print(f"[patch] current-78 EspVideo camera wrapper: {path.name}")

    if not camera_sources:
        raise SystemExit("MAX35 vendor board has no esp_video DVP camera source to migrate")

    for path in camera_sources:
        text = read(path)
        if old_include.search(text):
            raise SystemExit(f"old esp32_camera.h include remains in MAX35 DVP source: {path}")
        if old_ctor.search(text):
            raise SystemExit(f"old Esp32Camera(video_config) constructor remains: {path}")
        if old_member.search(text):
            raise SystemExit(f"old Esp32Camera* camera_ member remains: {path}")
        if '#include "esp_video.h"' not in text:
            raise SystemExit(f"MAX35 DVP source does not include current 78 esp_video.h: {path}")

    all_camera_text = "\n".join(read(path) for path in camera_sources)
    if "new EspVideo(video_config)" not in all_camera_text:
        raise SystemExit("MAX35 camera migration did not produce EspVideo(video_config)")
    if "EspVideo* camera_" not in all_camera_text and "EspVideo *camera_" not in all_camera_text:
        raise SystemExit("MAX35 camera migration did not produce an EspVideo camera_ member")

    print(
        "[OK] MAX35 DVP camera migrated to current 78 EspVideo "
        f"({patched_files} file(s), {migrated_member} member, {migrated_ctor} constructor)"
    )


def patch_max35_adc(board_dst: Path) -> None:
    """Redirect SpotPear's removed driver/adc.h API to IDF6 adc_oneshot."""
    shim = board_dst / "legacy_adc_compat.h"
    shim.write_text(
        r'''#pragma once
// SpotPear MAX35 legacy ADC compatibility for ESP-IDF 6.x.
#include <stdint.h>
#include "esp_adc/adc_oneshot.h"
#include "esp_err.h"

typedef adc_channel_t adc1_channel_t;
typedef adc_bitwidth_t adc_bits_width_t;
#ifndef ADC1_CHANNEL_0
#define ADC1_CHANNEL_0 ADC_CHANNEL_0
#define ADC1_CHANNEL_1 ADC_CHANNEL_1
#define ADC1_CHANNEL_2 ADC_CHANNEL_2
#define ADC1_CHANNEL_3 ADC_CHANNEL_3
#define ADC1_CHANNEL_4 ADC_CHANNEL_4
#define ADC1_CHANNEL_5 ADC_CHANNEL_5
#define ADC1_CHANNEL_6 ADC_CHANNEL_6
#define ADC1_CHANNEL_7 ADC_CHANNEL_7
#define ADC1_CHANNEL_8 ADC_CHANNEL_8
#define ADC1_CHANNEL_9 ADC_CHANNEL_9
#endif
#ifndef ADC_WIDTH_BIT_9
#define ADC_WIDTH_BIT_9  ADC_BITWIDTH_9
#define ADC_WIDTH_BIT_10 ADC_BITWIDTH_10
#define ADC_WIDTH_BIT_11 ADC_BITWIDTH_11
#define ADC_WIDTH_BIT_12 ADC_BITWIDTH_12
#endif
#ifndef ADC_ATTEN_DB_11
#define ADC_ATTEN_DB_11 ADC_ATTEN_DB_12
#endif

namespace max35_legacy_adc {
inline adc_oneshot_unit_handle_t& Unit() {
    static adc_oneshot_unit_handle_t handle = nullptr;
    return handle;
}
inline adc_bitwidth_t& Width() {
    static adc_bitwidth_t width = ADC_BITWIDTH_12;
    return width;
}
inline esp_err_t EnsureUnit() {
    if (Unit() != nullptr) return ESP_OK;
    adc_oneshot_unit_init_cfg_t cfg = {};
    cfg.unit_id = ADC_UNIT_1;
    cfg.ulp_mode = ADC_ULP_MODE_DISABLE;
    return adc_oneshot_new_unit(&cfg, &Unit());
}
}  // namespace max35_legacy_adc

static inline esp_err_t adc1_config_width(adc_bits_width_t width) {
    max35_legacy_adc::Width() = width;
    return max35_legacy_adc::EnsureUnit();
}
static inline esp_err_t adc1_config_channel_atten(adc1_channel_t channel, adc_atten_t atten) {
    esp_err_t err = max35_legacy_adc::EnsureUnit();
    if (err != ESP_OK) return err;
    adc_oneshot_chan_cfg_t cfg = {};
    cfg.atten = atten;
    cfg.bitwidth = max35_legacy_adc::Width();
    return adc_oneshot_config_channel(max35_legacy_adc::Unit(), channel, &cfg);
}
static inline int adc1_get_raw(adc1_channel_t channel) {
    if (max35_legacy_adc::EnsureUnit() != ESP_OK) return -1;
    int raw = 0;
    if (adc_oneshot_read(max35_legacy_adc::Unit(), channel, &raw) != ESP_OK) return -1;
    return raw;
}
''',
        encoding="utf-8",
    )

    changed = 0
    legacy_include = re.compile(
        r'#\s*include\s*[<"](?:driver/adc\.h|driver/deprecated/driver/adc\.h)[>"]'
    )
    for path in board_dst.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".h", ".hpp", ".c", ".cc", ".cpp"}:
            continue
        if path.name == shim.name:
            continue
        text = read(path)
        patched, count = legacy_include.subn('#include "legacy_adc_compat.h"', text)
        if count:
            write(path, patched)
            changed += count
            print(f"[patch] redirected legacy ADC include: {path} ({count})")

    if changed == 0:
        print("[adc] no legacy driver/adc.h include found; vendor board may already support IDF 6")

    board_text = "\n".join(
        read(path)
        for path in board_dst.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".h", ".hpp", ".c", ".cc", ".cpp"}
        and path.name != shim.name
    )
    if legacy_include.search(board_text):
        raise SystemExit("legacy driver/adc.h still present after MAX35 ADC compatibility patch")
    print("[OK] MAX35 legacy ADC calls are backed by adc_oneshot on IDF 6")


def copy_overlay(product: Path, upstream: Path) -> None:
    src = product / "overlay" / "main" / "display" / "aurora_max35"
    dst = upstream / "main" / "display" / "aurora_max35"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print("[copy] AURORA display overlay ->", dst)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vendor", required=True)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--product", required=True)
    args = parser.parse_args()

    vendor = Path(args.vendor).resolve()
    upstream = Path(args.upstream).resolve()
    product = Path(args.product).resolve()

    vendor_board = locate_vendor_board(vendor)
    print("[vendor] MAX35 hardware board:", vendor_board)

    board_dst = upstream / "main" / "boards" / PRODUCT_BOARD_DIR
    if board_dst.exists():
        shutil.rmtree(board_dst)
    board_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(vendor_board, board_dst)
    print("[copy] vendor board ->", board_dst)

    create_current_config(board_dst)
    copy_overlay(product, upstream)
    patch_kconfig(upstream)
    patch_cmake(upstream)
    patch_board_display(board_dst)
    patch_max35_camera(board_dst)
    patch_max35_adc(board_dst)

    # Intentionally no mcp_server.cc patch: native Xiaozhi camera/MCP stays intact.
    (upstream / ".max35_front_vendor_board_path").write_text(
        str(vendor_board) + "\n", encoding="utf-8"
    )
    print("[done] front/no-touch MAX35 imported; upstream Xiaozhi logic preserved")


if __name__ == "__main__":
    main()
