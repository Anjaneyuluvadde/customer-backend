from fastapi import APIRouter, HTTPException, Query, status
from starlette.concurrency import run_in_threadpool

from Supabase.client import get_supabase_client


router = APIRouter(
    prefix="/api/v1/customer/schedule",
    tags=["Customer Scheduling"],
)


@router.get("/config")
async def get_schedule_config():
    """
    Public endpoint to fetch calendar and time slots configuration.
    """
    try:
        def fetch_config():
            client = get_supabase_client()
            resp = client.table("schedule_config").select("*").execute()
            data = resp.data or []
            # Transform key-value config rows into a convenient dictionary
            config_dict = {}
            for row in data:
                key = row.get("config_key")
                val = row.get("config_value")
                if key:
                    config_dict[key] = val
            return config_dict, data

        cfg_dict, raw_data = await run_in_threadpool(fetch_config)
        return {
            "success": True,
            "data": cfg_dict,
            "raw": raw_data,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to fetch schedule configuration: {str(e)}",
        )


@router.get("/capacity-check")
async def check_schedule_capacity(
    booking_date: str = Query(..., description="Date in YYYY-MM-DD or DD/MM/YYYY"),
    hub_name: str = Query(..., description="Hub name"),
    category: str | None = Query(None, description="Main category or service type"),
):
    try:
        def fetch_capacity():
            client = get_supabase_client()

            # 1. Fetch staff count for this hub and category
            staff_count = 1
            query = client.table("hub_category_counts").select("*").ilike("hub", f"%{hub_name.strip()}%")
            if category:
                query = query.ilike("category", f"%{category.strip()}%")
            cat_resp = query.execute()

            if cat_resp.data and len(cat_resp.data) > 0:
                count_val = cat_resp.data[0].get("count")
                if count_val is not None:
                    staff_count = int(count_val)

            # 2. Fetch existing bookings on that date in this hub
            booking_resp = (
                client.table("bookings")
                .select("id, booking_time, work_status")
                .eq("booking_date", booking_date)
                .ilike("hub_name", f"%{hub_name.strip()}%")
                .neq("work_status", "CANCELLED")
                .execute()
            )
            booked_slots: dict[str, int] = {}
            if booking_resp.data:
                for b in booking_resp.data:
                    slot = b.get("booking_time")
                    if slot:
                        booked_slots[slot] = booked_slots.get(slot, 0) + 1

            return staff_count, booked_slots

        staff_limit, slots_used = await run_in_threadpool(fetch_capacity)
        return {
            "success": True,
            "data": {
                "staff_count": staff_limit,
                "booked_slots": slots_used,
            },
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to check capacity: {str(e)}",
        )


@router.get("/date-bookings")
async def get_date_bookings(
    booking_date: str = Query(..., description="Date substring or YYYY-MM-DD"),
):
    try:
        def fetch():
            client = get_supabase_client()
            resp = (
                client.table("bookings")
                .select("id, booking_date, booking_time, work_status, payment_status, hub_name")
                .ilike("booking_date", f"%{booking_date.strip()}%")
                .execute()
            )
            return resp.data or []

        bookings = await run_in_threadpool(fetch)
        return {
            "success": True,
            "data": bookings,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to fetch date bookings: {str(e)}",
        )


@router.get("/hub-category-counts")
async def get_hub_category_counts(
    hub: str = Query(..., description="Hub name to filter category counts"),
):
    try:
        def fetch():
            client = get_supabase_client()
            resp = (
                client.table("hub_category_counts")
                .select("count, category, hub")
                .ilike("hub", hub.strip())
                .execute()
            )
            return resp.data or []

        counts = await run_in_threadpool(fetch)
        return {
            "success": True,
            "data": counts,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to fetch category counts: {str(e)}",
        )

