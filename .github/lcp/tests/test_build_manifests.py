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


import build_manifests
from build_manifests import load_packages


def test_load_packages_applies_defaults(tmp_path, monkeypatch):
    cfg = tmp_path / "packages.yaml"
    cfg.write_text(
        "python:\n"
        "  - name: requests\n"
        "  - name: pyyaml\n"
        "    import_name: yaml\n"
        "  - name: google-adk\n"
        "    import_name: google.adk\n"
        "    include_prereleases: true\n"
        "    keep_versions: 3\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(build_manifests, "PACKAGES_YAML", cfg)
    pkgs = {p["name"]: p for p in load_packages()}

    assert pkgs["requests"] == {
        "name": "requests", "import_name": "requests",
        "include_prereleases": False, "keep_versions": 2,
    }
    assert pkgs["pyyaml"]["import_name"] == "yaml"
    assert pkgs["google-adk"]["include_prereleases"] is True
    assert pkgs["google-adk"]["keep_versions"] == 3


def test_load_packages_reads_real_config():
    pkgs = load_packages()
    assert len(pkgs) == 102
    names = {p["name"] for p in pkgs}
    assert {"boto3", "polars", "google-adk", "azure-ai-contentunderstanding"} <= names
    assert {p["name"]: p["import_name"] for p in pkgs}["pyyaml"] == "yaml"


from build_manifests import write_latest_json


def test_write_latest_json_picks_max_stable(tmp_path):
    for v in ["1.0.0", "1.2.0", "1.1.0"]:
        (tmp_path / f"{v}.lcp.json.gz").write_bytes(b"")
    write_latest_json(tmp_path, include_prereleases=False)
    import json
    data = json.loads((tmp_path / "latest.json").read_text())
    assert data == {"version": "1.2.0", "manifest": "1.2.0.lcp.json.gz"}


def test_write_latest_json_excludes_prerelease_by_default(tmp_path):
    for v in ["1.0.0", "2.0.0rc1"]:
        (tmp_path / f"{v}.lcp.json.gz").write_bytes(b"")
    write_latest_json(tmp_path, include_prereleases=False)
    import json
    data = json.loads((tmp_path / "latest.json").read_text())
    assert data["version"] == "1.0.0"


def test_write_latest_json_includes_prerelease_when_enabled(tmp_path):
    for v in ["1.0.0", "2.0.0rc1"]:
        (tmp_path / f"{v}.lcp.json.gz").write_bytes(b"")
    write_latest_json(tmp_path, include_prereleases=True)
    import json
    data = json.loads((tmp_path / "latest.json").read_text())
    assert data["version"] == "2.0.0rc1"
