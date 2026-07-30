"""Catalog-driven scenic selection for long-form video orchestration."""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import scenic_asset_catalog


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SELECTION_CONFIG_PATH = PROJECT_ROOT / "creative" / "scenic_selection.json"
DEFAULT_DIAGNOSTIC_DIR = (
    PROJECT_ROOT / "output" / "validation" / "sprint3c_scenic_selection"
)
WATER_SCENE_TYPES = {"ocean", "lake", "river", "waterfall"}
MORNING_TIMES = {"morning", "day"}
EVENING_TIMES = {"sunset", "evening", "night"}
NEUTRAL_TIME = "neutral"


class ScenicSelectionError(RuntimeError):
    """Base error for catalog-driven scenic selection."""


class ScenicSelectionConfigError(ScenicSelectionError):
    """Raised when scenic selection policy is missing or malformed."""


class InsufficientCompatibleAssets(ScenicSelectionError):
    """Raised when hard safety rules leave too few distinct assets."""


@dataclass(frozen=True)
class ScenicSelectionContext:
    prayer_category_id: str
    time_of_day: str
    emotional_tone: str
    scene_profile_id: str
    narration_duration_seconds: float
    content_type: str
    seed: str
    slot: str = ""
    planned_video_duration_seconds: Optional[float] = None
    recent_asset_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SelectedScenicAsset:
    asset_id: str
    filename: str
    path: Path
    visual_family: str
    duplicate_group: Optional[str]
    scene_type: Tuple[str, ...]
    time_of_day: Tuple[str, ...]
    emotional_affinity: Tuple[str, ...]
    energy_level: str
    selection_order: int
    selection_score: float
    selection_reasons: Tuple[str, ...]
    estimated_stretch_ratio: float

    def to_metadata_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "filename": self.filename,
            "visual_family": self.visual_family,
            "duplicate_group": self.duplicate_group,
            "scene_type": list(self.scene_type),
            "time_of_day": list(self.time_of_day),
            "emotional_affinity": list(self.emotional_affinity),
            "energy_level": self.energy_level,
            "selection_order": self.selection_order,
            "selection_score": self.selection_score,
            "selection_reasons": list(self.selection_reasons),
            "estimated_stretch_ratio": self.estimated_stretch_ratio,
        }


@dataclass(frozen=True)
class ScenicSelectionResult:
    selected_assets: Tuple[SelectedScenicAsset, ...]
    requested_clip_count: int
    selected_clip_count: int
    eligible_catalog_count: int
    eligible_after_hard_filters: int
    top_scored_candidates: Tuple[Dict[str, Any], ...]
    scoring_summary: Dict[str, Any]
    relaxation_steps: Tuple[str, ...]
    fallback_used: bool
    fallback_reason: Optional[str]
    hard_filter_exclusions: Dict[str, int]
    recent_use_handling: str
    warnings: Tuple[str, ...] = ()

    @property
    def paths(self) -> List[Path]:
        return [asset.path for asset in self.selected_assets]

    def to_metadata_dict(self) -> Dict[str, Any]:
        return {
            "selected_assets": [
                asset.to_metadata_dict() for asset in self.selected_assets
            ],
            "requested_clip_count": self.requested_clip_count,
            "selected_clip_count": self.selected_clip_count,
            "eligible_catalog_count": self.eligible_catalog_count,
            "eligible_after_hard_filters": self.eligible_after_hard_filters,
            "top_scored_candidates": list(self.top_scored_candidates),
            "scoring_summary": self.scoring_summary,
            "relaxation_steps": list(self.relaxation_steps),
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "hard_filter_exclusions": self.hard_filter_exclusions,
            "recent_use_handling": self.recent_use_handling,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class _ScoredAsset:
    asset: Dict[str, Any]
    path: Path
    score: float
    reasons: Tuple[str, ...]
    category_match: bool
    emotional_match: bool
    time_match: bool


def load_selection_config(
    path: Path = DEFAULT_SELECTION_CONFIG_PATH,
) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScenicSelectionConfigError(
            f"Scenic selection configuration is missing: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ScenicSelectionConfigError(
            f"Scenic selection configuration is malformed: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ScenicSelectionConfigError(
            "Scenic selection configuration root must be an object."
        )
    required = {
        "short_video_clip_count",
        "long_video_clip_count",
        "long_video_threshold_seconds",
        "max_preferred_stretch_ratio",
        "assumed_source_duration_seconds",
        "avoid_same_visual_family",
        "exclude_same_duplicate_group",
        "max_water_clips",
        "recent_use_window",
        "scoring_weights",
        "category_profiles",
        "scene_profiles",
    }
    missing = sorted(required - set(data))
    if missing:
        raise ScenicSelectionConfigError(
            "Scenic selection configuration is missing: " + ", ".join(missing)
        )
    return data


def build_selection_context(
    brief: Any,
    *,
    narration_duration_seconds: Optional[float],
    planned_video_duration_seconds: Optional[float] = None,
    recent_asset_ids: Iterable[str] = (),
) -> ScenicSelectionContext:
    duration = narration_duration_seconds
    if duration is None or duration <= 0:
        duration = float(getattr(brief, "duration_seconds", 0) or 0)
    return ScenicSelectionContext(
        prayer_category_id=str(
            getattr(brief, "prayer_category_id", "general_prayer")
            or "general_prayer"
        ),
        time_of_day=str(
            getattr(brief, "asset_time_of_day", "")
            or getattr(brief, "slot", "")
            or "neutral"
        ).lower(),
        emotional_tone=str(
            getattr(brief, "asset_emotional_tone", "")
            or getattr(brief, "normalized_emotion_id", "")
            or "neutral"
        ).lower(),
        scene_profile_id=str(
            getattr(brief, "scene_profile_id", "current_default")
            or "current_default"
        ),
        narration_duration_seconds=float(duration),
        content_type=str(getattr(brief, "content_type", "") or ""),
        seed=str(getattr(brief, "run_id", "") or "scenic-selection"),
        slot=str(getattr(brief, "slot", "") or "").lower(),
        planned_video_duration_seconds=planned_video_duration_seconds,
        recent_asset_ids=tuple(
            asset_id for asset_id in recent_asset_ids if str(asset_id).strip()
        ),
    )


def requested_clip_count(
    narration_duration_seconds: float,
    selection_config: Mapping[str, Any],
) -> int:
    if narration_duration_seconds >= float(
        selection_config["long_video_threshold_seconds"]
    ):
        return int(selection_config["long_video_clip_count"])
    return int(selection_config["short_video_clip_count"])


def _is_severe_time_conflict(
    asset_times: Sequence[str],
    context: ScenicSelectionContext,
) -> bool:
    times = set(asset_times)
    if not times or NEUTRAL_TIME in times:
        return False
    category = context.prayer_category_id
    target = context.time_of_day or context.slot
    is_morning = category == "morning_prayer" or target == "morning"
    is_night = category == "night_prayer" or target in {"evening", "night"}
    if is_morning:
        return times.issubset(EVENING_TIMES)
    if is_night:
        return times.issubset(MORNING_TIMES)
    return False


def _has_valid_selection_shape(asset: Mapping[str, Any]) -> bool:
    list_fields = (
        "scene_type",
        "time_of_day",
        "emotional_affinity",
        "category_affinity",
    )
    if any(
        not isinstance(asset.get(field_name), list)
        or any(not isinstance(value, str) for value in asset[field_name])
        for field_name in list_fields
    ):
        return False
    if not all(
        isinstance(asset.get(field_name), str)
        and str(asset[field_name]).strip()
        for field_name in (
            "asset_id",
            "filename",
            "energy_level",
            "visual_family",
        )
    ):
        return False
    if not isinstance(asset.get("enabled"), bool):
        return False
    if not isinstance(asset.get("contains_people"), bool):
        return False
    duplicate_group = asset.get("duplicate_group")
    return duplicate_group is None or (
        isinstance(duplicate_group, str) and bool(duplicate_group.strip())
    )


def _profile_for_context(
    context: ScenicSelectionContext,
    selection_config: Mapping[str, Any],
) -> Dict[str, Any]:
    category_profiles = selection_config["category_profiles"]
    category_profile = category_profiles.get(
        context.prayer_category_id,
        category_profiles.get("general_prayer", {}),
    )
    scene_profile = selection_config["scene_profiles"].get(
        context.scene_profile_id,
        selection_config["scene_profiles"].get("current_default", {}),
    )
    result = dict(category_profile)
    for key in (
        "preferred_scene_types",
        "preferred_emotions",
        "preferred_energy_levels",
    ):
        result[key] = list(
            dict.fromkeys(
                list(category_profile.get(key, []))
                + list(scene_profile.get(key, []))
            )
        )
    return result


def _score_asset(
    asset: Dict[str, Any],
    path: Path,
    context: ScenicSelectionContext,
    profile: Mapping[str, Any],
    weights: Mapping[str, Any],
) -> _ScoredAsset:
    category_affinity = set(asset["category_affinity"])
    emotions = set(asset["emotional_affinity"])
    times = set(asset["time_of_day"])
    scenes = set(asset["scene_type"])
    desired_emotions = set(profile.get("preferred_emotions", []))
    if context.emotional_tone in scenic_asset_catalog.EMOTIONAL_AFFINITIES:
        desired_emotions.add(context.emotional_tone)
    desired_times = set(profile.get("preferred_times", []))
    desired_scenes = set(profile.get("preferred_scene_types", []))
    desired_energy = set(profile.get("preferred_energy_levels", []))

    category_match = context.prayer_category_id in category_affinity
    emotional_matches = emotions & desired_emotions
    time_matches = times & desired_times
    scene_matches = scenes & desired_scenes
    score = 0.0
    reasons: List[str] = []

    if category_match:
        score += float(weights["category_affinity"])
        reasons.append("category_match")
    elif not category_affinity:
        score += float(weights["broad_usability"])
        reasons.append("broad_category_asset")

    if emotional_matches:
        score += float(weights["emotional_affinity"]) * min(
            2, len(emotional_matches)
        )
        reasons.append(
            "emotion_match:" + ",".join(sorted(emotional_matches))
        )
    elif "neutral" in emotions:
        score += float(weights["neutral_metadata"])
        reasons.append("neutral_emotion")

    if time_matches:
        score += float(weights["time_of_day"])
        reasons.append("time_match:" + ",".join(sorted(time_matches)))
    elif "neutral" in times:
        score += float(weights["neutral_metadata"])
        reasons.append("neutral_time")

    if scene_matches:
        score += float(weights["scene_type"]) * min(2, len(scene_matches))
        reasons.append("scene_match:" + ",".join(sorted(scene_matches)))

    if asset["energy_level"] in desired_energy:
        score += float(weights["energy_level"])
        reasons.append("energy_match:" + asset["energy_level"])

    people_preference = profile.get("people_preference", "allowed")
    if asset["contains_people"] and people_preference == "preferred":
        score += float(weights["people_preference"])
        reasons.append("people_preferred")
    elif asset["contains_people"] and people_preference == "discouraged":
        score += float(weights["people_distraction_penalty"])
        reasons.append("people_discouraged")

    if asset["asset_id"] in context.recent_asset_ids:
        score += float(weights["recent_use_penalty"])
        reasons.append("recent_use_penalty")

    return _ScoredAsset(
        asset=asset,
        path=path,
        score=score,
        reasons=tuple(reasons),
        category_match=category_match,
        emotional_match=bool(emotional_matches),
        time_match=bool(time_matches or "neutral" in times),
    )


def _duplicate_capacity(candidates: Sequence[_ScoredAsset]) -> int:
    represented: set[str] = set()
    for candidate in candidates:
        group = candidate.asset.get("duplicate_group")
        represented.add(
            f"group:{group}" if group else f"asset:{candidate.asset['asset_id']}"
        )
    return len(represented)


def _candidate_pool(
    candidates: Sequence[_ScoredAsset],
    *,
    context: ScenicSelectionContext,
    target_count: int,
) -> Tuple[List[_ScoredAsset], List[str]]:
    if context.prayer_category_id == "general_prayer":
        return list(candidates), []

    strict = [
        candidate
        for candidate in candidates
        if candidate.category_match and candidate.emotional_match
    ]
    pool = list(strict)
    relaxation_steps: List[str] = []

    stages = (
        (
            "relaxed_category_affinity",
            [
                candidate
                for candidate in candidates
                if candidate.emotional_match
            ],
        ),
        (
            "relaxed_emotional_affinity",
            [
                candidate
                for candidate in candidates
                if candidate.category_match
            ],
        ),
        (
            "broadened_neutral_assets",
            [
                candidate
                for candidate in candidates
                if "neutral" in candidate.asset["time_of_day"]
                or not candidate.asset["category_affinity"]
            ],
        ),
        ("broadened_compatible_pool", list(candidates)),
    )
    seen = {candidate.asset["asset_id"] for candidate in pool}
    for label, additions in stages:
        if _duplicate_capacity(pool) >= target_count:
            break
        added = False
        for candidate in additions:
            if candidate.asset["asset_id"] not in seen:
                pool.append(candidate)
                seen.add(candidate.asset["asset_id"])
                added = True
        if added:
            relaxation_steps.append(label)
    return pool, relaxation_steps


def _is_water_asset(candidate: _ScoredAsset) -> bool:
    return bool(set(candidate.asset["scene_type"]) & WATER_SCENE_TYPES)


def _weighted_choice(
    candidates: Sequence[Tuple[_ScoredAsset, float, Tuple[str, ...]]],
    rng: random.Random,
) -> Tuple[_ScoredAsset, float, Tuple[str, ...]]:
    ordered = sorted(candidates, key=lambda item: item[0].asset["asset_id"])
    minimum = min(item[1] for item in ordered)
    weights = [max(1.0, item[1] - minimum + 1.0) ** 2 for item in ordered]
    return rng.choices(ordered, weights=weights, k=1)[0]


def select_scenic_assets(
    catalog: Mapping[str, Any],
    context: ScenicSelectionContext,
    *,
    video_dir: Path = scenic_asset_catalog.DEFAULT_VIDEO_DIR,
    selection_config: Optional[Mapping[str, Any]] = None,
    crossfade_seconds: float = 0.6,
) -> ScenicSelectionResult:
    policy = dict(selection_config or load_selection_config())
    target_count = requested_clip_count(
        context.narration_duration_seconds,
        policy,
    )
    profile = _profile_for_context(context, policy)
    weights = policy["scoring_weights"]
    exclusions = {
        "disabled": 0,
        "missing_file": 0,
        "malformed": 0,
        "time_conflict": 0,
    }
    scored: List[_ScoredAsset] = []
    assets = catalog.get("assets", [])
    if not isinstance(assets, list):
        raise ScenicSelectionError("Scenic catalog does not contain an assets list.")

    for asset in assets:
        if not isinstance(asset, dict):
            exclusions["malformed"] += 1
            continue
        required = scenic_asset_catalog.REQUIRED_ASSET_FIELDS
        if required - set(asset):
            exclusions["malformed"] += 1
            continue
        if not _has_valid_selection_shape(asset):
            exclusions["malformed"] += 1
            continue
        if not asset.get("enabled"):
            exclusions["disabled"] += 1
            continue
        path = Path(video_dir) / str(asset["filename"])
        if not path.is_file():
            exclusions["missing_file"] += 1
            continue
        if _is_severe_time_conflict(asset["time_of_day"], context):
            exclusions["time_conflict"] += 1
            continue
        scored.append(_score_asset(asset, path, context, profile, weights))

    if _duplicate_capacity(scored) < target_count:
        raise InsufficientCompatibleAssets(
            "Hard scenic safety filters left {0} duplicate-safe assets for "
            "{1} requested clips.".format(_duplicate_capacity(scored), target_count)
        )

    pool, relaxation_steps = _candidate_pool(
        scored,
        context=context,
        target_count=target_count,
    )
    if _duplicate_capacity(pool) < target_count:
        raise InsufficientCompatibleAssets(
            "Scenic selection relaxation left too few duplicate-safe assets."
        )

    rng = random.Random(context.seed)
    selected: List[Tuple[_ScoredAsset, float, Tuple[str, ...]]] = []
    selected_ids: set[str] = set()
    selected_groups: set[str] = set()
    selected_families: set[str] = set()
    water_count = 0

    while len(selected) < target_count:
        available = [
            candidate
            for candidate in pool
            if candidate.asset["asset_id"] not in selected_ids
            and (
                not candidate.asset.get("duplicate_group")
                or candidate.asset["duplicate_group"] not in selected_groups
            )
        ]
        if not available:
            raise InsufficientCompatibleAssets(
                "No duplicate-safe scenic candidates remain."
            )

        if policy["avoid_same_visual_family"]:
            family_unique = [
                candidate
                for candidate in available
                if candidate.asset["visual_family"] not in selected_families
            ]
            if family_unique:
                available = family_unique
            elif "relaxed_visual_family_uniqueness" not in relaxation_steps:
                relaxation_steps.append("relaxed_visual_family_uniqueness")

        non_water = [
            candidate
            for candidate in available
            if not _is_water_asset(candidate)
        ]
        if water_count >= int(policy["max_water_clips"]) and non_water:
            available = non_water
        elif (
            water_count >= int(policy["max_water_clips"])
            and "relaxed_scene_type_diversity" not in relaxation_steps
        ):
            relaxation_steps.append("relaxed_scene_type_diversity")

        dynamic_candidates: List[
            Tuple[_ScoredAsset, float, Tuple[str, ...]]
        ] = []
        previous_scenes = (
            set(selected[-1][0].asset["scene_type"]) if selected else set()
        )
        for candidate in available:
            dynamic_score = candidate.score
            dynamic_reasons = list(candidate.reasons)
            if previous_scenes & set(candidate.asset["scene_type"]):
                dynamic_score += float(weights["adjacent_scene_penalty"])
                dynamic_reasons.append("adjacent_scene_penalty")
            if candidate.asset["visual_family"] in selected_families:
                dynamic_score += float(weights["visual_family_reuse_penalty"])
                dynamic_reasons.append("visual_family_reuse_penalty")
            dynamic_candidates.append(
                (candidate, dynamic_score, tuple(dynamic_reasons))
            )

        chosen = _weighted_choice(dynamic_candidates, rng)
        selected.append(chosen)
        selected_ids.add(chosen[0].asset["asset_id"])
        selected_families.add(chosen[0].asset["visual_family"])
        if chosen[0].asset.get("duplicate_group"):
            selected_groups.add(chosen[0].asset["duplicate_group"])
        if _is_water_asset(chosen[0]):
            water_count += 1

    planned_duration = (
        context.planned_video_duration_seconds
        if context.planned_video_duration_seconds is not None
        else context.narration_duration_seconds
    )
    segment_duration = (
        float(planned_duration) + crossfade_seconds * (target_count - 1)
    ) / target_count
    assumed_source_duration = float(policy["assumed_source_duration_seconds"])
    stretch_ratio = segment_duration / assumed_source_duration
    warnings: List[str] = []
    if stretch_ratio > float(policy["max_preferred_stretch_ratio"]):
        warnings.append(
            "Estimated per-clip stretch ratio {0:.2f} exceeds preferred "
            "maximum {1:.2f}.".format(
                stretch_ratio,
                float(policy["max_preferred_stretch_ratio"]),
            )
        )

    selected_assets = tuple(
        SelectedScenicAsset(
            asset_id=candidate.asset["asset_id"],
            filename=candidate.asset["filename"],
            path=candidate.path,
            visual_family=candidate.asset["visual_family"],
            duplicate_group=candidate.asset.get("duplicate_group"),
            scene_type=tuple(candidate.asset["scene_type"]),
            time_of_day=tuple(candidate.asset["time_of_day"]),
            emotional_affinity=tuple(candidate.asset["emotional_affinity"]),
            energy_level=candidate.asset["energy_level"],
            selection_order=index,
            selection_score=round(dynamic_score, 3),
            selection_reasons=dynamic_reasons,
            estimated_stretch_ratio=round(stretch_ratio, 3),
        )
        for index, (candidate, dynamic_score, dynamic_reasons) in enumerate(
            selected, start=1
        )
    )
    top_scored = tuple(
        {
            "asset_id": candidate.asset["asset_id"],
            "filename": candidate.asset["filename"],
            "score": round(candidate.score, 3),
            "reasons": list(candidate.reasons),
        }
        for candidate in sorted(
            scored,
            key=lambda item: (-item.score, item.asset["asset_id"]),
        )[:10]
    )
    recent_status = (
        "soft_penalty_active:{0}".format(len(context.recent_asset_ids))
        if context.recent_asset_ids
        else "no_recent_asset_history"
    )
    return ScenicSelectionResult(
        selected_assets=selected_assets,
        requested_clip_count=target_count,
        selected_clip_count=len(selected_assets),
        eligible_catalog_count=len(assets),
        eligible_after_hard_filters=len(scored),
        top_scored_candidates=top_scored,
        scoring_summary={
            "prayer_category_id": context.prayer_category_id,
            "time_of_day": context.time_of_day,
            "emotional_tone": context.emotional_tone,
            "scene_profile_id": context.scene_profile_id,
            "content_type": context.content_type,
            "seed": context.seed,
            "policy_version": str(policy.get("policy_version", "")),
            "estimated_segment_duration_seconds": round(segment_duration, 3),
            "assumed_source_duration_seconds": assumed_source_duration,
            "crossfade_seconds": crossfade_seconds,
        },
        relaxation_steps=tuple(relaxation_steps),
        fallback_used=False,
        fallback_reason=None,
        hard_filter_exclusions=exclusions,
        recent_use_handling=recent_status,
        warnings=tuple(warnings),
    )


def load_and_select_scenic_assets(
    context: ScenicSelectionContext,
    *,
    catalog_path: Path = scenic_asset_catalog.DEFAULT_CATALOG_PATH,
    video_dir: Path = scenic_asset_catalog.DEFAULT_VIDEO_DIR,
    category_path: Path = scenic_asset_catalog.DEFAULT_CATEGORY_PATH,
    selection_config_path: Path = DEFAULT_SELECTION_CONFIG_PATH,
    crossfade_seconds: float = 0.6,
) -> ScenicSelectionResult:
    catalog = scenic_asset_catalog.load_catalog(catalog_path)
    scenic_asset_catalog.validate_catalog(
        catalog,
        video_dir=video_dir,
        category_path=category_path,
    )
    policy = load_selection_config(selection_config_path)
    return select_scenic_assets(
        catalog,
        context,
        video_dir=video_dir,
        selection_config=policy,
        crossfade_seconds=crossfade_seconds,
    )


def write_selection_diagnostic(
    context: ScenicSelectionContext,
    result: ScenicSelectionResult,
    *,
    output_dir: Path = DEFAULT_DIAGNOSTIC_DIR,
    filename: str = "selection_diagnostic.json",
) -> Path:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    payload = {
        "context": {
            **asdict(context),
            "recent_asset_ids": list(context.recent_asset_ids),
        },
        "result": result.to_metadata_dict(),
    }
    output_path = destination / filename
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def write_fallback_diagnostic(
    context: ScenicSelectionContext,
    fallback_metadata: Mapping[str, Any],
    *,
    output_dir: Path = DEFAULT_DIAGNOSTIC_DIR,
    filename: str = "selection_diagnostic.json",
) -> Path:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    payload = {
        "context": {
            **asdict(context),
            "recent_asset_ids": list(context.recent_asset_ids),
        },
        "result": dict(fallback_metadata),
    }
    output_path = destination / filename
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _diagnostic_contexts() -> List[ScenicSelectionContext]:
    return [
        ScenicSelectionContext(
            prayer_category_id=category,
            time_of_day=time_of_day,
            emotional_tone=emotion,
            scene_profile_id="current_default",
            narration_duration_seconds=48.0,
            content_type=content_type,
            seed=f"sprint3c-{category}",
            slot=time_of_day,
            planned_video_duration_seconds=54.5,
        )
        for category, time_of_day, emotion, content_type in (
            ("morning_prayer", "morning", "hopeful", "prayer_read"),
            ("night_prayer", "evening", "peaceful", "night_prayer_or_rest"),
            ("anxiety", "evening", "anxiety", "prayer_read"),
            ("protection", "morning", "fear", "prayer_read"),
            ("bible_verse", "morning", "reflective", "devotional_read"),
            ("general_prayer", "morning", "neutral", "prayer_read"),
        )
    ]


def write_category_diagnostics(
    *,
    output_dir: Path = DEFAULT_DIAGNOSTIC_DIR,
    crossfade_seconds: float = 0.6,
) -> Path:
    diagnostics = []
    for context in _diagnostic_contexts():
        result = load_and_select_scenic_assets(
            context,
            crossfade_seconds=crossfade_seconds,
        )
        diagnostics.append(
            {
                "context": {
                    **asdict(context),
                    "recent_asset_ids": list(context.recent_asset_ids),
                },
                "result": result.to_metadata_dict(),
            }
        )
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    output_path = destination / "category_selection_diagnostics.json"
    output_path.write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


if __name__ == "__main__":
    print(write_category_diagnostics())
