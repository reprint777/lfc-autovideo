from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .config import load_config, write_default_config
from .errors import AutovideoError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autovideo",
        description="本地生成英文字幕，并在人工翻译后制作中英双语成片。",
    )
    parser.add_argument("--config", help="JSON 配置文件；未指定时使用内置默认值")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("doctor", help="检查 Python、FFmpeg 和本地转写依赖")

    init_config = commands.add_parser("init-config", help="写出一份可编辑的默认配置")
    init_config.add_argument("path", nargs="?", default="config.json")
    init_config.add_argument("--force", action="store_true", help="覆盖已有配置文件")

    prepare = commands.add_parser("prepare", help="下载/导入视频并在本机转写英文")
    prepare.add_argument("source", help="YouTube URL 或本地视频路径")
    prepare.add_argument(
        "--confirm-rights",
        action="store_true",
        help="确认已取得下载、翻译和重新发布所需权利",
    )
    prepare.add_argument("--model", help="faster-whisper 模型，如 tiny.en/small.en/medium.en")
    prepare.add_argument("--device", help="本地推理设备，如 cpu/cuda/auto")
    prepare.add_argument("--compute-type", help="计算类型，如 int8/float16/default")
    prepare.add_argument("--jobs-dir", help="任务输出根目录")

    render = commands.add_parser("render", help="读取人工翻译 CSV 并生成双语成片")
    render.add_argument("job_dir", help="prepare 生成的任务目录")
    render.add_argument(
        "--allow-missing-chinese",
        action="store_true",
        help="允许部分 chinese 单元格为空",
    )

    status = commands.add_parser("status", help="查看任务状态和文件路径")
    status.add_argument("job_dir")
    return parser


def _confirm_rights(flag: bool) -> bool:
    if flag:
        return True
    if not sys.stdin.isatty():
        return False
    answer = input(
        "请确认你有权下载、翻译并重新发布该内容。输入 YES 继续："
    ).strip()
    return answer == "YES"


def _doctor() -> int:
    from .doctor import run_doctor

    checks = run_doctor()
    all_ok = True
    for check in checks:
        ok = bool(getattr(check, "ok", False))
        required = bool(getattr(check, "required", True))
        name = str(getattr(check, "name", "检查项"))
        detail = str(getattr(check, "detail", ""))
        label = "OK" if ok else ("WARN" if not required else "FAIL")
        print(f"[{label}] {name}: {detail}")
        if required and not ok:
            all_ok = False
    return 0 if all_ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            return _doctor()
        if args.command == "init-config":
            output = write_default_config(args.path, overwrite=args.force)
            print(f"已写入配置：{output}")
            return 0

        config = load_config(args.config)
        if args.command == "prepare":
            if args.model:
                config["transcription"]["model"] = args.model
            if args.device:
                config["transcription"]["device"] = args.device
            if args.compute_type:
                config["transcription"]["compute_type"] = args.compute_type
            if args.jobs_dir:
                config["jobs_dir"] = args.jobs_dir
            if not _confirm_rights(args.confirm_rights):
                raise AutovideoError(
                    "未确认内容权利，任务没有开始。请获得授权后使用 --confirm-rights。"
                )
            from .pipeline import prepare_job

            job_dir, manifest = prepare_job(
                args.source,
                config,
                rights_confirmed=True,
            )
            print(f"任务已准备完成：{manifest['id']}")
            print(f"英文字幕：{job_dir / 'subtitles' / 'transcript.en.srt'}")
            print(f"请填写中文列：{job_dir / 'subtitles' / 'translation.csv'}")
            print(f"填写后运行：autovideo render {json.dumps(str(job_dir), ensure_ascii=False)}")
            return 0
        if args.command == "render":
            from .pipeline import render_job

            # With no explicit config, rendering uses the snapshot stored by prepare.
            render_config = config if args.config else None
            output, _manifest, missing = render_job(
                args.job_dir,
                render_config,
                allow_missing_chinese=args.allow_missing_chinese,
            )
            print(f"双语成片：{output}")
            if missing:
                print(f"注意：有 {missing} 条字幕只有英文。")
            return 0
        if args.command == "status":
            from .job import load_job

            manifest = load_job(Path(args.job_dir))
            summary = {
                "id": manifest.get("id"),
                "state": manifest.get("state"),
                "updated_at": manifest.get("updated_at"),
                "paths": manifest.get("paths", {}),
                "transcription": manifest.get("transcription", {}),
                "translation": manifest.get("translation", {}),
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0
        parser.error("未知命令")
    except AutovideoError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
