#!/usr/bin/env python3
"""Tear both app tiers down: the Python version of delete_weather_stack.sh."""
import argparse
import logging

from stack.clients import AwsClients
from stack.config import Settings
from stack.runner import delete_weather_stack


def main() -> None:
    """Delete both tiers. The database and the Gemini key are left alone."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env", help="path to the settings file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_file(args.env)
    delete_weather_stack(settings, AwsClients.create(settings.region))


if __name__ == "__main__":
    main()
