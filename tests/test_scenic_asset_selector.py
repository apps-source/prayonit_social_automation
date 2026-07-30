import json
from pathlib import Path
from types import SimpleNamespace

import history_store
import long_form_renderer
import prayonit_social
import scenic_asset_catalog
import scenic_asset_selector


def _asset(
    index,
    *,
    category=(),
    emotions=("peaceful",),
    times=("neutral",),
    scenes=("forest",),
    energy="low",
    family=None,
    duplicate_group=None,
    enabled=True,
    people=False,
):
    return {
        "asset_id": f"asset-{index}",
        "filename": f"asset-{index}.mp4",
        "scene_type": list(scenes),
        "time_of_day": list(times),
        "emotional_affinity": list(emotions),
        "category_affinity": list(category),
        "energy_level": energy,
        "visual_family": family or f"family-{index}",
        "duplicate_group": duplicate_group,
        "contains_people": people,
        "enabled": enabled,
        "notes": "",
    }


def _write_assets(tmp_path, assets, *, missing=()):
    missing_names = set(missing)
    for asset in assets:
        if asset["filename"] not in missing_names:
            (tmp_path / asset["filename"]).write_bytes(b"x")
    return {"catalog_version": "test", "assets": assets}


def _context(
    category,
    *,
    time_of_day="neutral",
    emotion="peaceful",
    duration=35.0,
    seed="seed-1",
    recent=(),
):
    return scenic_asset_selector.ScenicSelectionContext(
        prayer_category_id=category,
        time_of_day=time_of_day,
        emotional_tone=emotion,
        scene_profile_id="current_default",
        narration_duration_seconds=duration,
        content_type="prayer_read",
        seed=seed,
        slot=time_of_day,
        planned_video_duration_seconds=duration + 6.5,
        recent_asset_ids=tuple(recent),
    )


def _balanced_assets():
    return [
        _asset(
            0,
            category=("morning_prayer",),
            emotions=("hopeful", "uplifting"),
            times=("morning",),
            scenes=("field",),
        ),
        _asset(
            1,
            category=("night_prayer",),
            emotions=("peaceful", "reflective"),
            times=("night",),
            scenes=("clouds",),
        ),
        _asset(
            2,
            category=("anxiety",),
            emotions=("calming", "peaceful"),
            scenes=("ocean",),
        ),
        _asset(
            3,
            category=("anxiety",),
            emotions=("calming", "reflective"),
            scenes=("forest",),
        ),
        _asset(
            4,
            category=("protection",),
            emotions=("strong", "protective"),
            scenes=("mountains",),
            energy="medium",
        ),
        _asset(
            5,
            category=("protection",),
            emotions=("hopeful", "strong"),
            scenes=("home",),
            energy="medium",
        ),
        _asset(
            6,
            category=("bible_verse",),
            emotions=("reflective", "neutral"),
            scenes=("lake",),
        ),
        _asset(7, category=(), emotions=("peaceful",), scenes=("river",)),
        _asset(8, category=(), emotions=("hopeful",), scenes=("field",)),
        _asset(9, category=(), emotions=("reflective",), scenes=("path",)),
        _asset(10, category=(), emotions=("calming",), scenes=("waterfall",)),
        _asset(11, category=(), emotions=("neutral",), scenes=("abstract_nature",)),
        _asset(12, category=(), emotions=("peaceful",), scenes=("home",)),
        _asset(13, category=(), emotions=("hopeful",), scenes=("mountains",)),
    ]


def _select(tmp_path, assets, context, *, missing=()):
    catalog = _write_assets(tmp_path, assets, missing=missing)
    return scenic_asset_selector.select_scenic_assets(
        catalog,
        context,
        video_dir=tmp_path,
        selection_config=scenic_asset_selector.load_selection_config(),
        crossfade_seconds=0.6,
    )


def test_morning_prayer_excludes_explicit_night_only_assets(tmp_path):
    result = _select(
        tmp_path,
        _balanced_assets(),
        _context("morning_prayer", time_of_day="morning", emotion="hopeful"),
    )
    assert all("night" not in asset.time_of_day for asset in result.selected_assets)
    assert result.hard_filter_exclusions["time_conflict"] == 1


def test_night_prayer_excludes_explicit_morning_only_assets(tmp_path):
    result = _select(
        tmp_path,
        _balanced_assets(),
        _context("night_prayer", time_of_day="evening"),
    )
    assert all("morning" not in asset.time_of_day for asset in result.selected_assets)
    assert result.hard_filter_exclusions["time_conflict"] == 1


def test_anxiety_prefers_calming_low_energy_assets(tmp_path):
    result = _select(
        tmp_path,
        _balanced_assets(),
        _context("anxiety", emotion="anxiety"),
    )
    top = result.top_scored_candidates[0]
    assert top["asset_id"] in {"asset-2", "asset-3"}
    assert "energy_match:low" in top["reasons"]


def test_protection_ranked_pool_differs_from_anxiety(tmp_path):
    assets = _balanced_assets()
    anxiety = _select(tmp_path, assets, _context("anxiety", seed="anxiety"))
    protection = _select(
        tmp_path,
        assets,
        _context("protection", emotion="fear", seed="protection"),
    )
    anxiety_top = [item["asset_id"] for item in anxiety.top_scored_candidates[:3]]
    protection_top = [
        item["asset_id"] for item in protection.top_scored_candidates[:3]
    ]
    assert anxiety_top != protection_top
    assert protection_top[0] in {"asset-4", "asset-5"}


def test_bible_verse_prefers_reflective_low_distraction_asset(tmp_path):
    assets = _balanced_assets()
    assets.append(
        _asset(
            20,
            category=("bible_verse",),
            emotions=("strong",),
            scenes=("people",),
            energy="high",
            people=True,
        )
    )
    result = _select(
        tmp_path,
        assets,
        _context("bible_verse", emotion="reflective"),
    )
    assert result.top_scored_candidates[0]["asset_id"] == "asset-6"


def test_general_prayer_keeps_a_broad_compatible_pool(tmp_path):
    assets = _balanced_assets()
    result = _select(tmp_path, assets, _context("general_prayer"))
    assert result.eligible_after_hard_filters == len(assets)
    assert result.relaxation_steps == ()


def test_disabled_and_missing_assets_are_never_selected(tmp_path):
    assets = _balanced_assets()
    assets[7]["enabled"] = False
    result = _select(
        tmp_path,
        assets,
        _context("general_prayer"),
        missing=(assets[8]["filename"],),
    )
    selected_ids = {asset.asset_id for asset in result.selected_assets}
    assert assets[7]["asset_id"] not in selected_ids
    assert assets[8]["asset_id"] not in selected_ids
    assert result.hard_filter_exclusions["disabled"] == 1
    assert result.hard_filter_exclusions["missing_file"] == 1


def test_malformed_asset_metadata_is_excluded_safely(tmp_path):
    assets = _balanced_assets()
    assets[7]["time_of_day"] = "neutral"
    result = _select(tmp_path, assets, _context("general_prayer"))
    assert "asset-7" not in {
        asset.asset_id for asset in result.selected_assets
    }
    assert result.hard_filter_exclusions["malformed"] == 1


def test_duplicate_group_members_cannot_appear_together(tmp_path):
    assets = _balanced_assets()
    assets[7]["duplicate_group"] = "batch-1"
    assets[8]["duplicate_group"] = "batch-1"
    result = _select(
        tmp_path,
        assets,
        _context("general_prayer", duration=48.0),
    )
    groups = [
        asset.duplicate_group
        for asset in result.selected_assets
        if asset.duplicate_group
    ]
    assert groups.count("batch-1") <= 1


def test_visual_family_diversity_is_enforced_when_inventory_allows(tmp_path):
    assets = _balanced_assets()
    assets[7]["visual_family"] = "shared-family"
    assets[8]["visual_family"] = "shared-family"
    result = _select(
        tmp_path,
        assets,
        _context("general_prayer", duration=48.0),
    )
    families = [asset.visual_family for asset in result.selected_assets]
    assert len(families) == len(set(families))
    assert "relaxed_visual_family_uniqueness" not in result.relaxation_steps


def test_visual_family_reuse_is_explicitly_relaxed_when_required(tmp_path):
    assets = [
        _asset(index, family="shared-family", scenes=("forest",))
        for index in range(6)
    ]
    result = _select(
        tmp_path,
        assets,
        _context("general_prayer", duration=48.0),
    )
    assert len(result.selected_assets) == 6
    assert "relaxed_visual_family_uniqueness" in result.relaxation_steps


def test_clip_count_uses_narration_duration_threshold(tmp_path):
    assets = _balanced_assets()
    short = _select(tmp_path, assets, _context("general_prayer", duration=41.9))
    long = _select(tmp_path, assets, _context("general_prayer", duration=42.0))
    assert short.requested_clip_count == 5
    assert long.requested_clip_count == 6


def test_selection_is_deterministic_for_same_seed(tmp_path):
    assets = _balanced_assets()
    first = _select(tmp_path, assets, _context("general_prayer", seed="repeat"))
    second = _select(tmp_path, assets, _context("general_prayer", seed="repeat"))
    assert [asset.asset_id for asset in first.selected_assets] == [
        asset.asset_id for asset in second.selected_assets
    ]


def test_different_seeds_can_produce_different_valid_selections(tmp_path):
    assets = _balanced_assets()
    first = _select(tmp_path, assets, _context("general_prayer", seed="alpha"))
    second = _select(tmp_path, assets, _context("general_prayer", seed="omega"))
    assert [asset.asset_id for asset in first.selected_assets] != [
        asset.asset_id for asset in second.selected_assets
    ]
    assert len(first.selected_assets) == len(second.selected_assets) == 5


def test_neutral_assets_support_sparse_category_with_logged_relaxation(tmp_path):
    assets = [
        _asset(index, category=(), emotions=("hopeful",), times=("neutral",))
        for index in range(7)
    ]
    result = _select(
        tmp_path,
        assets,
        _context("hope", emotion="hopeful"),
    )
    assert len(result.selected_assets) == 5
    assert "relaxed_category_affinity" in result.relaxation_steps


def test_recent_use_is_a_soft_penalty_not_a_hard_exclusion(tmp_path):
    assets = _balanced_assets()
    result = _select(
        tmp_path,
        assets,
        _context("anxiety", emotion="anxiety", recent=("asset-2",)),
    )
    recent = next(
        item for item in result.top_scored_candidates if item["asset_id"] == "asset-2"
    )
    assert "recent_use_penalty" in recent["reasons"]
    assert result.recent_use_handling == "soft_penalty_active:1"


def test_stretch_warning_is_reported_without_duration_extension(tmp_path):
    assets = _balanced_assets()
    context = _context("general_prayer", duration=80.0)
    context = scenic_asset_selector.ScenicSelectionContext(
        **{
            **context.__dict__,
            "planned_video_duration_seconds": 100.0,
        }
    )
    result = _select(tmp_path, assets, context)
    assert result.warnings
    assert all(
        asset.estimated_stretch_ratio > 1.4
        for asset in result.selected_assets
    )


def test_primary_catalog_selection_returns_only_primary_library_paths(tmp_path):
    assets = _balanced_assets()
    result = _select(tmp_path, assets, _context("general_prayer"))
    assert all(asset.path.parent == tmp_path for asset in result.selected_assets)
    assert result.fallback_used is False


def test_catalog_failure_uses_legacy_selector_and_persists_fallback(
    isolated_database,
    monkeypatch,
    tmp_path,
):
    history_store.initialize_database()
    row_id = history_store.create_run_record(
        run_id="fallback-run",
        slot="morning",
        campaign_name="General",
        resolved_brief={"prayer_category_id": "general_prayer"},
        status="in_progress",
    )
    fallback_dir = tmp_path / "fallback"
    fallback_dir.mkdir()
    fallback_path = fallback_dir / "fallback.mp4"
    fallback_path.write_bytes(b"x")

    monkeypatch.setattr(
        scenic_asset_selector,
        "load_and_select_scenic_assets",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            scenic_asset_catalog.CatalogValidationError("invalid catalog")
        ),
    )
    monkeypatch.setattr(
        long_form_renderer,
        "select_long_form_video_assets",
        lambda **kwargs: [long_form_renderer.VideoAssetSpec(fallback_path)],
    )
    monkeypatch.setattr(
        prayonit_social.config,
        "SCENIC_SELECTION_DIAGNOSTIC_DIR",
        tmp_path / "diagnostics",
    )
    monkeypatch.setattr(
        prayonit_social.config,
        "MOTION_BACKGROUNDS_DIR",
        fallback_dir,
    )
    brief = SimpleNamespace(
        prayer_category_id="general_prayer",
        asset_time_of_day="morning",
        asset_emotional_tone="neutral",
        normalized_emotion_id="neutral",
        scene_profile_id="current_default",
        duration_seconds=35,
        content_type="prayer_read",
        run_id="fallback-run",
        slot="morning",
    )

    selected = prayonit_social._select_long_form_scenic_assets(
        brief=brief,
        narration_duration=35.0,
        planned_video_duration=41.5,
        run_row_id=row_id,
    )

    assert selected[0].path == fallback_path
    row = history_store.get_recent_campaign_history(days=1)[0]
    persisted = json.loads(row["resolved_brief_json"])
    assert persisted["selected_scenic_assets"][0]["asset_id"].startswith(
        "legacy_filename:"
    )
    assert persisted["scenic_selection"]["fallback_used"] is True
    assert (
        persisted["scenic_selection"]["fallback_reason"]
        == "catalog_validation_failure"
    )


def test_successful_selection_persists_catalog_asset_ids(
    isolated_database,
    monkeypatch,
    tmp_path,
):
    history_store.initialize_database()
    row_id = history_store.create_run_record(
        run_id="catalog-run",
        slot="morning",
        campaign_name="Hope",
        resolved_brief={"prayer_category_id": "hope"},
        status="in_progress",
    )
    selected_path = tmp_path / "sunrise.mp4"
    selected_path.write_bytes(b"x")
    selected_asset = scenic_asset_selector.SelectedScenicAsset(
        asset_id="sunrise-1",
        filename=selected_path.name,
        path=selected_path,
        visual_family="sunrise",
        duplicate_group=None,
        scene_type=("field",),
        time_of_day=("morning",),
        emotional_affinity=("hopeful",),
        energy_level="low",
        selection_order=1,
        selection_score=42.0,
        selection_reasons=("category_match",),
        estimated_stretch_ratio=1.1,
    )
    result = scenic_asset_selector.ScenicSelectionResult(
        selected_assets=(selected_asset,),
        requested_clip_count=1,
        selected_clip_count=1,
        eligible_catalog_count=1,
        eligible_after_hard_filters=1,
        top_scored_candidates=(),
        scoring_summary={"policy_version": "1"},
        relaxation_steps=(),
        fallback_used=False,
        fallback_reason=None,
        hard_filter_exclusions={},
        recent_use_handling="no_recent_asset_history",
    )
    monkeypatch.setattr(
        scenic_asset_selector,
        "load_and_select_scenic_assets",
        lambda *args, **kwargs: result,
    )
    monkeypatch.setattr(
        prayonit_social.config,
        "SCENIC_SELECTION_DIAGNOSTIC_DIR",
        tmp_path / "diagnostics",
    )
    brief = SimpleNamespace(
        prayer_category_id="hope",
        asset_time_of_day="morning",
        asset_emotional_tone="hopeful",
        normalized_emotion_id="hopeful",
        scene_profile_id="current_default",
        duration_seconds=35,
        content_type="prayer_read",
        run_id="catalog-run",
        slot="morning",
    )

    selected = prayonit_social._select_long_form_scenic_assets(
        brief=brief,
        narration_duration=35.0,
        planned_video_duration=41.5,
        run_row_id=row_id,
    )

    assert selected == [selected_path]
    row = history_store.get_recent_campaign_history(days=1)[0]
    persisted = json.loads(row["resolved_brief_json"])
    assert persisted["selected_scenic_assets"][0]["asset_id"] == "sunrise-1"
    assert persisted["scenic_selection"]["fallback_used"] is False


def test_renderer_explicit_assets_bypass_automatic_selector(monkeypatch, tmp_path):
    explicit = tmp_path / "explicit.mp4"
    explicit.write_bytes(b"x")
    monkeypatch.setattr(
        long_form_renderer,
        "select_long_form_video_assets",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("automatic selector should not be called")
        ),
    )
    normalized = long_form_renderer._normalize_video_assets([explicit])
    assert normalized == [long_form_renderer.VideoAssetSpec(explicit)]


def test_renderer_and_selector_share_one_crossfade_source():
    assert (
        long_form_renderer.CROSSFADE_SECONDS
        == prayonit_social.config.LONG_FORM_CROSSFADE_SECONDS
    )
