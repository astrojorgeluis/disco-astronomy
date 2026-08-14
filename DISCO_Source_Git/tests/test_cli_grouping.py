import os

import pytest

from disco.cli import discover_groups, resolve_geometry_ref


def _touch_fits(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"SIMPLE")


def test_group_file_each_fits_own_group(tmp_path):
    a = tmp_path / "obj" / "src_Band6.fits"
    b = tmp_path / "obj" / "src_Band7.fits"
    _touch_fits(a)
    _touch_fits(b)
    groups = discover_groups(str(tmp_path / "obj"), mode="file")
    names = sorted(g["name"] for g in groups)
    assert names == ["src_Band6", "src_Band7"]
    assert all(len(g["files"]) == 1 for g in groups)


def test_group_dir_same_folder_one_group(tmp_path):
    folder = tmp_path / "AS209"
    _touch_fits(folder / "priism_b6.fits")
    _touch_fits(folder / "robust0.fits")
    groups = discover_groups(str(folder), mode="dir")
    assert len(groups) == 1
    assert groups[0]["name"] == "AS209"
    assert len(groups[0]["files"]) == 2


def test_group_dir_nested_folders_are_separate(tmp_path):
    _touch_fits(tmp_path / "AS209" / "a.fits")
    _touch_fits(tmp_path / "HD163296" / "b.fits")
    groups = discover_groups(str(tmp_path), mode="dir")
    names = sorted(g["name"] for g in groups)
    assert names == ["AS209", "HD163296"]


def test_group_name_legacy_band_prefix(tmp_path):
    d = tmp_path / "data"
    _touch_fits(d / "test_Band6_priism.fits")
    _touch_fits(d / "test_Band7_priism.fits")
    _touch_fits(d / "other_Band6.fits")
    groups = discover_groups(str(d), mode="name")
    prefixes = sorted(
        os.path.basename(g["output_dir"]) for g in groups
    )
    assert prefixes == ["other", "test"]
    test_g = next(g for g in groups if g["output_dir"].endswith("test"))
    assert len(test_g["files"]) == 2


def test_group_name_does_not_split_b6_underscore(tmp_path):
    d = tmp_path / "data"
    _touch_fits(d / "priism_b6.fits")
    _touch_fits(d / "priism_b7.fits")
    groups = discover_groups(str(d), mode="name")
    # No BandN token → two prefixes, not one "priism" group
    assert len(groups) == 2


def test_resolve_ref_basename_and_substring():
    temp = [
        {"filename": "robust0.fits", "filepath": "/data/robust0.fits"},
        {"filename": "priism_b6.fits", "filepath": "/data/priism_b6.fits"},
    ]
    assert resolve_geometry_ref(temp, "robust0.fits") == 0
    assert resolve_geometry_ref(temp, "priism") == 1
    assert resolve_geometry_ref(temp, "/data/robust0.fits") == 0


def test_resolve_ref_errors_on_zero_or_many():
    temp = [
        {"filename": "a_Band6.fits", "filepath": "/data/a_Band6.fits"},
        {"filename": "b_Band6.fits", "filepath": "/data/b_Band6.fits"},
    ]
    with pytest.raises(ValueError, match="matched 2"):
        resolve_geometry_ref(temp, "Band6")
    with pytest.raises(ValueError, match="matched 0"):
        resolve_geometry_ref(temp, "robust0")
