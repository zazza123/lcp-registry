"""Unit tests for the build_manifests engine (pure logic only — no network,
no venv, no installs). Run from the repo root with:

    python3.12 -m venv devenv
    devenv/bin/pip install -r .github/lcp/requirements-dev.txt
    PYTHONPATH=.github/lcp devenv/bin/python -m pytest .github/lcp/tests -v
"""
import build_manifests

from build_manifests import plan_versions


def test_module_imports():
    assert hasattr(build_manifests, "build_one")


def test_plan_versions_newest_only_when_missing():
    got = plan_versions(
        ["1.0", "1.1", "1.2"], on_disk=[], keep_versions=1,
        include_prereleases=False,
    )
    assert got == ["1.2"]


def test_plan_versions_backfills_up_to_keep_versions():
    got = plan_versions(
        ["1.0", "1.1", "1.2"], on_disk=["1.2"], keep_versions=2,
        include_prereleases=False,
    )
    assert got == ["1.1"]  # newest two are 1.1 & 1.2; 1.2 already on disk


def test_plan_versions_returns_missing_sorted_oldest_first():
    got = plan_versions(
        ["1.0", "1.1", "1.2"], on_disk=[], keep_versions=3,
        include_prereleases=False,
    )
    assert got == ["1.0", "1.1", "1.2"]


def test_plan_versions_excludes_prereleases_by_default():
    got = plan_versions(
        ["1.0", "2.0rc1"], on_disk=[], keep_versions=2,
        include_prereleases=False,
    )
    assert got == ["1.0"]


def test_plan_versions_includes_prereleases_when_enabled():
    got = plan_versions(
        ["1.0", "2.0rc1"], on_disk=[], keep_versions=2,
        include_prereleases=True,
    )
    assert got == ["1.0", "2.0rc1"]


def test_plan_versions_empty_when_all_present():
    got = plan_versions(
        ["1.0", "1.1"], on_disk=["1.0", "1.1"], keep_versions=2,
        include_prereleases=False,
    )
    assert got == []


def test_plan_versions_no_stable_returns_empty_when_prereleases_excluded():
    got = plan_versions(
        ["2.0rc1", "2.0rc2"], on_disk=[], keep_versions=2,
        include_prereleases=False,
    )
    assert got == []


def test_plan_versions_ignores_unparseable_versions():
    got = plan_versions(
        ["1.0", "not-a-version", "1.1"], on_disk=[], keep_versions=1,
        include_prereleases=False,
    )
    assert got == ["1.1"]
