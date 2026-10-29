from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from App.Dependencies.customer_auth import (
    AuthenticatedCustomer,
    get_current_customer,
    resolve_customer_target_id,
)
from Supabase.client import get_supabase_client


router = APIRouter(
    prefix="/api/v1/customer/cart",
    tags=["Customer Cart"],
)


class AddCartItemRequest(BaseModel):
    service_id: str
    title: str
    duration: str | None = None
    price: str | None = None
    image: str | None = None


@router.get("")
async def get_customer_cart(
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def fetch_cart():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            resp = (
                client.table("cart_items")
                .select("id, service_id, title, duration, price, image")
                .in_("user_id", [customer.user_id, target_id])
                .order("created_at", desc=True)
                .execute()
            )
            return resp.data or []

        items = await run_in_threadpool(fetch_cart)
        return {
            "success": True,
            "data": items,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to fetch cart: {str(e)}",
        )


@router.post("/items")
async def add_cart_item(
    payload: AddCartItemRequest,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def insert_item():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            # Check if item is already in cart to prevent duplicates
            existing = (
                client.table("cart_items")
                .select("id")
                .in_("user_id", [customer.user_id, target_id])
                .eq("service_id", payload.service_id)
                .maybe_single()
                .execute()
            )
            if existing and existing.data:
                return existing.data

            data = {
                "user_id": target_id,
                "service_id": payload.service_id,
                "title": payload.title,
                "duration": payload.duration or "",
                "price": payload.price or "",
                "image": payload.image or "",
            }
            resp = client.table("cart_items").insert(data).execute()
            return resp.data[0] if (resp and resp.data) else data

        result = await run_in_threadpool(insert_item)
        return {
            "success": True,
            "data": result,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to add item to cart: {str(e)}",
        )


@router.delete("/items/{service_id}")
async def remove_cart_item(
    service_id: str,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def delete_item():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            resp = (
                client.table("cart_items")
                .delete()
                .in_("user_id", [customer.user_id, target_id])
                .eq("service_id", service_id)
                .execute()
            )
            return resp.data

        await run_in_threadpool(delete_item)
        return {
            "success": True,
            "message": "Item removed from cart",
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to remove item from cart: {str(e)}",
        )


@router.delete("")
async def clear_customer_cart(
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def clear_cart():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            resp = (
                client.table("cart_items")
                .delete()
                .in_("user_id", [customer.user_id, target_id])
                .execute()
            )
            # Also clear any legacy cart table rows if present
            try:
                client.table("cart").delete().in_("user_id", [customer.user_id, target_id]).execute()
            except Exception:
                pass

            return resp.data

        await run_in_threadpool(clear_cart)
        return {
            "success": True,
            "message": "Cart cleared successfully",
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to clear cart: {str(e)}",
        )
