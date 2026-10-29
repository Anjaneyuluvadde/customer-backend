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
    Public endpoint to fetch active app policies, terms, and cancellation rules.
    """
    try:
        def fetch_policies():
            client = get_supabase_client()
            response = (
                client.table("app_policies")
                .select("*")
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            return response.data[0] if (response and response.data) else None

        policy = await run_in_threadpool(fetch_policies)
        return {
            "success": True,
            "data": policy,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to fetch policies: {str(e)}",
        )
