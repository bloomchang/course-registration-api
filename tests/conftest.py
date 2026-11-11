import os

import httpx
import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    live_url = os.environ.get("CI_API_BASE_URL")
    if live_url:
        with httpx.Client(base_url=live_url, trust_env=False) as live_client:
            yield live_client
    else:
        with TestClient(app) as test_client:
            yield test_client
