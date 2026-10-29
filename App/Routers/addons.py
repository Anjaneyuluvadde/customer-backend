
from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from Supabase.client import get_supabase_client


router = APIRouter(
    prefix="/api/v1/customer/addons",
    tags=["Customer Add-ons"],
)


@router.get("")
async def get_addons():
    try:
        def fetch_addons():
            client = get_supabase_client()

            return (
                client.table("add_ons")
                .select("*")
                .eq("is_active", True)
                .order("sort_order", desc=False)
                .execute()
            )

        response = await run_in_threadpool(fetch_addons)

        return {
            "success": True,
            "data": response.data or [],
        }

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to fetch add-ons at this time.",
        )
