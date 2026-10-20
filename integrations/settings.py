import os
import re
from dataclasses import dataclass, field


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", value):
        raise ValueError("expected an uppercase Snowflake object identifier")
    return value


def require_live(allow_live: bool):
    if allow_live is not True or os.environ.get("ALLOW_LIVE_SERVICES") != "true":
        raise PermissionError("live services require explicit opt-in and ALLOW_LIVE_SERVICES=true")


@dataclass(frozen=True)
class SnowflakeSettings:
    account: str
    user: str
    role: str
    warehouse: str
    database: str
    schema: str
    order_view: str
    search_service: str
    oauth_token: str = field(repr=False)

    def __post_init__(self):
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.account, self.user, self.oauth_token)
        ):
            raise ValueError("Snowflake account, user and OAuth token are required")
        for name in ("role", "warehouse", "database", "schema", "order_view", "search_service"):
            identifier(getattr(self, name))

    @classmethod
    def from_env(cls, environment=None):
        values = os.environ if environment is None else environment
        names = (
            "account",
            "user",
            "role",
            "warehouse",
            "database",
            "schema",
            "order_view",
            "search_service",
            "oauth_token",
        )
        return cls(**{name: values.get("SNOWFLAKE_" + name.upper(), "") for name in names})
