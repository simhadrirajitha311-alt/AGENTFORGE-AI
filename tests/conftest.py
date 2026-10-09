import pytest
from fastapi.testclient import TestClient

import app.api as api_module
import app.main as main_module
from app.config import Settings


@pytest.fixture
def test_settings(tmp_path, monkeypatch):
    settings = Settings(database_path=tmp_path / "agentforge-test.db", max_upload_bytes=256)
    monkeypatch.setattr(api_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def client(test_settings):
    with TestClient(main_module.app) as test_client:
        yield test_client
