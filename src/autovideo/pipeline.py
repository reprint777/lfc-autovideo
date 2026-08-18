from __future__ import annotations

from pathlib import Path
import shutil
from datetime import datetime
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
    cue_timeline_digest,
    read_translation_csv,
    write_ass,
    write_bilingual_srt,
    write_srt,
    write_translation_csv,
)
from .transcribe import transcribe_local


def _transcription_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    transcription = config["transcription"]
    return {
        "model_size": str(transcription["model"]),
        "device": str(transcription["device"]),
        "compute_type": str(transcription["compute_type"]),
        "language": (
            str(transcription["language"]) if transcription.get("language") else None
        ),
        "initial_prompt": (
            str(transcription["initial_prompt"])
            if transcription.get("initial_prompt")
            else None
        ),
        "beam_size": int(transcription["beam_size"]),
        "vad_filter": bool(transcription["vad_filter"]),
        "vad_threshold": float(transcription["vad_threshold"]),
        "vad_min_silence_duration_ms": int(
            transcription["vad_min_silence_duration_ms"]
        ),
        "vad_speech_pad_ms": int(transcription["vad_speech_pad_ms"]),
        "condition_on_previous_text": bool(
            transcription["condition_on_previous_text"]
        ),
        "hotwords": str(transcription["hotwords"]) if transcription.get("hotwords") else None,
        "max_chars": int(transcription["max_chars"]),
        "max_duration": float(transcription["max_duration"]),
    }


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


def _write_transcription_package(
    job_dir: Path,
    manifest: dict[str, Any],
    config: dict[str, Any],
    audio_path: Path,
    cues: list[Any],
    info: dict[str, object],
) -> None:
    subtitle_dir = job_dir / "subtitles"
    english_srt = write_srt(cues, subtitle_dir / "transcript.en.srt")
    translation_csv = write_translation_csv(cues, subtitle_dir / "translation.csv")
    bilingual_srt = write_bilingual_srt(cues, subtitle_dir / "subtitle.bilingual.srt")
    bilingual_ass = write_ass(
        cues,
        subtitle_dir / "subtitle.bilingual.ass",
        **_subtitle_kwargs(config),
    )

    review_path = subtitle_dir / "transcription.review.csv"
    review_error: str | None = None
    suspicious_gaps = 0
    try:
        from .review import write_gap_review

        review_path, suspicious_gaps = write_gap_review(
            cues,
            audio_path,
            review_path,
            min_gap=float(config["transcription"]["review_gap_seconds"]),
            noise_db=float(config["transcription"]["review_silence_noise_db"]),
            silence_min_duration=float(
                config["transcription"]["review_silence_min_duration"]
            ),
        )
    except Exception as exc:  # Report generation must not discard a good transcript.
        review_error = str(exc)

    manifest["transcription"] = {
        **info,
        "cue_count": len(cues),
        "cue_timeline_sha256": cue_timeline_digest(cues),
        "suspicious_gap_count": suspicious_gaps,
    }
    if review_error:
        manifest["transcription"]["review_error"] = review_error
    manifest["paths"].update(
        {
            "english_srt": relative_to_job(job_dir, english_srt),
            "translation_csv": relative_to_job(job_dir, translation_csv),
            "bilingual_srt": relative_to_job(job_dir, bilingual_srt),
            "bilingual_ass": relative_to_job(job_dir, bilingual_ass),
        }
    )
    if review_path.is_file():
        manifest["paths"]["transcription_review"] = relative_to_job(
            job_dir, review_path
        )


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
        audio_path = job_dir / "audio" / "speech.wav"
        extract_audio(video_path, audio_path)
        manifest["paths"]["audio"] = relative_to_job(job_dir, audio_path)
        save_job(job_dir, manifest)

        set_state(job_dir, manifest, "transcribing")
        cues, info = transcribe_local(audio_path, **_transcription_kwargs(config))
        if not cues:
            raise AutovideoError("没有识别到英文语音，未生成字幕。请检查音轨或更换模型。")

        _write_transcription_package(job_dir, manifest, config, audio_path, cues, info)
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


def _backup_subtitles(job_dir: Path, manifest: dict[str, Any]) -> Path | None:
    candidates = ("translation_csv", "english_srt", "bilingual_srt", "bilingual_ass")
    existing = [
        path_from_manifest(job_dir, manifest["paths"][key])
        for key in candidates
        if manifest.get("paths", {}).get(key)
        and path_from_manifest(job_dir, manifest["paths"][key]).is_file()
    ]
    if not existing:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = job_dir / "subtitles" / "backups" / stamp
    suffix = 1
    while backup_dir.exists():
        suffix += 1
        backup_dir = job_dir / "subtitles" / "backups" / f"{stamp}-{suffix}"
    backup_dir.mkdir(parents=True)
    for source in existing:
        shutil.copy2(source, backup_dir / source.name)
    return backup_dir


def retranscribe_job(
    job_dir_value: str | Path,
    config: dict[str, Any],
) -> tuple[Path, dict[str, Any], Path | None]:
    """Re-run local transcription from a job's existing audio without downloading."""

    job_dir = Path(job_dir_value).expanduser().resolve()
    manifest = load_job(job_dir)
    audio_stored = manifest.get("paths", {}).get("audio")
    if not isinstance(audio_stored, str):
        raise AutovideoError("任务记录中没有可重新转写的音频路径。")
    audio_path = path_from_manifest(job_dir, audio_stored)
    if not audio_path.is_file():
        raise AutovideoError(f"找不到任务音频：{audio_path}")

    try:
        set_state(job_dir, manifest, "retranscribing")
        cues, info = transcribe_local(audio_path, **_transcription_kwargs(config))
        if not cues:
            raise AutovideoError("重新转写没有识别到英文语音。请检查音轨或更换模型。")
        backup_dir = _backup_subtitles(job_dir, manifest)
        manifest["config"] = config
        _write_transcription_package(job_dir, manifest, config, audio_path, cues, info)
        if backup_dir:
            manifest["paths"]["previous_subtitles"] = relative_to_job(
                job_dir, backup_dir
            )
        set_state(job_dir, manifest, "waiting_for_translation")
        return job_dir, manifest, backup_dir
    except (KeyboardInterrupt, SystemExit):
        set_state(job_dir, manifest, "interrupted")
        raise
    except Exception as exc:
        set_state(job_dir, manifest, "retranscription_failed", detail=str(exc))
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
        expected_digest = manifest.get("transcription", {}).get("cue_timeline_sha256")
        if isinstance(expected_digest, str) and cue_timeline_digest(cues) != expected_digest:
            raise AutovideoError(
                "translation.csv 的序号或时间轴已被修改。"
                "请恢复 prepare 生成的时间轴；english 和 chinese 列都允许编辑。"
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
