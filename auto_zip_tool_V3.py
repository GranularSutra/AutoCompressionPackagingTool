#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
自动压缩打包工具 v3.0
用法：将文件/文件夹拖拽到这个脚本上，自动生成带北京时间时间戳的 zip 压缩包。

v3.0 修复点：
- 大文件/多文件实时进度条（文件数 + 字节 + 百分比），避免“看起来卡死”
- 标准输出强制即时刷新，不再被块缓冲静默
- 先扫描统计文件清单与总大小，再分块压缩
- Ctrl+C 中断时自动清理半成品压缩包
- 跳过符号链接和无权限文件，避免卡在循环链接上
"""

import os
import sys
import zipfile
from datetime import datetime, timedelta, timezone

CHUNK_SIZE = 1024 * 1024  # 1MB，分块读写，进度按块更新
BEIJING_TZ = timezone(timedelta(hours=8))
# 压缩级别：1 最快/体积稍大，9 最慢/体积最小；大文件建议保持 6
COMPRESS_LEVEL = 6


def log(msg=""):
    """即时输出，避免被块缓冲吞掉。"""
    print(msg, flush=True)


def get_timestamp():
    """北京时间（UTC+8）时间戳：年月日时分秒。"""
    return datetime.now(BEIJING_TZ).strftime("%Y%m%d%H%M%S")


def human_size(num):
    """把字节数转成易读格式。"""
    n = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


def make_unique_path(path):
    """同名压缩包已存在时追加序号，避免覆盖。"""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    idx = 1
    while True:
        candidate = f"{base}_{idx}{ext}"
        if not os.path.exists(candidate):
            return candidate
        idx += 1


def get_zip_path(original_path):
    parent = os.path.dirname(os.path.abspath(original_path))
    base_name = os.path.basename(original_path)
    name_without_ext = os.path.splitext(base_name)[0]
    zip_name = f"{name_without_ext}_{get_timestamp()}.zip"
    return make_unique_path(os.path.join(parent, zip_name))


def scan_folder(folder_path):
    """第一遍扫描：收集文件清单、总大小，记录被跳过的项。"""
    entries = []
    total_size = 0
    skipped = []

    for root, _dirs, files in os.walk(folder_path):
        for file in files:
            full_path = os.path.join(root, file)
            if os.path.islink(full_path):
                skipped.append(full_path)
                continue
            try:
                size = os.path.getsize(full_path)
            except OSError as e:
                skipped.append(f"{full_path}（{e}）")
                continue
            arcname = os.path.relpath(full_path, folder_path)
            entries.append((full_path, arcname, size))
            total_size += size

    return entries, total_size, skipped


def render_bar(done, total, prefix="", width=36):
    """在同一行刷新进度条。"""
    percent = (done / total * 100) if total > 0 else 0.0
    filled = int(width * done / total) if total > 0 else 0
    bar = "█" * filled + "░" * (width - filled)
    line = f"{prefix} [{bar}] {percent:5.1f}%  {human_size(done)}/{human_size(total)}"
    sys.stdout.write("\r" + line.ljust(110))
    sys.stdout.flush()


def write_file_to_zip(zf, file_path, arcname, size, done_bytes, total_bytes, label):
    """分块写入单个文件，并按累计字节更新总体进度条。"""
    zinfo = zipfile.ZipInfo.from_file(file_path, arcname)
    zinfo.compress_type = zipfile.ZIP_DEFLATED

    copied = 0
    with zf.open(zinfo, mode="w") as zout, open(file_path, "rb") as fin:
        while True:
            chunk = fin.read(CHUNK_SIZE)
            if not chunk:
                break
            zout.write(chunk)
            copied += len(chunk)
            render_bar(done_bytes + copied, total_bytes, prefix=label)

    return size


def zip_file(file_path, zip_path):
    """压缩单个文件（带字节级进度）。"""
    size = os.path.getsize(file_path)
    with zipfile.ZipFile(
        zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=COMPRESS_LEVEL
    ) as zf:
        write_file_to_zip(
            zf,
            file_path,
            os.path.basename(file_path),
            size,
            0,
            size,
            label="📄",
        )
    sys.stdout.write("\n")
    sys.stdout.flush()


def zip_folder(folder_path, zip_path):
    """压缩整个文件夹（带文件数 + 总体字节进度）。"""
    entries, total_size, skipped = scan_folder(folder_path)

    for item in skipped:
        log(f"⚠️  跳过: {item}")

    if not entries:
        log("⚠️  文件夹内没有可压缩的文件")
        return

    total_files = len(entries)
    done_bytes = 0

    with zipfile.ZipFile(
        zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=COMPRESS_LEVEL
    ) as zf:
        for idx, (full_path, arcname, size) in enumerate(entries, 1):
            label = f"📁 {idx}/{total_files}"
            try:
                write_file_to_zip(
                    zf, full_path, arcname, size,
                    done_bytes, total_size, label,
                )
            except Exception as e:
                sys.stdout.write("\n")
                log(f"❌ 文件失败: {arcname}（{e}）")
            done_bytes += size

    sys.stdout.write("\n")
    sys.stdout.flush()


def remove_partial(zip_path):
    if os.path.exists(zip_path):
        try:
            os.remove(zip_path)
        except OSError:
            pass


def process_path(path):
    """处理单个路径：压缩文件或文件夹。"""
    if not os.path.exists(path):
        log(f"❌ 路径不存在: {path}")
        return False

    zip_path = get_zip_path(path)

    try:
        if os.path.isfile(path):
            log(f"📄 正在压缩文件: {os.path.basename(path)}")
            zip_file(path, zip_path)
        elif os.path.isdir(path):
            log(f"📁 正在压缩文件夹: {os.path.basename(path)}")
            zip_folder(path, zip_path)
        else:
            log(f"❌ 不支持的路径类型: {path}")
            return False

        log(f"✅ 压缩成功: {zip_path}")
        log(f"📊 压缩包大小: {human_size(os.path.getsize(zip_path))}")
        return True

    except KeyboardInterrupt:
        log("\n⏹  已中断，清理半成品压缩包...")
        remove_partial(zip_path)
        raise
    except Exception as e:
        log(f"❌ 压缩失败: {e}")
        remove_partial(zip_path)
        return False


def pause():
    """等待回车；非交互环境（无 stdin）下直接返回，不报错。"""
    try:
        input("\n按 Enter 键退出...")
    except (EOFError, OSError):
        pass


def main():
    # 尽量把输出切到行缓冲，防止拖拽运行时被块缓冲静默
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    log("=" * 50)
    log("🔧 自动压缩打包工具 v3.0（北京时间）")
    log("=" * 50)

    if len(sys.argv) < 2:
        log("❌ 请将文件或文件夹拖拽到此脚本上运行")
        log("💡 提示：支持同时拖拽多个文件/文件夹")
        pause()
        sys.exit(1)

    paths = sys.argv[1:]
    success_count = 0

    try:
        for i, path in enumerate(paths, 1):
            log(f"\n📦 处理第 {i}/{len(paths)} 个项目:")
            if process_path(path):
                success_count += 1
    except KeyboardInterrupt:
        log("\n⏹  用户中断。")
        pause()
        sys.exit(1)

    log("\n" + "=" * 50)
    log(f"📊 处理完成: 成功 {success_count}/{len(paths)} 个")
    log("=" * 50)

    if success_count < len(paths):
        pause()
    else:
        log("\n✨ 全部处理成功！")
        pause()


if __name__ == "__main__":
    main()
#（注：内容由AI生成）
