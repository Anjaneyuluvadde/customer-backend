
from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from Supabase.client import get_supabase_client


router = APIRouter(
    prefix="/api/v1/customer/app-popups",
    tags=["Customer App Popups"],
)


@router.get("")
async def get_customer_app_popups():
    try:
        def fetch_popups():
            client = get_supabase_client()

            return (
                client.table("app_popups")
                .select("title, description, image_url")
                .eq("is_active", True)
                .execute()
            )

        response = await run_in_threadpool(fetch_popups)

        return {
            "success": True,
            "data": response.data or [],
        }

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to fetch app popups at this time.",
        )
