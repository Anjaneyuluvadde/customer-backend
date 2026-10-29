
from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from Supabase.client import get_supabase_client


router = APIRouter(
    prefix="/api/v1/customer/main-categories",
    tags=["Customer Main Categories"],
)


@router.get("")
async def get_main_categories():
    try:
        def fetch_categories():
            client = get_supabase_client()

            return (
                client.table("main_categories")
                .select("*")
                .order("sort_order", desc=False)
                .execute()
            )

        response = await run_in_threadpool(fetch_categories)

        return {
            "success": True,
            "data": response.data or [],
        }

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to fetch main categories at this time.",
        )
