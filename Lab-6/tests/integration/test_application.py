"""Call the deployed app the way a user would. Run with:   pytest -m integration"""
import subprocess
import sys
from pathlib import Path

import pytest
import requests

from tests.helpers import probe, tier_url, wait_until

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module", autouse=True)
def stack_is_up(settings, outputs):
    """These tests sort before the health check test, and may start while instances boot."""
    for tier in settings.tiers:
        url = tier_url(outputs, settings, tier.name) + "/"
        assert wait_until(lambda: probe(url), timeout=420, interval=10), f"{url} never answered"


@pytest.fixture(scope="module")
def weather(settings, outputs):
    return tier_url(outputs, settings, "weather")


@pytest.fixture(scope="module")
def advisor(settings, outputs):
    return tier_url(outputs, settings, "advisor")


def _weather(weather, zip_code):
    return requests.get(f"{weather}/weather", params={"zip": zip_code}, timeout=30).json()


def test_second_lookup_is_a_miss_then_a_hit_and_lands_in_history(weather, settings):
    # A recent run leaves 60616 cached, so keep asking until that copy expires.
    first = wait_until(lambda: (body := _weather(weather, "60616"))["cache"] == "miss" and body,
                       timeout=settings.cache_seconds + 30, interval=15)
    assert first, "60616 never came back as a miss"
    second = _weather(weather, "60616")
    assert second["cache"] == "hit"
    assert second["forecast"] == first["forecast"]
    history = requests.get(f"{weather}/history", timeout=15).json()
    assert "60616" in [item["zip"] for item in history["lookups"]]


def test_a_bad_zip_is_400(weather):
    assert requests.get(f"{weather}/weather?zip=abc", timeout=15).status_code == 400


def test_an_unknown_zip_is_404(weather):
    assert requests.get(f"{weather}/weather?zip=00000", timeout=30).status_code == 404


def test_advice_comes_back_labelled_with_its_source(advisor):
    response = requests.get(f"{advisor}/advice?zip=60616", timeout=45)
    assert response.status_code == 200
    body = response.json()
    assert body["advice"]
    assert body["source"] in ("gemini", "fallback")


def test_advisor_rejects_a_bad_zip(advisor):
    assert requests.get(f"{advisor}/advice?zip=abc", timeout=15).status_code == 400


def test_the_full_smoke_test_passes():
    """All nine checks, including the cache, history and a real answer from Gemini."""
    result = subprocess.run([sys.executable, str(ROOT / "testing" / "app_smoke_test.py")],
                            capture_output=True, text=True, timeout=180)
    print(result.stdout)
    assert result.returncode == 0, result.stdout
