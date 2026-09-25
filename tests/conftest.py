import pytest

from law_radar.config import ROOT, load_config, load_datasets


@pytest.fixture(autouse=True)
def _no_env_icp(monkeypatch):
    # Tests always use the fictional Ledgerly ICP, never a real one from the environment.
    monkeypatch.delenv("ICP_YAML", raising=False)


@pytest.fixture
def cfg():
    return load_config(str(ROOT / "icp.example.yaml"))


@pytest.fixture
def datasets():
    return load_datasets()
