from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .assets import ResolvedSceneAsset
from .models import VideoJobCreate
from .providers import StoryboardResult


class ManifestValidationError(ValueError):
    pass


def build_manifest(
    *,
    request: VideoJobCreate,
    storyboard: StoryboardResult,
    resolved_assets: list[ResolvedSceneAsset],
    logo_uri: str,
    voice_uri: str | None = None,
    subtitles: list[dict] | None = None,
) -> dict:
    asset_by_scene = {item.scene_id: item.asset for item in resolved_assets}
    scenes: list[dict] = []
    for scene in storyboard.scenes:
        asset = asset_by_scene.get(scene.id)
        if asset is None:
            raise ManifestValidationError(f"missing resolved asset for {scene.id}")
        scenes.append(
            {
                "id": scene.id,
                "start_seconds": scene.start_seconds,
                "duration_seconds": scene.duration_seconds,
                "role": scene.role,
                "narration": scene.narration,
                "visual": {
                    "type": asset.media_type,
                    "uri": asset.path.as_posix(),
                    "fit": "cover",
                },
                "overlay": {"headline": scene.on_screen_text or ""},
            }
        )

    manifest: dict = {
        "version": "1.0",
        "metadata": {
            "title": request.topic,
            "project": request.project,
            "template": request.video.template,
            "duration_seconds": request.video.duration_seconds,
            "fps": 30,
            "width": 1080,
            "height": 1920,
            "language": request.video.language,
        },
        "brand": {
            "name": "Ngoc Phuong Dong",
            "logo_uri": logo_uri,
            "cta": request.content.cta,
        },
        "scenes": scenes,
        "subtitles": subtitles or [],
    }
    if voice_uri:
        manifest["voice"] = {"audio_uri": voice_uri, "gain_db": 0}
    return manifest


def validate_manifest(manifest: dict, schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=lambda error: list(error.absolute_path))
    if errors:
        messages = [f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}" for error in errors]
        raise ManifestValidationError("; ".join(messages))

    scenes = manifest.get("scenes", [])
    expected = float(manifest["metadata"]["duration_seconds"])
    actual = sum(float(scene["duration_seconds"]) for scene in scenes)
    if abs(actual - expected) > 0.1:
        raise ManifestValidationError(f"scene duration total {actual} does not match metadata duration {expected}")

    starts = [float(scene["start_seconds"]) for scene in scenes]
    if starts != sorted(starts):
        raise ManifestValidationError("scene start times are not monotonic")


def persist_manifest(manifest: dict, output_path: Path, schema_path: Path) -> Path:
    validate_manifest(manifest, schema_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
