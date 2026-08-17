from __future__ import annotations

import importlib.metadata
import importlib.util
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def run_doctor() -> list[Check]:
    """Inspect local runtime requirements without installing or downloading anything."""

    version = sys.version_info[:3]
    checks = [
        Check(
            "python",
            version >= (3, 10),
            f"{version[0]}.{version[1]}.{version[2]} (需要 3.10+)",
        )
    ]

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    checks.append(Check("ffmpeg", ffmpeg is not None, ffmpeg or "未找到"))
    checks.append(Check("ffprobe", ffprobe is not None, ffprobe or "未找到"))

    filter_output = ""
    filter_error = ""
    if ffmpeg is not None:
        try:
            completed = subprocess.run(
                [ffmpeg, "-hide_banner", "-filters"],
                check=True,
                capture_output=True,
                text=True,
                shell=False,
            )
            filter_output = f"{completed.stdout}\n{completed.stderr}"
        except (OSError, subprocess.CalledProcessError) as exc:
            filter_error = str(exc)
    for filter_name in ("ass", "subtitles"):
        available = bool(
            filter_output
            and re.search(rf"(?m)^\s*\S+\s+{re.escape(filter_name)}\s+", filter_output)
        )
        detail = "可用" if available else (filter_error or "不可用（需要 libass）")
        checks.append(
            Check(
                f"ffmpeg_filter_{filter_name}",
                available,
                detail,
                required=(filter_name == "ass"),
            )
        )

    for module in ("yt_dlp", "faster_whisper"):
        available = _module_available(module)
        checks.append(Check(module, available, "已安装" if available else "未安装"))

    try:
        ejs_version = importlib.metadata.version("yt-dlp-ejs")
    except importlib.metadata.PackageNotFoundError:
        ejs_version = None
    checks.append(
        Check(
            "yt_dlp_ejs",
            ejs_version is not None,
            f"已安装 {ejs_version}" if ejs_version else "未安装（请安装 yt-dlp[default]）",
        )
    )

    deno = shutil.which("deno")
    deno_ok = False
    deno_detail = "未找到（YouTube 下载需要；Deno 2.3+）"
    if deno is not None:
        try:
            completed = subprocess.run(
                [deno, "--version"],
                check=True,
                capture_output=True,
                text=True,
                shell=False,
            )
            first_line = completed.stdout.splitlines()[0] if completed.stdout else ""
            match = re.search(r"\bdeno\s+(\d+)\.(\d+)\.(\d+)", first_line)
            deno_ok = bool(match and tuple(map(int, match.groups())) >= (2, 3, 0))
            deno_detail = first_line or deno
            if not deno_ok:
                deno_detail += "（需要 2.3+）"
        except (OSError, subprocess.CalledProcessError) as exc:
            deno_detail = f"无法运行：{exc}"
    checks.append(
        Check(
            "deno",
            deno_ok,
            deno_detail,
        )
    )
    return checks


def doctor_ok(checks: list[Check] | None = None) -> bool:
    return all(
        check.ok or not check.required
        for check in (checks if checks is not None else run_doctor())
    )
