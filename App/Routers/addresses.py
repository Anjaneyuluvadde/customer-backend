from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from App.Dependencies.customer_auth import (
    AuthenticatedCustomer,
    get_current_customer,
    resolve_customer_target_id,
)
from Supabase.client import get_supabase_client


router = APIRouter(
    prefix="/api/v1/customer/addresses",
    tags=["Customer Addresses"],
)


class AddressSaveRequest(BaseModel):
    tag: str = "Home"
    house_no: str | None = None
    landmark: str | None = None
    full_address: str
    pincode: str | None = None
    latitude: float | None = None
    longitude: float | None = None


@router.get("")
async def get_customer_addresses(
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def fetch_addresses():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            response = (
                client.table("user_addresses")
                .select("*")
                .in_("user_id", [customer.user_id, target_id])
                .order("created_at", desc=True)
                .execute()
            )
            return response.data or []

        addresses = await run_in_threadpool(fetch_addresses)
        return {
            "success": True,
            "data": addresses,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to fetch addresses: {str(e)}",
        )


@router.post("")
async def save_customer_address(
    payload: AddressSaveRequest,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def save_addr():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            # If saving a tagged address (e.g., Home, Work), delete any existing address with the same tag first
            if payload.tag:
                try:
                    (
                        client.table("user_addresses")
                        .delete()
                        .eq("user_id", target_id)
                        .eq("tag", payload.tag)
                        .execute()
                    )
                except Exception:
                    pass

            insert_data: dict[str, Any] = {
                "user_id": target_id,
                "tag": payload.tag or "Home",
                "full_address": payload.full_address,
            }
            if payload.house_no:
                insert_data["house_no"] = payload.house_no
            if payload.landmark:
                insert_data["landmark"] = payload.landmark
            if payload.pincode:
                insert_data["pincode"] = payload.pincode
            if payload.latitude is not None:
                insert_data["latitude"] = payload.latitude
            if payload.longitude is not None:
                insert_data["longitude"] = payload.longitude

            response = client.table("user_addresses").insert(insert_data).execute()

            # If tag is Home, also sync to profile table address & pincode
            if payload.tag == "Home":
                try:
                    profile_update: dict[str, Any] = {"address": payload.full_address}
                    if payload.pincode:
                        profile_update["pincode"] = payload.pincode
                    client.table("profile").update(profile_update).eq("id", target_id).execute()
                except Exception:
                    pass

            return response.data[0] if (response and response.data) else insert_data

        saved = await run_in_threadpool(save_addr)
        return {
            "success": True,
            "data": saved,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to save address: {str(e)}",
        )


@router.delete("/{address_id}")
async def delete_customer_address(
    address_id: str,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def del_addr():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            resp = (
                client.table("user_addresses")
                .delete()
                .eq("id", address_id)
                .in_("user_id", [customer.user_id, target_id])
                .execute()
            )
            return resp.data

        await run_in_threadpool(del_addr)
        return {
            "success": True,
            "message": "Address deleted successfully",
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to delete address: {str(e)}",
        )
