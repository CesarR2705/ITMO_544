#!/usr/bin/env python3
"""Build the PostgreSQL database: the Python version of create_database.sh."""
import argparse
import logging

from stack.clients import AwsClients
from stack.config import Settings
from stack.database import create_database


def main() -> None:
    """Build the database, save its outputs, and print what to run next."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env", help="path to the settings file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_file(args.env)
    outputs = create_database(settings, AwsClients.create(settings.region))
    outputs.save()
    print()
    print(f"Done. Database endpoint: {outputs.db_host}")
    print("Automated backups are OFF (retention 0) and no final snapshot will be taken on delete.")
    print("Next: python create_weather_stack.py. When testing is finished: "
          "python delete_weather_stack.py, then python delete_database.py")


if __name__ == "__main__":
    main()
