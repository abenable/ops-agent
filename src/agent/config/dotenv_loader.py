"""Explicit .env loading so secrets are available before settings are read."""

from dotenv import find_dotenv, load_dotenv


def load_env() -> None:
    """Load environment variables from the nearest `.env` file."""
    env_file = find_dotenv()
    if env_file:
        load_dotenv(env_file, override=False)
