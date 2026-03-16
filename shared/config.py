import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://estate:estate@db:5432/estate"
)

DATABASE_URL_SYNC = os.getenv(
    "DATABASE_URL_SYNC",
    "postgresql://estate:estate@db:5432/estate"
)

PROXY_URL = os.getenv("PROXY_URL", "")
