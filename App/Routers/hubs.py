from fastapi import APIRouter, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from Supabase.client import get_supabase_client


router = APIRouter(
    prefix="/api/v1/customer/hubs",
    tags=["Customer Hub Locations"],
)


@router.get("/check-pincode")
async def check_pincode_serviceable(
    pincode: str = Query(..., description="6-digit pincode"),
    address: str | None = Query(None, description="Optional full address string"),
):
    try:
        def check_serviceability():
            client = get_supabase_client()
            clean_pin = "".join(filter(str.isdigit, pincode)).strip()

            # 1. Exact Pincode match
            if len(clean_pin) == 6:
                resp = (
                    client.table("hub_locations")
                    .select("*")
                    .eq("pincode", clean_pin)
                    .eq("is_active", True)
                    .execute()
                )
                if resp.data and len(resp.data) > 0:
                    return {
                        "serviceable": True,
                        "hub": resp.data[0],
                    }

            # 2. Address string fallback
            if address:
                addr_upper = address.upper()
                all_resp = (
                    client.table("hub_locations")
                    .select("*")
                    .eq("is_active", True)
                    .execute()
                )
                if all_resp.data:
                    for h in all_resp.data:
                        loc_name = str(h.get("location_name") or "").upper().strip()
                        if loc_name and loc_name in addr_upper:
                            return {
                                "serviceable": True,
                                "hub": h,
                            }

            return {
                "serviceable": False,
                "hub": None,
            }

        result = await run_in_threadpool(check_serviceability)
        return {
            "success": True,
            **result,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to check pincode: {str(e)}",
        )


@router.get("/locations")
async def get_active_hubs():
    try:
        def fetch_hubs():
            client = get_supabase_client()
            resp = (
                client.table("hub_locations")
                .select("*")
                .eq("is_active", True)
                .execute()
            )
            return resp.data or []

        hubs = await run_in_threadpool(fetch_hubs)
        return {
            "success": True,
            "data": hubs,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to fetch hub locations: {str(e)}",
        )
