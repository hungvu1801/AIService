from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str

    secret_key: SecretStr
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    s3_bucket_name: str = ""
    s3_region: str = "ap-southeast-1"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_endpoint_url: str | None = None

    max_upload_size_bytes: int = 15 * 1024 * 1024
    max_video_upload_bytes: int = 150 * 1024 * 1024

    comfyui_base_url: str = "http://127.0.0.1:8188"
    comfyui_workflow_path: str = "workflows/motion_transfer.json"
    comfyui_animatediff_workflow_path: str = "workflows/animatediff.json"
    comfyui_animatediff_video_node: str = "24"
    comfyui_minimax_workflow_path: str = "workflows/minimaxH3.json"
    comfyui_wan_t2v_workflow_path: str = "workflows/motion_transfer_2.json"
    data_dir: str = "data"

    posts_per_page: int = 10

    reset_token_expiration_minutes: int = 60

    mail_server: str = "localhost"

    mail_port: int = 587
    mail_username: str = ""
    mail_password: SecretStr = SecretStr("")
    mail_from: str = "noreply@example.com"
    mail_use_tls: bool = True
    frontend_url: str = "http://localhost:8000"


settings = Settings()  # Loaded from .env file
