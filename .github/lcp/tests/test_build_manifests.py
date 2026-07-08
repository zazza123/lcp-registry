"""Unit tests for the build_manifests engine (pure logic only — no network,
no venv, no installs). Run from the repo root with:

    python3.12 -m venv devenv
    devenv/bin/pip install -r .github/lcp/requirements-dev.txt
    PYTHONPATH=.github/lcp devenv/bin/python -m pytest .github/lcp/tests -v
"""
import build_manifests


def test_module_imports():
    assert hasattr(build_manifests, "build_one")
