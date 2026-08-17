from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import AutovideoError
from .job import (
    create_job,
    load_job,
    path_from_manifest,
    relative_to_job,
    save_job,
    set_state,
)
from .render import render_video
from .subtitles import (
    cue_source_digest,
    read_translation_csv,
    write_ass,
    write_bilingual_srt,
    write_srt,
    write_translation_csv,
)
from .transcribe import transcribe_local


def _subtitle_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    style = config["subtitles"]
    return {
        "font_name": style["font_name"],
        "font_size": int(style["chinese_font_size"]),
        "english_font_size": int(style["english_font_size"]),
        "margin_v": int(style["margin_vertical"]),
        "outline": float(style["outline"]),
        "shadow": float(style["shadow"]),
    }


def prepare_job(
    source_value: str,
    config: dict[str, Any],
    *,
    rights_confirmed: bool,
) -> tuple[Path, dict[str, Any]]:
    """Prepare a source, transcribe it locally, and export manual-translation files."""

    if not rights_confirmed:
        raise AutovideoError("必须先确认你有权下载、翻译和重新发布该内容。")

    # Heavy/optional source dependencies are imported only for this command.
    from .media import extract_audio
    from .sources import prepare_source, resolve_source

    spec = resolve_source(source_value)
    job_dir, manifest = create_job(
        config["jobs_dir"],
        source_value,
        rights_confirmed=True,
        config=config,
    )

    try:
        set_state(job_dir, manifest, "preparing_source")
        video_path, source_metadata = prepare_source(
            spec,
            job_dir,
            max_height=int(config["download"]["max_height"]),
        )
        manifest["source"] = source_metadata
        manifest["paths"]["source_video"] = relative_to_job(job_dir, video_path)
        save_job(job_dir, manifest)

        set_state(job_dir, manifest, "extracting_audio")
        audio_path = job_dir / "audio" / "speech.m4a"
        extract_audio(video_path, audio_path)
        manifest["paths"]["audio"] = relative_to_job(job_dir, audio_path)
        save_job(job_dir, manifest)

        set_state(job_dir, manifest, "transcribing")
        transcription = config["transcription"]
        cues, info = transcribe_local(
            audio_path,
            model_size=str(transcription["model"]),
            device=str(transcription["device"]),
            compute_type=str(transcription["compute_type"]),
            language=str(transcription["language"]) if transcription.get("language") else None,
            initial_prompt=(
                str(transcription["initial_prompt"])
                if transcription.get("initial_prompt")
                else None
            ),
            beam_size=int(transcription["beam_size"]),
            vad_filter=bool(transcription["vad_filter"]),
            max_chars=int(transcription["max_chars"]),
            max_duration=float(transcription["max_duration"]),
        )
        if not cues:
            raise AutovideoError("没有识别到英文语音，未生成字幕。请检查音轨或更换模型。")

        subtitle_dir = job_dir / "subtitles"
        english_srt = write_srt(cues, subtitle_dir / "transcript.en.srt")
        translation_csv = write_translation_csv(cues, subtitle_dir / "translation.csv")
        bilingual_srt = write_bilingual_srt(
            cues, subtitle_dir / "subtitle.bilingual.srt"
        )
        bilingual_ass = write_ass(
            cues,
            subtitle_dir / "subtitle.bilingual.ass",
            **_subtitle_kwargs(config),
        )

        manifest["transcription"] = {
            **info,
            "cue_count": len(cues),
            "cue_source_sha256": cue_source_digest(cues),
        }
        manifest["paths"].update(
            {
                "english_srt": relative_to_job(job_dir, english_srt),
                "translation_csv": relative_to_job(job_dir, translation_csv),
                "bilingual_srt": relative_to_job(job_dir, bilingual_srt),
                "bilingual_ass": relative_to_job(job_dir, bilingual_ass),
            }
        )
        set_state(job_dir, manifest, "waiting_for_translation")
        return job_dir, manifest
    except (KeyboardInterrupt, SystemExit):
        set_state(job_dir, manifest, "interrupted")
        raise
    except Exception as exc:
        set_state(job_dir, manifest, "failed", detail=str(exc))
        if isinstance(exc, AutovideoError):
            raise
        raise AutovideoError(str(exc)) from exc


def render_job(
    job_dir_value: str | Path,
    config: dict[str, Any] | None = None,
    *,
    allow_missing_chinese: bool = False,
) -> tuple[Path, dict[str, Any], int]:
    """Read the manually translated CSV and render a bilingual MP4."""

    job_dir = Path(job_dir_value).expanduser().resolve()
    manifest = load_job(job_dir)
    effective_config = config or manifest.get("config")
    if not isinstance(effective_config, dict):
        raise AutovideoError("任务缺少有效配置，请通过 --config 指定配置文件。")

    failure_state = "translation_needs_attention"
    try:
        translation_path = path_from_manifest(
            job_dir,
            manifest["paths"].get(
                "translation_csv", "subtitles/translation.csv"
            ),
        )
        try:
            cues = read_translation_csv(translation_path)
        except FileNotFoundError as exc:
            raise AutovideoError(f"找不到人工翻译文件：{translation_path}") from exc
        except ValueError as exc:
            raise AutovideoError(str(exc)) from exc

        expected_count = manifest.get("transcription", {}).get("cue_count")
        if isinstance(expected_count, int) and len(cues) != expected_count:
            raise AutovideoError(
                f"translation.csv 应有 {expected_count} 行字幕，实际为 {len(cues)} 行。"
                "请恢复 prepare 生成的原始行数，只编辑 chinese 列。"
            )
        expected_digest = manifest.get("transcription", {}).get("cue_source_sha256")
        if isinstance(expected_digest, str) and cue_source_digest(cues) != expected_digest:
            raise AutovideoError(
                "translation.csv 的时间轴或英文原文已被修改。"
                "请恢复 prepare 生成的文件，只编辑 chinese 列。"
            )

        missing = sum(1 for cue in cues if cue.english.strip() and not cue.chinese.strip())
        if missing and not allow_missing_chinese:
            failure_state = "waiting_for_translation"
            raise AutovideoError(
                f"还有 {missing} 行没有中文翻译。填写 translation.csv 的 chinese 列后重试；"
                "若确实需要部分英文字幕，可加 --allow-missing-chinese。"
            )

        failure_state = "failed"
        set_state(job_dir, manifest, "building_bilingual_subtitles")
        subtitle_dir = job_dir / "subtitles"
        bilingual_srt = write_bilingual_srt(
            cues, subtitle_dir / "subtitle.bilingual.srt"
        )
        bilingual_ass = write_ass(
            cues,
            subtitle_dir / "subtitle.bilingual.ass",
            **_subtitle_kwargs(effective_config),
        )
        manifest["paths"]["bilingual_srt"] = relative_to_job(job_dir, bilingual_srt)
        manifest["paths"]["bilingual_ass"] = relative_to_job(job_dir, bilingual_ass)
        save_job(job_dir, manifest)

        source_path = path_from_manifest(job_dir, manifest["paths"]["source_video"])
        output_path = job_dir / "output" / "final.bilingual.mp4"
        set_state(job_dir, manifest, "rendering")
        render_video(
            source_path,
            bilingual_ass,
            output_path,
            effective_config["render"],
        )
        manifest["paths"]["final_video"] = relative_to_job(job_dir, output_path)
        manifest["translation"] = {
            "cue_count": len(cues),
            "missing_chinese": missing,
        }
        set_state(job_dir, manifest, "completed")
        return output_path, manifest, missing
    except (KeyboardInterrupt, SystemExit):
        set_state(job_dir, manifest, "interrupted")
        raise
    except Exception as exc:
        set_state(job_dir, manifest, failure_state, detail=str(exc))
        if isinstance(exc, AutovideoError):
            raise
        raise AutovideoError(str(exc)) from exc
