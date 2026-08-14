from pathlib import Path

import pytest

from app.assets import AssetResolutionError, LocalAssetResolver
from app.manifest import build_manifest, validate_manifest
from app.models import VideoJobCreate
from app.providers import DeterministicContentProvider


def make_request() -> VideoJobCreate:
    return VideoJobCreate.model_validate({
        "topic": "3 ly do nen chu y Vinhomes Green Paradise tuan nay",
        "project": "vinhomes-green-paradise",
        "video": {"duration_seconds": 45, "aspect": "9:16", "language": "vi", "template": "real-estate-short-v1"},
        "content": {"objective": "lead_generation", "audience": "khach hang", "tone": "tin cay", "cta": "Dang ky tham quan sa ban"},
        "media": {"source": "local", "project_asset_folder": "vinhomes-green-paradise", "minimum_clips": 5, "allow_stock": False, "allow_ai_generation": False},
    })


@pytest.mark.asyncio
async def test_deterministic_assets_build_schema_valid_manifest(tmp_path: Path):
    request = make_request()
    project = tmp_path / request.media.project_asset_folder
    project.mkdir()
    for index in range(5):
        (project / f"clip-{index + 1:02d}.mp4").write_bytes(b"fixture")

    provider = DeterministicContentProvider()
    script = await provider.generate_script(request)
    storyboard = await provider.generate_storyboard(request, script)
    resolved = LocalAssetResolver(tmp_path).resolve(request, storyboard)

    manifest = build_manifest(
        request=request,
        storyboard=storyboard,
        resolved_assets=resolved,
        logo_uri="/workspace/storage/assets/brand/npd-logo.png",
    )
    schema = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "video-manifest.schema.json"
    validate_manifest(manifest, schema)
    assert len(manifest["scenes"]) == 6
    assert sum(scene["duration_seconds"] for scene in manifest["scenes"]) == pytest.approx(45, abs=0.1)


@pytest.mark.asyncio
async def test_asset_resolver_requires_minimum_clips(tmp_path: Path):
    request = make_request()
    project = tmp_path / request.media.project_asset_folder
    project.mkdir()
    (project / "only-one.mp4").write_bytes(b"fixture")
    provider = DeterministicContentProvider()
    script = await provider.generate_script(request)
    storyboard = await provider.generate_storyboard(request, script)
    with pytest.raises(AssetResolutionError):
        LocalAssetResolver(tmp_path).resolve(request, storyboard)
