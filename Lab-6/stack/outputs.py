"""Identifiers the create steps generate, saved so tests and other tools can find them."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


def _save(data: dict, stem: str, directory: str | Path) -> None:
    """Write <stem>.json (for Python) and <stem>.env (for the shell and the smoke test)."""
    directory = Path(directory)
    (directory / f"{stem}.json").write_text(json.dumps(data, indent=2) + "\n")
    env_lines = [f"{key.upper()}={value}" for key, value in data.items()]
    (directory / f"{stem}.env").write_text("\n".join(env_lines) + "\n")


def _remove(stem: str, directory: str | Path) -> None:
    """Delete the .json and .env outputs with this name, if they exist."""
    for suffix in (".json", ".env"):
        (Path(directory) / f"{stem}{suffix}").unlink(missing_ok=True)


@dataclass
class DatabaseOutputs:
    """What create_database produces and the weather stack needs."""
    db_host: str
    db_security_group_id: str

    def save(self, directory: str | Path = ".") -> None:
        """Write db_outputs.json and db_outputs.env."""
        _save(asdict(self), "db_outputs", directory)

    @classmethod
    def load(cls, directory: str | Path = ".") -> "DatabaseOutputs":
        """Read db_outputs.json."""
        return cls(**json.loads((Path(directory) / "db_outputs.json").read_text()))

    @staticmethod
    def remove(directory: str | Path = ".") -> None:
        """Delete both database outputs files."""
        _remove("db_outputs", directory)


@dataclass
class StackOutputs:
    """What create_weather_stack produces and the tests need."""
    vpc_id: str
    subnet_a: str
    subnet_b: str
    alb_security_group_id: str
    alb_arn: str
    alb_dns_name: str
    weather_tg_arn: str
    advisor_tg_arn: str

    def tg_arn(self, tier_name: str) -> str:
        """Return the target group ARN for this tier."""
        return {"weather": self.weather_tg_arn, "advisor": self.advisor_tg_arn}[tier_name]

    def save(self, directory: str | Path = ".") -> None:
        """Write stack_outputs.json and stack_outputs.env."""
        _save(asdict(self), "stack_outputs", directory)

    @classmethod
    def load(cls, directory: str | Path = ".") -> "StackOutputs":
        """Read stack_outputs.json."""
        return cls(**json.loads((Path(directory) / "stack_outputs.json").read_text()))

    @staticmethod
    def remove(directory: str | Path = ".") -> None:
        """Delete both stack outputs files."""
        _remove("stack_outputs", directory)
