"""Break a real dependency and check that the app degrades the way the design says.

Slow, and needs the SSH key from SSH_KEY_PATH. Run with:   pytest -m chaos -s
"""
import time

import pytest
import requests

from stack import network
from tests.helpers import instance_ip, ssh, tier_url, wait_until

pytestmark = pytest.mark.chaos


def _status(url, timeout):
    try:
        return requests.get(url, timeout=timeout).status_code
    except requests.RequestException:
        return 0


def _in_service_instance(aws, asg_name):
    group = aws.autoscaling.describe_auto_scaling_groups(
        AutoScalingGroupNames=[asg_name])["AutoScalingGroups"][0]
    for instance in group["Instances"]:
        if instance["LifecycleState"] == "InService":
            return instance["InstanceId"]
    return None


def test_forecast_survives_losing_the_database(aws, settings, outputs, database):
    url = tier_url(outputs, settings, "weather") + "/weather?zip=60616"
    ip = instance_ip(aws, "weather-app")
    network.block_app_from_database(aws, settings, database.db_security_group_id)
    try:
        # Open connections are not cut when a rule is removed, so force a new one.
        result = ssh(settings, ip, "sudo systemctl restart weather")
        assert result.returncode == 0, result.stderr
        assert wait_until(lambda: _status(url, 20) == 200, timeout=60, interval=3)
        response = requests.get(url, timeout=20)
        print(f"\nwith the database cut off: {response.status_code}, cache={response.json()['cache']}")
        assert response.status_code == 200
        assert response.json()["cache"] == "unavailable"
    finally:
        network.allow_app_to_database(aws, settings, database.db_security_group_id)

    def cache_is_back():
        return requests.get(url, timeout=20).json()["cache"] in ("hit", "miss")
    assert wait_until(cache_is_back, timeout=90, interval=10), "the cache did not come back"


def test_advisor_fails_fast_while_the_weather_tier_recovers(aws, settings, outputs):
    weather = tier_url(outputs, settings, "weather") + "/weather?zip=60616"
    advisor = tier_url(outputs, settings, "advisor")
    assert _status(weather, 20) == 200, "the weather tier must be healthy before the experiment"
    victim = _in_service_instance(aws, settings.weather.asg_name)
    assert victim, f"no in-service instance in {settings.weather.asg_name}"

    aws.autoscaling.terminate_instance_in_auto_scaling_group(
        InstanceId=victim, ShouldDecrementDesiredCapacity=False)
    started = time.time()
    advisor_answers, home_page_stayed_up, recovered_after = [], True, None
    while time.time() - started < settings.recovery_slo_seconds:
        if _status(weather, 5) == 200:
            if advisor_answers:
                recovered_after = time.time() - started
                break
        else:
            # 25 seconds is past the advisor's own 20 second limit: 0 here would mean a hang.
            advisor_answers.append(_status(f"{advisor}/advice?zip=33101", 25))
            home_page_stayed_up = home_page_stayed_up and _status(f"{advisor}/", 5) == 200
        time.sleep(5)

    print(f"\nterminated {victim}, advisor said {sorted(set(advisor_answers))}, "
          f"recovery took {recovered_after}s (limit {settings.recovery_slo_seconds}s)")
    assert advisor_answers, "the weather tier never went down, so nothing was tested"
    assert 502 in advisor_answers, "the advisor should answer 502 during the outage"
    assert 0 not in advisor_answers, "the advisor hung instead of failing fast"
    assert home_page_stayed_up, "the advisor's own page must stay up during the outage"
    assert recovered_after is not None, "the weather tier did not recover in time"
