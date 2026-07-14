"""Manual trading mode configuration."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class ManualTradingConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MANUAL_",
        env_file=".env",
        extra="ignore",
    )

    bot_token: str = ""
    admin_user_ids: str = ""

    @property
    def admin_ids(self) -> list[int]:
        if not self.admin_user_ids:
            return []
        return [int(x.strip()) for x in self.admin_user_ids.split(",") if x.strip()]
