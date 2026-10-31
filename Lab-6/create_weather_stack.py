#!/usr/bin/env python3
"""Build both app tiers: the Python version of create_weather_stack.sh."""
import argparse
import logging

from stack.clients import AwsClients
from stack.config import Settings
from stack.runner import create_weather_stack


def main() -> None:
    """Build both tiers, save their outputs, and print the two URLs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env", help="path to the settings file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_file(args.env)
    outputs = create_weather_stack(settings, AwsClients.create(settings.region))
    outputs.save()
    print()
    print(f"Weather: http://{outputs.alb_dns_name}:{settings.weather.listener_port}/weather?zip=60616")
    print(f"Advisor: http://{outputs.alb_dns_name}:{settings.advisor.listener_port}/")
    print("Give the target groups 2 to 3 minutes to report healthy, then run: pytest -m integration")


if __name__ == "__main__":
    main()
