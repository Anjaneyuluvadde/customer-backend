import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import Client, create_client

# Ensure .env from CUSTOMER-BACKEND root is loaded regardless of current working directory
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH)
else:
    load_dotenv()

SUPABASE_URL = (
    os.getenv("SUPABASE_URL", "").strip()
    or os.getenv("EXPO_PUBLIC_SUPABASE_URL", "").strip()
)
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_ANON_KEY = (
    os.getenv("SUPABASE_ANON_KEY", "").strip()
    or os.getenv("EXPO_PUBLIC_SUPABASE_ANON_KEY", "").strip()
)


def get_supabase_client() -> Client:
    """
    Create a Supabase client using the project URL.

    Uses SUPABASE_SERVICE_ROLE_KEY if available so server-side operations bypass RLS.
    Falls back to SUPABASE_ANON_KEY if service role key is not configured.
    """
    if not SUPABASE_URL:
        raise RuntimeError("SUPABASE_URL is not configured.")

    key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
    if not key:
        raise RuntimeError("Neither SUPABASE_SERVICE_ROLE_KEY nor SUPABASE_ANON_KEY is configured.")

    return create_client(SUPABASE_URL, key)
