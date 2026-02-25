import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "ezauth"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class CLIConfig:
    server_url: str = ""
    publishable_key: str = ""
    secret_key: str = ""
    access_token: str = ""
    refresh_token: str = ""
    email: str = ""

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls) -> "CLIConfig":
        if not CONFIG_FILE.exists():
            return cls()
        try:
            data = json.loads(CONFIG_FILE.read_text())
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError):
            return cls()

    def clear_session(self) -> None:
        self.access_token = ""
        self.refresh_token = ""
        self.email = ""
        self.save()
