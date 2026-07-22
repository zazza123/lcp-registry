"""Unit tests for the build_manifests engine (pure logic only — no network,
no venv, no installs). Run from the repo root with:

    python3.12 -m venv devenv
    devenv/bin/pip install -r .github/lcp/requirements-dev.txt
    PYTHONPATH=.github/lcp devenv/bin/python -m pytest .github/lcp/tests -v
"""
from pathlib import Path

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

    # import_name is None when not overridden — the signal to auto-detect.
    assert pkgs["requests"] == {
        "name": "requests", "import_name": None,
        "include_prereleases": False, "keep_versions": 2, "env": {},
        "constraints": [], "install_with": [],
    }
    assert pkgs["pyyaml"]["import_name"] == "yaml"
    assert pkgs["google-adk"]["include_prereleases"] is True
    assert pkgs["google-adk"]["keep_versions"] == 3


def test_load_packages_coerces_env_to_str(tmp_path, monkeypatch):
    # YAML parses an unquoted 3.5 as a float; env values must reach
    # subprocess/os.environ as strings either way.
    cfg = tmp_path / "packages.yaml"
    cfg.write_text(
        "python:\n"
        "  - name: pocket-coffea\n"
        "    env:\n"
        "      CMAKE_POLICY_VERSION_MINIMUM: 3.5\n"
        "      SOME_FLAG: \"1\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(build_manifests, "PACKAGES_YAML", cfg)
    (pkg,) = load_packages()
    assert pkg["env"] == {
        "CMAKE_POLICY_VERSION_MINIMUM": "3.5", "SOME_FLAG": "1",
    }


def test_load_packages_reads_real_config():
    pkgs = load_packages()
    assert len(pkgs) == 111
    names = {p["name"] for p in pkgs}
    assert {"boto3", "polars", "google-adk", "azure-ai-contentunderstanding"} <= names
    assert {p["name"]: p["import_name"] for p in pkgs}["pyyaml"] == "yaml"
    envs = {p["name"]: p["env"] for p in pkgs}
    assert envs["pocket-coffea"] == {"CMAKE_POLICY_VERSION_MINIMUM": "3.5"}
    assert envs["boto3"] == {}


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


import os

import regen_compare


def test_process_env_applies_and_restores(monkeypatch):
    monkeypatch.setenv("LCP_TEST_KEEP", "original")
    monkeypatch.delenv("LCP_TEST_NEW", raising=False)
    with build_manifests._process_env(
        {"LCP_TEST_KEEP": "override", "LCP_TEST_NEW": "value"}
    ):
        assert os.environ["LCP_TEST_KEEP"] == "override"
        assert os.environ["LCP_TEST_NEW"] == "value"
    assert os.environ["LCP_TEST_KEEP"] == "original"
    assert "LCP_TEST_NEW" not in os.environ


class _StubDoc:
    """Minimal LCPDocument stand-in for build_one plumbing tests."""

    def __init__(self):
        self.manifest = type(
            "M",
            (),
            {
                "library": type("L", (), {"version": None})(),
                "generation": type("G", (), {"date": None})(),
            },
        )()
        self.symbols = {}

    def to_json(self, indent=2):
        return "{}"


def _plumbed_build_one(
    tmp_path, monkeypatch, pkg_env, constraints=None, install_with=None,
    upload_date=None,
):
    """Run build_one with venv/pip/scan faked; return what each step saw."""
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["install_env"] = kwargs.get("env")
        seen["install_cmd"] = list(cmd)
        if "-c" in cmd:
            # The file lives in build_one's TemporaryDirectory — read it now,
            # it is gone by the time build_one returns.
            seen["constraints_file"] = Path(
                cmd[cmd.index("-c") + 1]
            ).read_text(encoding="utf-8")
        return type("R", (), {"returncode": 0, "stderr": ""})()

    def fake_scan(import_name, python=None, timeout=None):
        seen["scan_env"] = os.environ.get("CMAKE_POLICY_VERSION_MINIMUM")
        seen["doc"] = _StubDoc()
        return seen["doc"]

    monkeypatch.setattr(build_manifests.venv, "create", lambda *a, **k: None)
    monkeypatch.setattr(build_manifests.subprocess, "run", fake_run)
    monkeypatch.setattr(build_manifests, "scan_package_subprocess", fake_scan)
    monkeypatch.setattr(build_manifests, "validate_or_raise", lambda doc: None)
    monkeypatch.setattr(build_manifests, "MANIFESTS_ROOT", tmp_path)
    monkeypatch.setattr(build_manifests, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("CMAKE_POLICY_VERSION_MINIMUM", raising=False)

    seen["msg"] = build_manifests.build_one(
        "pocket-coffea", "0.9.13", "pocket_coffea", pkg_env, constraints,
        install_with, upload_date,
    )
    return seen


def test_build_one_applies_pkg_env_to_install_and_scan(tmp_path, monkeypatch):
    env = {"CMAKE_POLICY_VERSION_MINIMUM": "3.5"}
    seen = _plumbed_build_one(tmp_path, monkeypatch, env)
    # pip install ran with the override merged onto the process env ...
    assert seen["install_env"]["CMAKE_POLICY_VERSION_MINIMUM"] == "3.5"
    # ... the scan subprocess saw it via os.environ inheritance ...
    assert seen["scan_env"] == "3.5"
    # ... and it never leaked past the build.
    assert "CMAKE_POLICY_VERSION_MINIMUM" not in os.environ
    assert "pocket-coffea==0.9.13" in seen["msg"]


def test_build_one_without_env_inherits_process_environment(tmp_path, monkeypatch):
    seen = _plumbed_build_one(tmp_path, monkeypatch, None)
    # env=None means subprocess.run inherits the parent environment untouched.
    assert seen["install_env"] is None
    assert seen["scan_env"] is None


def test_regen_compare_load_package_env(tmp_path, monkeypatch):
    cfg = tmp_path / "packages.yaml"
    cfg.write_text(
        "python:\n"
        "  - name: boto3\n"
        "  - name: pocket-coffea\n"
        "    env:\n"
        "      CMAKE_POLICY_VERSION_MINIMUM: 3.5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(regen_compare, "PACKAGES_YAML", cfg)
    assert regen_compare.load_package_env("pocket-coffea") == {
        "CMAKE_POLICY_VERSION_MINIMUM": "3.5"
    }
    assert regen_compare.load_package_env("boto3") == {}
    assert regen_compare.load_package_env("unknown-slug") == {}


def test_regen_compare_load_package_env_reads_real_config():
    assert regen_compare.load_package_env("pocket-coffea") == {
        "CMAKE_POLICY_VERSION_MINIMUM": "3.5"
    }


from lcp.naming import normalize_package_name


def test_load_packages_normalizes_constraints():
    packages = {p["name"]: p for p in build_manifests.load_packages()}
    assert packages["pixeltable"]["constraints"] == ["pgvector<0.5"]
    # Packages that declare none get [], not None.
    assert packages["boto3"]["constraints"] == []


def test_pip_constraint_args_writes_file(tmp_path):
    args = build_manifests.pip_constraint_args(
        tmp_path, ["pgvector<0.5", "numpy<3"]
    )
    assert args[0] == "-c"
    assert Path(args[1]).read_text(encoding="utf-8") == "pgvector<0.5\nnumpy<3\n"


def test_pip_constraint_args_empty_is_no_flags(tmp_path):
    assert build_manifests.pip_constraint_args(tmp_path, []) == []
    assert not list(tmp_path.iterdir())  # no stray file written


def test_build_one_passes_constraints_to_pip(tmp_path, monkeypatch):
    seen = _plumbed_build_one(
        tmp_path, monkeypatch, None, constraints=["pgvector<0.5"]
    )
    cmd = seen["install_cmd"]
    assert "-c" in cmd
    assert seen["constraints_file"] == "pgvector<0.5\n"
    # The constraint flag precedes the requirement, and the requirement stands.
    assert cmd.index("-c") < cmd.index("pocket-coffea==0.9.13")


def test_build_one_without_constraints_passes_no_flag(tmp_path, monkeypatch):
    seen = _plumbed_build_one(tmp_path, monkeypatch, None)
    assert "-c" not in seen["install_cmd"]


def test_regen_compare_load_package_constraints(tmp_path, monkeypatch):
    cfg = tmp_path / "packages.yaml"
    cfg.write_text(
        "python:\n"
        "  - name: boto3\n"
        "  - name: pixeltable\n"
        "    constraints:\n"
        "      - \"pgvector<0.5\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(regen_compare, "PACKAGES_YAML", cfg)
    assert regen_compare.load_package_constraints("pixeltable") == [
        "pgvector<0.5"
    ]
    assert regen_compare.load_package_constraints("boto3") == []
    assert regen_compare.load_package_constraints("unknown-slug") == []


def test_regen_compare_constraints_match_build_manifests():
    """Both consumers must read the same list, or CI installs a different
    dependency closure than generation did and the comparison is meaningless.
    """
    packages = {p["name"]: p for p in build_manifests.load_packages()}
    for name, pkg in packages.items():
        slug = normalize_package_name(name)
        assert regen_compare.load_package_constraints(slug) == pkg["constraints"]


def test_load_packages_normalizes_install_with():
    packages = {p["name"]: p for p in build_manifests.load_packages()}
    assert packages["soupsieve"]["install_with"] == ["beautifulsoup4"]
    assert packages["boto3"]["install_with"] == []


def test_build_one_appends_install_with_after_the_target(tmp_path, monkeypatch):
    seen = _plumbed_build_one(
        tmp_path, monkeypatch, None, install_with=["beautifulsoup4"]
    )
    cmd = seen["install_cmd"]
    # The pinned target must precede the extras, so the resolver sees the pin
    # rather than resolving the package fresh as a dependency of the extra.
    assert cmd[-2:] == ["pocket-coffea==0.9.13", "beautifulsoup4"]


def test_build_one_without_install_with_installs_only_target(tmp_path, monkeypatch):
    seen = _plumbed_build_one(tmp_path, monkeypatch, None)
    assert seen["install_cmd"][-1] == "pocket-coffea==0.9.13"


def test_regen_compare_load_package_install_with(tmp_path, monkeypatch):
    cfg = tmp_path / "packages.yaml"
    cfg.write_text(
        "python:\n"
        "  - name: boto3\n"
        "  - name: soupsieve\n"
        "    install_with:\n"
        "      - beautifulsoup4\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(regen_compare, "PACKAGES_YAML", cfg)
    assert regen_compare.load_package_install_with("soupsieve") == [
        "beautifulsoup4"
    ]
    assert regen_compare.load_package_install_with("boto3") == []
    assert regen_compare.load_package_install_with("unknown-slug") == []


def test_regen_compare_install_with_matches_build_manifests():
    """CI must co-install exactly what generation did, or the rescan imports a
    different environment — or fails to import at all.
    """
    packages = {p["name"]: p for p in build_manifests.load_packages()}
    for name, pkg in packages.items():
        slug = normalize_package_name(name)
        assert (
            regen_compare.load_package_install_with(slug) == pkg["install_with"]
        )


import json as _json


def test_fetch_pypi_upload_dates_picks_earliest_and_filters(monkeypatch):
    payload = {
        "releases": {
            "1.0": [
                {"upload_time_iso_8601": "2026-01-02T00:00:00.000000Z", "yanked": False},
                {"upload_time_iso_8601": "2026-01-01T00:00:00.000000Z", "yanked": False},
            ],
            "0.9": [  # yanked-only release: excluded
                {"upload_time_iso_8601": "2025-12-01T00:00:00.000000Z", "yanked": True}
            ],
            "0.8": [],  # file-less release: excluded
        }
    }

    class FakeResp:
        def read(self):
            return _json.dumps(payload).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        build_manifests.urllib.request, "urlopen", lambda *a, **k: FakeResp()
    )
    dates = build_manifests.fetch_pypi_upload_dates("whatever")
    assert dates == {"1.0": "2026-01-01T00:00:00.000000Z"}


def test_build_one_stamps_generation_date_from_pypi(tmp_path, monkeypatch):
    from datetime import datetime
    seen = _plumbed_build_one(
        tmp_path, monkeypatch, None,
        upload_date="2026-06-24T09:12:34.123456Z",
    )
    assert seen["doc"].manifest.generation.date == datetime.fromisoformat(
        "2026-06-24T09:12:34.123456Z"
    )


def test_build_one_writes_gzip_with_zeroed_mtime(tmp_path, monkeypatch):
    _plumbed_build_one(
        tmp_path, monkeypatch, None,
        upload_date="2026-06-24T09:12:34.123456Z",
    )
    data = (
        tmp_path / "p" / "pocket-coffea" / "0.9.13.lcp.json.gz"
    ).read_bytes()
    # Bytes 4..8 are the gzip MTIME header; mtime=0 zeroes them so identical
    # content always serializes identically.
    assert data[4:8] == b"\x00\x00\x00\x00"
