from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from .models import VideoJobCreate
from .providers import StoryboardResult


SUPPORTED_ASSET_SUFFIXES = {".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png"}


class AssetResolutionError(RuntimeError):
    pass


class ResolvedAsset(BaseModel):
    id: str
    path: Path
    media_type: str


class ResolvedSceneAsset(BaseModel):
    scene_id: str
    asset: ResolvedAsset


class LocalAssetResolver:
    def __init__(self, asset_root: Path):
        self.asset_root = asset_root.resolve()

    def _project_folder(self, project_folder: str) -> Path:
        candidate = (self.asset_root / project_folder).resolve()
        if candidate.parent != self.asset_root:
            raise AssetResolutionError("project asset folder escaped asset root")
        return candidate

    def list_assets(self, project_folder: str) -> list[ResolvedAsset]:
        folder = self._project_folder(project_folder)
        if not folder.is_dir():
            raise AssetResolutionError("project asset folder does not exist")
        paths = sorted(
            path for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_ASSET_SUFFIXES
        )
        assets: list[ResolvedAsset] = []
        for index, path in enumerate(paths, start=1):
            media_type = "image" if path.suffix.lower() in {".jpg", ".jpeg", ".png"} else "video"
            assets.append(ResolvedAsset(id=f"asset_{index:03d}", path=path.resolve(), media_type=media_type))
        return assets

    def resolve(self, request: VideoJobCreate, storyboard: StoryboardResult) -> list[ResolvedSceneAsset]:
        assets = self.list_assets(request.media.project_asset_folder)
        if len(assets) < request.media.minimum_clips:
            raise AssetResolutionError(
                f"expected at least {request.media.minimum_clips} local assets, found {len(assets)}"
            )
        return [
            ResolvedSceneAsset(scene_id=scene.id, asset=assets[index % len(assets)])
            for index, scene in enumerate(storyboard.scenes)
        ]
