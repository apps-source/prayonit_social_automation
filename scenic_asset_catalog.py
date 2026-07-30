"""Version-controlled metadata catalog for long-form scenic videos.

The production renderer remains independent from this catalog. Creative
orchestration may load it through the dedicated scenic selector.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "creative" / "video_assets.json"
DEFAULT_VIDEO_DIR = PROJECT_ROOT / "assets" / "videos" / "long"
DEFAULT_CATEGORY_PATH = PROJECT_ROOT / "creative" / "prayer_categories.json"
DEFAULT_DIAGNOSTIC_DIR = (
    PROJECT_ROOT / "output" / "validation" / "sprint3b_asset_catalog"
)
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}

SCENE_TYPES = {
    "mountains",
    "river",
    "waterfall",
    "ocean",
    "lake",
    "forest",
    "field",
    "clouds",
    "city",
    "home",
    "path",
    "hands",
    "people",
    "abstract_nature",
    "other",
}
TIMES_OF_DAY = {"morning", "day", "sunset", "evening", "night", "neutral"}
EMOTIONAL_AFFINITIES = {
    "calming",
    "hopeful",
    "reflective",
    "comforting",
    "strong",
    "uplifting",
    "peaceful",
    "protective",
    "neutral",
}
ENERGY_LEVELS = {"low", "medium", "high"}
REQUIRED_ASSET_FIELDS = {
    "asset_id",
    "filename",
    "scene_type",
    "time_of_day",
    "emotional_affinity",
    "category_affinity",
    "energy_level",
    "visual_family",
    "duplicate_group",
    "contains_people",
    "enabled",
    "notes",
}


class CatalogValidationError(ValueError):
    """Raised when catalog data cannot safely describe the current library."""


def list_eligible_video_filenames(video_dir: Path = DEFAULT_VIDEO_DIR) -> List[str]:
    directory = Path(video_dir)
    if not directory.exists():
        return []
    return sorted(
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
    )


def load_canonical_category_ids(
    category_path: Path = DEFAULT_CATEGORY_PATH,
) -> set[str]:
    try:
        data = json.loads(Path(category_path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogValidationError(
            f"Prayer category configuration is missing: {category_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise CatalogValidationError(
            f"Prayer category configuration is malformed: {exc}"
        ) from exc
    if not isinstance(data, list):
        raise CatalogValidationError("Prayer category configuration must be a list.")
    return {
        str(category.get("id", "")).strip()
        for category in data
        if isinstance(category, dict) and str(category.get("id", "")).strip()
    }


def load_catalog(catalog_path: Path = DEFAULT_CATALOG_PATH) -> Dict[str, Any]:
    path = Path(catalog_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogValidationError(f"Scenic asset catalog is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogValidationError(
            f"Scenic asset catalog is malformed: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise CatalogValidationError("Scenic asset catalog root must be an object.")
    if not isinstance(data.get("assets"), list):
        raise CatalogValidationError("Scenic asset catalog must contain an assets list.")
    return data


def _validate_controlled_values(
    *,
    asset_id: str,
    field_name: str,
    values: Any,
    allowed_values: Iterable[str],
    errors: List[str],
) -> None:
    if not isinstance(values, list):
        errors.append(f"{asset_id}: {field_name} must be a list.")
        return
    invalid = sorted(
        {
            repr(value)
            for value in values
            if not isinstance(value, str) or value not in allowed_values
        }
    )
    if invalid:
        errors.append(
            f"{asset_id}: {field_name} contains unsupported values: "
            + ", ".join(invalid)
        )


def validate_catalog(
    catalog: Dict[str, Any],
    *,
    video_dir: Path = DEFAULT_VIDEO_DIR,
    category_path: Path = DEFAULT_CATEGORY_PATH,
) -> None:
    assets = catalog.get("assets")
    if not isinstance(assets, list):
        raise CatalogValidationError("Scenic asset catalog must contain an assets list.")

    errors: List[str] = []
    category_ids = load_canonical_category_ids(category_path)
    eligible_filenames = set(list_eligible_video_filenames(video_dir))
    seen_ids: set[str] = set()
    seen_filenames: set[str] = set()
    duplicate_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for index, asset in enumerate(assets):
        label = f"asset[{index}]"
        if not isinstance(asset, dict):
            errors.append(f"{label}: entry must be an object.")
            continue
        missing_fields = sorted(REQUIRED_ASSET_FIELDS - set(asset))
        if missing_fields:
            errors.append(f"{label}: missing fields: {', '.join(missing_fields)}")
            continue

        raw_asset_id = asset.get("asset_id")
        raw_filename = asset.get("filename")
        asset_id = raw_asset_id.strip() if isinstance(raw_asset_id, str) else ""
        filename = raw_filename.strip() if isinstance(raw_filename, str) else ""
        label = asset_id or label
        if not isinstance(raw_asset_id, str):
            errors.append(f"{label}: asset_id must be a string.")
        elif not asset_id:
            errors.append(f"{label}: asset_id must be nonblank.")
        elif asset_id in seen_ids:
            errors.append(f"{label}: duplicate asset_id.")
        seen_ids.add(asset_id)

        if not isinstance(raw_filename, str):
            errors.append(f"{label}: filename must be a string.")
        elif not filename:
            errors.append(f"{label}: filename must be nonblank.")
        elif (
            Path(filename).is_absolute()
            or "/" in filename
            or "\\" in filename
            or filename != Path(filename).name
        ):
            errors.append(
                f"{label}: filename must be a repository-relative basename, not a path."
            )
        elif filename in seen_filenames:
            errors.append(f"{label}: duplicate filename entry: {filename}")
        seen_filenames.add(filename)

        _validate_controlled_values(
            asset_id=label,
            field_name="scene_type",
            values=asset.get("scene_type"),
            allowed_values=SCENE_TYPES,
            errors=errors,
        )
        _validate_controlled_values(
            asset_id=label,
            field_name="time_of_day",
            values=asset.get("time_of_day"),
            allowed_values=TIMES_OF_DAY,
            errors=errors,
        )
        _validate_controlled_values(
            asset_id=label,
            field_name="emotional_affinity",
            values=asset.get("emotional_affinity"),
            allowed_values=EMOTIONAL_AFFINITIES,
            errors=errors,
        )
        _validate_controlled_values(
            asset_id=label,
            field_name="category_affinity",
            values=asset.get("category_affinity"),
            allowed_values=category_ids,
            errors=errors,
        )

        if asset.get("energy_level") not in ENERGY_LEVELS:
            errors.append(
                f"{label}: unsupported energy_level: {asset.get('energy_level')!r}"
            )
        if not isinstance(asset.get("contains_people"), bool):
            errors.append(f"{label}: contains_people must be a boolean.")
        if not isinstance(asset.get("enabled"), bool):
            errors.append(f"{label}: enabled must be a boolean.")
        if not isinstance(asset.get("notes"), str):
            errors.append(f"{label}: notes must be a string.")

        for field_name, value in asset.items():
            strings = value if isinstance(value, list) else [value]
            for candidate in strings:
                if not isinstance(candidate, str):
                    continue
                if Path(candidate).is_absolute() or PureWindowsPath(candidate).is_absolute():
                    errors.append(
                        f"{label}: {field_name} must not contain an absolute filesystem path."
                    )

        visual_family = asset.get("visual_family")
        if not isinstance(visual_family, str) or not visual_family.strip():
            errors.append(f"{label}: visual_family must be a nonblank string.")

        duplicate_group = asset.get("duplicate_group")
        if duplicate_group is not None:
            if not isinstance(duplicate_group, str) or not duplicate_group.strip():
                errors.append(
                    f"{label}: duplicate_group must be null or a nonblank string."
                )
            else:
                duplicate_groups[duplicate_group].append(asset)

    missing_entries = sorted(eligible_filenames - seen_filenames)
    extra_entries = sorted(seen_filenames - eligible_filenames)
    if missing_entries:
        errors.append("Eligible videos missing from catalog: " + ", ".join(missing_entries))
    if extra_entries:
        errors.append("Catalog entries missing from video library: " + ", ".join(extra_entries))

    for group_id, members in sorted(duplicate_groups.items()):
        if len(members) < 2:
            errors.append(
                f"Duplicate group {group_id!r} must contain at least two assets."
            )
        families = {
            str(member.get("visual_family", "")).strip() for member in members
        }
        if len(families) != 1:
            errors.append(
                f"Duplicate group {group_id!r} spans multiple visual families."
            )

    if errors:
        raise CatalogValidationError(
            "Scenic asset catalog validation failed:\n- " + "\n- ".join(errors)
        )


def summarize_catalog(
    catalog: Dict[str, Any],
    *,
    video_dir: Path = DEFAULT_VIDEO_DIR,
) -> Dict[str, Any]:
    assets = catalog["assets"]

    def count_values(field_name: str) -> Dict[str, int]:
        counts = Counter(
            value
            for asset in assets
            for value in asset.get(field_name, [])
        )
        return dict(sorted(counts.items()))

    uncertainty_markers = (
        "uncertain",
        "unknown",
        "not encoded",
        "truncated",
        "no dedicated",
        "not in the initial",
        "exact type",
    )
    uncertain_assets = sorted(
        asset["asset_id"]
        for asset in assets
        if any(
            marker in asset.get("notes", "").lower()
            for marker in uncertainty_markers
        )
        or not asset.get("scene_type")
        or not asset.get("time_of_day")
        or not asset.get("emotional_affinity")
        or "other" in asset.get("scene_type", [])
    )
    return {
        "status": "valid",
        "catalog_version": str(catalog.get("catalog_version", "")),
        "total_eligible_videos": len(list_eligible_video_filenames(video_dir)),
        "total_catalog_entries": len(assets),
        "enabled_count": sum(asset["enabled"] for asset in assets),
        "disabled_count": sum(not asset["enabled"] for asset in assets),
        "scene_type_counts": count_values("scene_type"),
        "time_of_day_counts": count_values("time_of_day"),
        "emotional_affinity_counts": count_values("emotional_affinity"),
        "visual_family_count": len(
            {asset["visual_family"] for asset in assets}
        ),
        "duplicate_group_count": len(
            {
                asset["duplicate_group"]
                for asset in assets
                if asset["duplicate_group"] is not None
            }
        ),
        "assets_with_people": sum(asset["contains_people"] for asset in assets),
        "uncertain_or_incomplete_count": len(uncertain_assets),
        "uncertain_or_incomplete_assets": uncertain_assets,
    }


def _summary_text(summary: Dict[str, Any]) -> str:
    if summary.get("status") != "valid":
        return "Sprint 3B scenic asset catalog: INVALID\n" + "\n".join(
            summary.get("errors", [])
        )

    lines = [
        "Sprint 3B Scenic Asset Catalog",
        f"Eligible videos: {summary['total_eligible_videos']}",
        f"Catalog entries: {summary['total_catalog_entries']}",
        f"Enabled: {summary['enabled_count']}",
        f"Disabled: {summary['disabled_count']}",
        f"Visual families: {summary['visual_family_count']}",
        f"Duplicate groups: {summary['duplicate_group_count']}",
        f"Assets with people: {summary['assets_with_people']}",
        f"Uncertain/incomplete: {summary['uncertain_or_incomplete_count']}",
        "",
        "Scene types:",
        json.dumps(summary["scene_type_counts"], indent=2, sort_keys=True),
        "",
        "Time of day:",
        json.dumps(summary["time_of_day_counts"], indent=2, sort_keys=True),
        "",
        "Emotional affinity:",
        json.dumps(
            summary["emotional_affinity_counts"], indent=2, sort_keys=True
        ),
        "",
        "Uncertain/incomplete assets:",
        *summary["uncertain_or_incomplete_assets"],
    ]
    return "\n".join(lines) + "\n"


def write_diagnostic_summary(
    *,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    video_dir: Path = DEFAULT_VIDEO_DIR,
    category_path: Path = DEFAULT_CATEGORY_PATH,
    output_dir: Path = DEFAULT_DIAGNOSTIC_DIR,
) -> Dict[str, Any]:
    try:
        catalog = load_catalog(catalog_path)
        validate_catalog(
            catalog,
            video_dir=video_dir,
            category_path=category_path,
        )
        summary = summarize_catalog(catalog, video_dir=video_dir)
    except CatalogValidationError as exc:
        summary = {"status": "invalid", "errors": [str(exc)]}

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "catalog_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / "catalog_summary.txt").write_text(
        _summary_text(summary),
        encoding="utf-8",
    )
    return summary


if __name__ == "__main__":
    result = write_diagnostic_summary()
    print(_summary_text(result), end="")
    raise SystemExit(0 if result.get("status") == "valid" else 1)
