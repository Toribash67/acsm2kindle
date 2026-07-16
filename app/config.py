import os
from dataclasses import dataclass


@dataclass
class Settings:
    kindle_email: str
    sender_email: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    data_dir: str

    @property
    def incoming_dir(self) -> str:
        return os.path.join(self.data_dir, "incoming")

    @property
    def library_dir(self) -> str:
        return os.path.join(self.data_dir, "library")

    @property
    def config_dir(self) -> str:
        return os.path.join(self.data_dir, "config")

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "jobs.sqlite")

    def ensure_dirs(self) -> None:
        for d in (self.incoming_dir, self.library_dir, self.config_dir):
            os.makedirs(d, exist_ok=True)


def get_settings() -> Settings:
    return Settings(
        kindle_email=os.environ.get("KINDLE_EMAIL", ""),
        sender_email=os.environ.get("SENDER_EMAIL", ""),
        smtp_host=os.environ.get("SMTP_HOST", ""),
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_user=os.environ.get("SMTP_USER", ""),
        smtp_password=os.environ.get("SMTP_PASSWORD", ""),
        data_dir=os.environ.get("DATA_DIR", "/data"),
    )
