from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .errors import AutovideoError


SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def make_job_id(source: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:8]
    return f"{timestamp}-{digest}"


def create_job(
    jobs_dir: str | Path,
    source: str,
    *,
    rights_confirmed: bool,
    config: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    root = Path(jobs_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    base_id = make_job_id(source)
    job_id = base_id
    suffix = 1
    while (root / job_id).exists():
        suffix += 1
        job_id = f"{base_id}-{suffix}"

    job_dir = root / job_id
    for name in ("source", "audio", "subtitles", "output", "logs"):
        (job_dir / name).mkdir(parents=True, exist_ok=True)

    now = _now()
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "id": job_id,
        "created_at": now,
        "updated_at": now,
        "state": "created",
        "input": source,
        "rights_confirmed": rights_confirmed,
        "config": dict(config),
        "paths": {},
        "history": [{"at": now, "state": "created"}],
    }
    save_job(job_dir, manifest)
    return job_dir, manifest


def load_job(job_dir: str | Path) -> dict[str, Any]:
    directory = Path(job_dir).expanduser().resolve()
    path = directory / "job.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AutovideoError(f"不是有效任务目录，缺少 job.json：{directory}") from exc
    except json.JSONDecodeError as exc:
        raise AutovideoError(f"任务记录已损坏：{path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise AutovideoError(f"不支持的任务记录格式：{path}")
    return value


def save_job(job_dir: str | Path, manifest: Mapping[str, Any]) -> None:
    directory = Path(job_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "job.json"
    temporary = directory / ".job.json.tmp"
    updated_at = _now()
    if isinstance(manifest, dict):
        manifest["updated_at"] = updated_at
    value = dict(manifest)
    value["updated_at"] = updated_at
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def set_state(
    job_dir: str | Path,
    manifest: dict[str, Any],
    state: str,
    *,
    detail: str | None = None,
) -> None:
    manifest["state"] = state
    event: dict[str, Any] = {"at": _now(), "state": state}
    if detail:
        event["detail"] = detail
    manifest.setdefault("history", []).append(event)
    save_job(job_dir, manifest)


def relative_to_job(job_dir: str | Path, path: str | Path) -> str:
    directory = Path(job_dir).expanduser().resolve()
    target = Path(path).expanduser().resolve()
    try:
        return str(target.relative_to(directory))
    except ValueError:
        return str(target)


def path_from_manifest(job_dir: str | Path, stored_path: str) -> Path:
    path = Path(stored_path)
    if path.is_absolute():
        return path
    return Path(job_dir).expanduser().resolve() / path
