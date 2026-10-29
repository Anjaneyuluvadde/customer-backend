
from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from Supabase.client import get_supabase_client


router = APIRouter(
    prefix="/api/v1/customer/offers",
    tags=["Customer Offers"],
)


@router.get("")
async def get_customer_offers():
    try:
        def fetch_offers():
            client = get_supabase_client()

            return (
                client.table("offers")
                .select(
                    "title, service_type, offer_percentage, description"
                )
                .eq("is_offer_enabled", True)
                .execute()
            )

        response = await run_in_threadpool(fetch_offers)

        return {
            "success": True,
            "data": response.data or [],
        }

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to fetch customer offers at this time.",
        )
