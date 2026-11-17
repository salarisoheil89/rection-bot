from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    bot_token: str
    database_url: str = "sqlite+aiosqlite:///./bot.db"
    admin_usernames: str = "Sikxven,B2nald"
    trial_hours: int = 24
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    @property
    def initial_admins(self):
        return {x.strip().lstrip("@").lower() for x in self.admin_usernames.split(",") if x.strip()}
settings = Settings()
