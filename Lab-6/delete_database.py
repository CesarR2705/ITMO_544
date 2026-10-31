#!/usr/bin/env python3
"""Remove the database and prove nothing is left: the Python version of delete_database.sh."""
import argparse
import logging

from stack.clients import AwsClients
from stack.config import Settings
from stack.database import delete_database, leftovers


def main() -> None:
    """Delete the database, then print whatever RDS still holds."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env", help="path to the settings file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_file(args.env)
    aws = AwsClients.create(settings.region)
    delete_database(settings, aws)
    print()
    for kind, names in leftovers(aws).items():
        print(f"RDS {kind} remaining: {names}")


if __name__ == "__main__":
    main()
