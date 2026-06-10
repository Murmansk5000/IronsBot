from pydantic import BaseModel, Field

IRONS_DATA_RELEASE = "https://github.com/Murmansk5000/seerapi/releases/download"


class DataSourceConfig(BaseModel):
    url: str
    fingerprint_url: str = ""
    interval_minutes: int = Field(default=60, gt=0)
    local_path: str


class DataSyncConfig(BaseModel):
    on_startup: bool = False
    interval_enabled: bool = True
    sources: dict[str, DataSourceConfig] = Field(
        default_factory=lambda: {
            "seerapi": DataSourceConfig(
                url=f"{IRONS_DATA_RELEASE}/ironsbot-data-latest/ironsbot-data.sqlite",
                fingerprint_url=(
                    f"{IRONS_DATA_RELEASE}/ironsbot-data-latest/"
                    "ironsbot-data.sqlite.sha256"
                ),
                interval_minutes=60,
                local_path="data/ironsbot-data.sqlite",
            ),
            "aliases": DataSourceConfig(
                url=f"{IRONS_DATA_RELEASE}/alias-db-latest/aliases-data.sqlite",
                fingerprint_url=(
                    f"{IRONS_DATA_RELEASE}/alias-db-latest/"
                    "aliases-data.sqlite.sha256"
                ),
                interval_minutes=60,
                local_path="data/aliases-data.sqlite",
            ),
        }
    )
