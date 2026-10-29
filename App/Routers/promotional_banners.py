
from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from App.Dependencies.customer_auth import (
    AuthenticatedCustomer,
    get_current_customer,
    resolve_customer_target_id,
)
from Supabase.client import get_supabase_client


router = APIRouter(
    prefix="/api/v1/customer/promotional-banners",
    tags=["Customer Promotional Banners"],
)


@router.get("")
async def get_customer_promotional_banners():
    try:
        def fetch_banners():
            client = get_supabase_client()

            return (
                client.table("promotional_banners")
                .select("*")
                .eq("is_active", True)
                .eq("banner_type", "customer_app")
                .order("display_order", desc=False)
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
            detail="Unable to fetch promotional banners at this time.",
        )


@router.get("/relations")
async def get_promotional_banner_relations():
    try:
        def fetch_relations():
            client = get_supabase_client()
            loc_resp = (
                client.table("promotional_banner_locations")
                .select("banner_id, location_id")
                .execute()
            )
            svc_resp = (
                client.table("promotional_banner_services")
                .select("banner_id, service_id")
                .execute()
            )
            return {
                "locations": loc_resp.data or [],
                "services": svc_resp.data or [],
            }

        relations = await run_in_threadpool(fetch_relations)
        return {
            "success": True,
            "data": relations,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to fetch banner relations: {str(e)}",
        )


@router.get("/consumed")
async def get_consumed_promotional_banners(
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def fetch_consumed():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            user_ids = list({customer.user_id, target_id})
            resp = (
                client.table("bookings")
                .select("promotional_banner_id, work_status")
                .in_("user_id", user_ids)
                .not_.is_("promotional_banner_id", "null")
                .execute()
            )
            data = resp.data or []
            consumed_ids = set()
            for row in data:
                ws = str(row.get("work_status") or "").strip().upper()
                if ws == "COMPLETED" and row.get("promotional_banner_id"):
                    consumed_ids.add(row["promotional_banner_id"])
            return list(consumed_ids)

        consumed = await run_in_threadpool(fetch_consumed)
        return {
            "success": True,
            "data": consumed,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to fetch consumed banners: {str(e)}",
        )

