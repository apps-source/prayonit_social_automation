import copy
import inspect
import json
from pathlib import Path

import pytest

import long_form_renderer
import scenic_asset_catalog


def _catalog():
    return scenic_asset_catalog.load_catalog()


def _first_asset_catalog():
    catalog = _catalog()
    catalog["assets"] = [copy.deepcopy(catalog["assets"][0])]
    return catalog


def _write_video_files(video_dir: Path, filenames):
    video_dir.mkdir(parents=True, exist_ok=True)
    for filename in filenames:
        (video_dir / filename).write_bytes(b"placeholder")


def test_all_eligible_long_form_videos_are_cataloged():
    catalog = _catalog()
    catalog_names = {asset["filename"] for asset in catalog["assets"]}
    eligible_names = set(scenic_asset_catalog.list_eligible_video_filenames())
    assert len(eligible_names) == 81
    assert catalog_names == eligible_names


def test_all_cataloged_files_exist_and_enabled_assets_are_discoverable():
    catalog = _catalog()
    scenic_asset_catalog.validate_catalog(catalog)
    for asset in catalog["assets"]:
        assert (scenic_asset_catalog.DEFAULT_VIDEO_DIR / asset["filename"]).is_file()
        if asset["enabled"]:
            assert asset["filename"] in scenic_asset_catalog.list_eligible_video_filenames()


def test_catalog_asset_ids_and_filenames_are_unique():
    assets = _catalog()["assets"]
    assert len({asset["asset_id"] for asset in assets}) == len(assets)
    assert len({asset["filename"] for asset in assets}) == len(assets)


@pytest.mark.parametrize(
    ("field_name", "error_pattern"),
    [
        ("asset_id", "duplicate asset_id"),
        ("filename", "duplicate filename entry"),
    ],
)
def test_duplicate_ids_and_filenames_fail_validation(
    tmp_path, field_name, error_pattern
):
    assets = copy.deepcopy(_catalog()["assets"][:2])
    assets[1][field_name] = assets[0][field_name]
    catalog = {"catalog_version": "1", "assets": assets}
    video_dir = tmp_path / "videos"
    _write_video_files(video_dir, {asset["filename"] for asset in assets})
    with pytest.raises(
        scenic_asset_catalog.CatalogValidationError,
        match=error_pattern,
    ):
        scenic_asset_catalog.validate_catalog(catalog, video_dir=video_dir)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("scene_type", ["volcano"]),
        ("time_of_day", ["midnight_blue"]),
        ("emotional_affinity", ["melancholic"]),
    ],
)
def test_controlled_vocabulary_validation_rejects_unknown_values(
    tmp_path, field_name, invalid_value
):
    catalog = _first_asset_catalog()
    asset = catalog["assets"][0]
    asset[field_name] = invalid_value
    video_dir = tmp_path / "videos"
    _write_video_files(video_dir, [asset["filename"]])
    with pytest.raises(
        scenic_asset_catalog.CatalogValidationError,
        match="unsupported values",
    ):
        scenic_asset_catalog.validate_catalog(catalog, video_dir=video_dir)


def test_invalid_canonical_category_fails_validation(tmp_path):
    catalog = _first_asset_catalog()
    asset = catalog["assets"][0]
    asset["category_affinity"] = ["not_a_prayer_category"]
    video_dir = tmp_path / "videos"
    _write_video_files(video_dir, [asset["filename"]])
    with pytest.raises(
        scenic_asset_catalog.CatalogValidationError,
        match="category_affinity contains unsupported values",
    ):
        scenic_asset_catalog.validate_catalog(catalog, video_dir=video_dir)


def test_invalid_energy_level_fails_validation(tmp_path):
    catalog = _first_asset_catalog()
    asset = catalog["assets"][0]
    asset["energy_level"] = "extreme"
    video_dir = tmp_path / "videos"
    _write_video_files(video_dir, [asset["filename"]])
    with pytest.raises(
        scenic_asset_catalog.CatalogValidationError,
        match="unsupported energy_level",
    ):
        scenic_asset_catalog.validate_catalog(catalog, video_dir=video_dir)


def test_absolute_paths_are_rejected(tmp_path):
    catalog = _first_asset_catalog()
    asset = catalog["assets"][0]
    asset["filename"] = "/Users/example/private/video.mp4"
    with pytest.raises(
        scenic_asset_catalog.CatalogValidationError,
        match="repository-relative basename",
    ):
        scenic_asset_catalog.validate_catalog(catalog, video_dir=tmp_path)


def test_duplicate_groups_contain_multiple_files_with_one_visual_family():
    assets = _catalog()["assets"]
    groups = {}
    for asset in assets:
        if asset["duplicate_group"]:
            groups.setdefault(asset["duplicate_group"], []).append(asset)
    assert len(groups) == 10
    assert all(len(members) == 4 for members in groups.values())
    assert all(
        len({member["visual_family"] for member in members}) == 1
        for members in groups.values()
    )


def test_four_variation_family_shares_one_duplicate_group():
    assets = [
        asset
        for asset in _catalog()["assets"]
        if asset["visual_family"] == "river_batch_20260712"
    ]
    assert len(assets) == 4
    assert {asset["duplicate_group"] for asset in assets} == {
        "river_batch_20260712"
    }


def test_single_member_duplicate_group_fails_validation(tmp_path):
    catalog = _first_asset_catalog()
    asset = catalog["assets"][0]
    asset["duplicate_group"] = "orphan_group"
    video_dir = tmp_path / "videos"
    _write_video_files(video_dir, [asset["filename"]])
    with pytest.raises(
        scenic_asset_catalog.CatalogValidationError,
        match="must contain at least two assets",
    ):
        scenic_asset_catalog.validate_catalog(catalog, video_dir=video_dir)


def test_production_selector_does_not_consume_catalog(monkeypatch, tmp_path):
    video_dir = tmp_path / "videos"
    _write_video_files(video_dir, [f"clip-{index}.mp4" for index in range(6)])
    monkeypatch.setattr(
        scenic_asset_catalog,
        "load_catalog",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Production selector must not load the Sprint 3B catalog")
        ),
    )
    selected = long_form_renderer.select_long_form_video_assets(
        long_video_dir=video_dir
    )
    assert len(selected) == 5
    assert len({item.path for item in selected}) == 5


def test_renderer_has_no_catalog_dependency():
    source = inspect.getsource(long_form_renderer)
    assert "scenic_asset_catalog" not in source
    assert "video_assets.json" not in source


@pytest.mark.parametrize("catalog_contents", ["{bad json", json.dumps([])])
def test_malformed_catalog_fails_safely_in_diagnostics(
    tmp_path, catalog_contents
):
    catalog_path = tmp_path / "video_assets.json"
    catalog_path.write_text(catalog_contents, encoding="utf-8")
    summary = scenic_asset_catalog.write_diagnostic_summary(
        catalog_path=catalog_path,
        video_dir=tmp_path / "videos",
        output_dir=tmp_path / "diagnostics",
    )
    assert summary["status"] == "invalid"
    assert (tmp_path / "diagnostics" / "catalog_summary.json").is_file()
    assert (tmp_path / "diagnostics" / "catalog_summary.txt").is_file()


def test_catalog_summary_reports_current_library_counts():
    catalog = _catalog()
    scenic_asset_catalog.validate_catalog(catalog)
    summary = scenic_asset_catalog.summarize_catalog(catalog)
    assert summary["status"] == "valid"
    assert summary["total_eligible_videos"] == 81
    assert summary["total_catalog_entries"] == 81
    assert summary["enabled_count"] == 81
    assert summary["disabled_count"] == 0
    assert summary["duplicate_group_count"] == 10
