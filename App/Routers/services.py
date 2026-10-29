
from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from Supabase.client import get_supabase_client

router = APIRouter(
    prefix="/api/v1/customer/services",
    tags=["Customer Services"],
)


@router.get("")
async def get_services(
    service_type: str | None = Query(default=None),
    main_category_id: str | None = Query(default=None),
):
    try:
        def fetch_services():
            client = get_supabase_client()

            query = (
                client.table("services")
                .select("*")
                .order("sort_order", desc=False)
            )

            if service_type is not None:
                query = query.eq("service_type", service_type)

            if main_category_id is not None:
                query = query.eq("main_category_id", main_category_id)

            return query.execute()

        response = await run_in_threadpool(fetch_services)

        return {
            "success": True,
            "data": response.data or [],
        }

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to fetch services at this time.",
        )

@router.get("/{service_identifier}")
async def get_service_details(service_identifier: str):
    try:
        def fetch_service():
            client = get_supabase_client()

            # First: find service using slug
            response = (
                client.table("services")
                .select("*")
                .eq("slug", service_identifier)
                .limit(1)
                .execute()
            )

            if response.data:
                return response.data[0]

            # Fallback: find service using UUID
            # Validate before querying a UUID column
            from uuid import UUID

            try:
                UUID(service_identifier)
            except (ValueError, AttributeError):
                return None

            response = (
                client.table("services")
                .select("*")
                .eq("id", service_identifier)
                .limit(1)
                .execute()
            )

            return response.data[0] if response.data else None

        service = await run_in_threadpool(fetch_service)

        if service is None:
            raise HTTPException(
                status_code=404,
                detail="Service not found."
            )

        return {
            "success": True,
            "data": service
        }

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Unable to fetch service details at this time."
        )


@router.get("/{service_id}/videos")
async def get_service_videos(service_id: str):
    try:
        def fetch():
            client = get_supabase_client()
            resp = (
                client.table("service_how_it_works_videos")
                .select("*")
                .eq("service_id", service_id)
                .eq("is_active", True)
                .order("sort_order", desc=False)
                .execute()
            )
            return resp.data or []

        videos = await run_in_threadpool(fetch)
        return {
            "success": True,
            "data": videos,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to fetch service videos: {str(e)}",
        )

