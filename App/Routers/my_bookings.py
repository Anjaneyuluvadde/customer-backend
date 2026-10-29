
from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from App.Dependencies.customer_auth import (
    AuthenticatedCustomer,
    get_current_customer,
    resolve_customer_target_id,
)
from Supabase.client import get_supabase_client


router = APIRouter(
    prefix="/api/v1/customer/my-bookings",
    tags=["Customer My Bookings"],
)


@router.get("")
async def get_my_bookings(
    customer: AuthenticatedCustomer = Depends(
        get_current_customer
    ),
):
    """
    Return booking history belonging to the authenticated customer,
    including legacy phone-matched profile bookings.
    """

    try:
        def fetch_bookings():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            if target_id and target_id != customer.user_id:
                # Query both IDs
                response = (
                    client.table("bookings")
                    .select("*")
                    .in_("user_id", [customer.user_id, target_id])
                    .order("created_at", desc=True)
                    .execute()
                )
            else:
                response = (
                    client.table("bookings")
                    .select("*")
                    .eq("user_id", customer.user_id)
                    .order("created_at", desc=True)
                    .execute()
                )

            return response.data or []

        bookings = await run_in_threadpool(fetch_bookings)

        return {
            "success": True,
            "data": bookings,
        }

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to fetch customer bookings at this time.",
        )
