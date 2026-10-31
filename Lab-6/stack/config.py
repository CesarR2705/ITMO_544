"""Settings for the stack, read from the .env file."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REQUIRED_KEYS = [
    "AWS_REGION", "AMI_ID", "KEY_NAME", "INSTANCE_TYPE", "APP_SECURITY_GROUP_ID", "APP_PORT",
    "WEATHER_ROLE_NAME", "WEATHER_PROFILE_NAME", "WEATHER_LT_NAME",
    "WEATHER_TG_NAME", "WEATHER_ASG_NAME", "WEATHER_LISTENER_PORT",
    "ADVISOR_ROLE_NAME", "ADVISOR_PROFILE_NAME", "ADVISOR_LT_NAME",
    "ADVISOR_TG_NAME", "ADVISOR_ASG_NAME", "ADVISOR_LISTENER_PORT",
    "ALB_NAME", "ALB_SG_NAME", "AZ_A", "AZ_B", "RECOVERY_SLO_SECONDS",
    "DB_INSTANCE_ID", "DB_INSTANCE_CLASS", "DB_ALLOCATED_STORAGE", "DB_PORT", "DB_NAME",
    "DB_USER", "DB_SG_NAME", "DB_SUBNET_GROUP_NAME", "DB_PASSWORD_PARAM", "CACHE_SECONDS",
    "GEMINI_PARAM_NAME", "GEMINI_MODEL", "KEY_CACHE_SECONDS", "CONTACT_EMAIL",
]


class ConfigError(Exception):
    """Raised when .env is missing keys, with a message that says which."""


def load_dotenv(path: str | Path = ".env") -> dict[str, str]:
    """Read KEY=VALUE lines into a dict. Comments and blank lines are skipped."""
    values: dict[str, str] = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _int_setting(values: dict[str, str], key: str) -> int:
    """A non-number gets a ConfigError that names the key, not a bare ValueError."""
    try:
        return int(values[key])
    except ValueError:
        raise ConfigError(f"{key} must be a whole number, got {values[key]!r}") from None


@dataclass(frozen=True)
class Tier:
    """Everything that belongs to one application tier (weather or advisor)."""
    name: str
    role_name: str
    profile_name: str
    lt_name: str
    tg_name: str
    asg_name: str
    listener_port: int
    app_dir: Path
    secret_param: str  # the one SSM parameter this tier's role may read

    @property
    def policy_name(self) -> str:
        """The name of this tier's inline policy."""
        return f"{self.role_name}-policy"

    @property
    def service_name(self) -> str:
        """The name of this tier's systemd service."""
        return self.name


@dataclass(frozen=True)
class Settings:
    """Every value the stack reads from .env."""
    region: str
    ami_id: str
    key_name: str
    instance_type: str
    app_sg_id: str
    app_port: int
    alb_name: str
    alb_sg_name: str
    az_a: str
    az_b: str
    recovery_slo_seconds: int
    db_instance_id: str
    db_instance_class: str
    db_allocated_storage: int
    db_port: int
    db_name: str
    db_user: str
    db_sg_name: str
    db_subnet_group_name: str
    db_password_param: str
    cache_seconds: int
    gemini_param_name: str
    gemini_model: str
    key_cache_seconds: int
    contact_email: str
    ssh_key_path: str
    weather: Tier
    advisor: Tier

    @property
    def tiers(self) -> tuple[Tier, Tier]:
        """Both tiers, for code that treats them the same."""
        return (self.weather, self.advisor)

    def tier(self, name: str) -> Tier:
        """Return the tier with this name."""
        return {"weather": self.weather, "advisor": self.advisor}[name]

    @classmethod
    def from_values(cls, v: dict[str, str], base_dir: str | Path = ".") -> "Settings":
        """Build Settings from a dict, or raise ConfigError naming what is wrong."""
        missing = [k for k in REQUIRED_KEYS if not v.get(k)]
        if missing:
            raise ConfigError("Missing keys in .env: " + ", ".join(missing))
        base = Path(base_dir)

        def tier(prefix: str, secret_param: str) -> Tier:
            """Build one Tier from the keys that start with this prefix."""
            return Tier(
                name=prefix.lower(),
                role_name=v[f"{prefix}_ROLE_NAME"],
                profile_name=v[f"{prefix}_PROFILE_NAME"],
                lt_name=v[f"{prefix}_LT_NAME"],
                tg_name=v[f"{prefix}_TG_NAME"],
                asg_name=v[f"{prefix}_ASG_NAME"],
                listener_port=_int_setting(v, f"{prefix}_LISTENER_PORT"),
                app_dir=base / f"{prefix.lower()}-app",
                secret_param=secret_param,
            )

        return cls(
            region=v["AWS_REGION"], ami_id=v["AMI_ID"], key_name=v["KEY_NAME"],
            instance_type=v["INSTANCE_TYPE"], app_sg_id=v["APP_SECURITY_GROUP_ID"],
            app_port=_int_setting(v, "APP_PORT"), alb_name=v["ALB_NAME"],
            alb_sg_name=v["ALB_SG_NAME"], az_a=v["AZ_A"], az_b=v["AZ_B"],
            recovery_slo_seconds=_int_setting(v, "RECOVERY_SLO_SECONDS"),
            db_instance_id=v["DB_INSTANCE_ID"], db_instance_class=v["DB_INSTANCE_CLASS"],
            db_allocated_storage=_int_setting(v, "DB_ALLOCATED_STORAGE"),
            db_port=_int_setting(v, "DB_PORT"), db_name=v["DB_NAME"], db_user=v["DB_USER"],
            db_sg_name=v["DB_SG_NAME"], db_subnet_group_name=v["DB_SUBNET_GROUP_NAME"],
            db_password_param=v["DB_PASSWORD_PARAM"],
            cache_seconds=_int_setting(v, "CACHE_SECONDS"),
            gemini_param_name=v["GEMINI_PARAM_NAME"], gemini_model=v["GEMINI_MODEL"],
            key_cache_seconds=_int_setting(v, "KEY_CACHE_SECONDS"),
            contact_email=v["CONTACT_EMAIL"],
            ssh_key_path=v.get("SSH_KEY_PATH") or str(base / f"{v['KEY_NAME']}.pem"),
            weather=tier("WEATHER", v["DB_PASSWORD_PARAM"]),
            advisor=tier("ADVISOR", v["GEMINI_PARAM_NAME"]),
        )

    @classmethod
    def from_file(cls, path: str | Path = ".env") -> "Settings":
        """Build Settings from a .env file, with app folders beside that file."""
        path = Path(path)
        return cls.from_values(load_dotenv(path), base_dir=path.resolve().parent)
