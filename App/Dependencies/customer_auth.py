
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from Supabase.client import get_supabase_client


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedCustomer:
    user_id: str
    phone: str | None = None
    email: str | None = None


def resolve_customer_target_id(client, customer: AuthenticatedCustomer) -> str:
    """
    Resolve customer target ID.
    If the customer's phone number matches an existing legacy profile,
    return that profile's ID so that past bookings/data remain accessible.
    Otherwise, return customer.user_id.
    """
    if customer.phone:
        clean_phone = "".join(filter(str.isdigit, str(customer.phone)))[-10:]
        if clean_phone:
            try:
                resp = (
                    client.table("profile")
                    .select("id")
                    .ilike("phone", f"%{clean_phone}%")
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                if resp.data and len(resp.data) > 0 and resp.data[0].get("id"):
                    return str(resp.data[0]["id"])
            except Exception:
                pass
    return customer.user_id


async def get_current_customer(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        bearer_scheme
    ),
) -> AuthenticatedCustomer:
    """
    Validate a Supabase Auth access token.

    Never trust customer IDs supplied in query parameters
    or request bodies.
    """

    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = credentials.credentials

    def verify_customer_token():
        client = get_supabase_client()
        return client.auth.get_user(access_token)

    try:
        response = await run_in_threadpool(
            verify_customer_token
        )

        user = response.user

        if not user or not user.id:
            raise ValueError("Invalid authenticated user")

        validated_id = str(UUID(str(user.id)))

        phone = getattr(user, "phone", None)
        if not phone and hasattr(user, "user_metadata") and isinstance(user.user_metadata, dict):
            phone = user.user_metadata.get("phone_number") or user.user_metadata.get("phone")

        email = getattr(user, "email", None)

        return AuthenticatedCustomer(
            user_id=validated_id,
            phone=str(phone) if phone else None,
            email=str(email) if email else None,
        )

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
