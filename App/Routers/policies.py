
from fastapi import APIRouter, HTTPException, status
from starlette.concurrency import run_in_threadpool

from Supabase.client import get_supabase_client


router = APIRouter(
    prefix="/api/v1/customer/policies",
    tags=["Customer Policies"],
)


@router.get("")
async def get_customer_policies():
    """
    Public endpoint to fetch active Customer App policies,
    including Terms & Conditions and Privacy Policy.

    Only returns records where app_type = customer.
    """
    try:
        def fetch_policies():
            client = get_supabase_client()

            response = (
                client.table("app_policies")
                .select("*")
                .eq("app_type", "customer")
                .eq("is_active", True)
                .limit(1)
                .execute()
            )

            return (
                response.data[0]
                if response and response.data
                else None
            )

        policy = await run_in_threadpool(fetch_policies)

        return {
            "success": True,
            "data": policy,
        }

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to fetch customer policies at this time.",
        )
