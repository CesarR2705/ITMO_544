"""Small helpers shared by the integration tests."""
import subprocess
import time

import requests


def probe(url: str, timeout: float = 3.0) -> bool:
    """True if the URL answers 200 within the timeout."""
    try:
        return requests.get(url, timeout=timeout).status_code == 200
    except requests.RequestException:
        return False


def wait_until(check, timeout: int = 300, interval: int = 10):
    """Call check() until it returns something truthy, or fail after `timeout` seconds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = check()
        if result:
            return result
        time.sleep(interval)
    return None


def tier_url(outputs, settings, tier_name: str) -> str:
    port = settings.tier(tier_name).listener_port
    return f"http://{outputs.alb_dns_name}:{port}"


def instance_ip(aws, tag: str) -> str:
    """The public address of the running instance with this Name tag."""
    reservations = aws.ec2.describe_instances(Filters=[
        {"Name": "tag:Name", "Values": [tag]},
        {"Name": "instance-state-name", "Values": ["running"]},
    ])["Reservations"]
    return reservations[0]["Instances"][0]["PublicIpAddress"]


def ssh(settings, ip: str, command: str) -> subprocess.CompletedProcess:
    """Run one command on an instance over SSH."""
    return subprocess.run(
        ["ssh", "-i", settings.ssh_key_path, "-o", "StrictHostKeyChecking=accept-new",
         "-o", "ConnectTimeout=10", f"ec2-user@{ip}", command],
        capture_output=True, text=True, timeout=60)
