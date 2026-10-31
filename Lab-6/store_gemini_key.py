#!/usr/bin/env python3
"""Store the Gemini key as a SecureString, read at a hidden prompt, or delete it (Part C3)."""
import argparse
import getpass
import logging

from stack import parameters
from stack.clients import AwsClients
from stack.config import Settings


def main() -> None:
    """Store the key from a hidden prompt, or delete it with --delete."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env", help="path to the settings file")
    parser.add_argument("--delete", action="store_true", help="delete the parameter instead")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings.from_file(args.env)
    aws = AwsClients.create(settings.region)
    if args.delete:
        parameters.delete_parameter(aws, settings.gemini_param_name)
        return
    key = getpass.getpass("Gemini API key: ").strip()
    if not key:
        raise SystemExit("No key entered, nothing stored.")
    parameters.put_secret(aws, settings.gemini_param_name, key)
    print(f"Stored {settings.gemini_param_name} as a SecureString.")


if __name__ == "__main__":
    main()
