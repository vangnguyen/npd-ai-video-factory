from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path

from app.assets import AssetResolutionError, LocalAssetResolver

from .pipeline import SUPPORTED_LOGO_SUFFIXES, WorkerConfig


@dataclass(frozen=True)
class PilotPreflightResult:
    project_folder: str
    asset_count: int
    logo_path: str
    asset_root: str


def validate_pilot_assets(
    config: WorkerConfig,
    *,
    project_folder: str,
    minimum_clips: int,
) -> PilotPreflightResult:
    if minimum_clips < 1:
        raise ValueError("minimum_clips must be at least 1")

    if not config.logo_path.is_file() or config.logo_path.stat().st_size <= 0:
        raise AssetResolutionError(f"required brand logo is missing or empty: {config.logo_path}")
    if config.logo_path.suffix.lower() not in SUPPORTED_LOGO_SUFFIXES:
        raise AssetResolutionError(
            f"brand logo has unsupported format: {config.logo_path.suffix or '<none>'}"
        )

    assets = LocalAssetResolver(config.asset_root).list_assets(project_folder)
    if len(assets) < minimum_clips:
        raise AssetResolutionError(
            f"expected at least {minimum_clips} local assets, found {len(assets)}"
        )

    empty = [asset.path.name for asset in assets if asset.path.stat().st_size <= 0]
    if empty:
        raise AssetResolutionError(f"empty media files: {', '.join(empty)}")

    return PilotPreflightResult(
        project_folder=project_folder,
        asset_count=len(assets),
        logo_path=str(config.logo_path),
        asset_root=str(config.asset_root),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate production pilot media and brand assets")
    parser.add_argument("--project-folder", required=True)
    parser.add_argument("--minimum-clips", type=int, default=5)
    args = parser.parse_args()

    config = WorkerConfig.from_env()
    result = validate_pilot_assets(
        config,
        project_folder=args.project_folder,
        minimum_clips=args.minimum_clips,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
