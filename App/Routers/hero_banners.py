
from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from Supabase.client import get_supabase_client


router = APIRouter(
    prefix="/api/v1/customer/hero-banners",
    tags=["Customer Hero Banners"],
)


@router.get("")
async def get_customer_hero_banners():
    try:
        def fetch_banners():
            client = get_supabase_client()

            return (
                client.table("hero_banners")
                .select("image_path")
                .eq("is_active", True)
                .order("priority", desc=False)
                .execute()
            )

        response = await run_in_threadpool(fetch_banners)

        return {
            "success": True,
            "data": response.data or [],
        }

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to fetch hero banners at this time.",
        )
