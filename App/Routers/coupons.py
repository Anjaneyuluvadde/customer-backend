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
    prefix="/api/v1/customer/coupons",
    tags=["Customer Coupons"],
)


class ValidateCouponRequest(BaseModel):
    code: str
    phone: str | None = None
    banner_id: str | None = None


@router.post("/validate")
async def validate_coupon(
    payload: ValidateCouponRequest,
):
    try:
        def check_coupon():
            client = get_supabase_client()
            clean_code = payload.code.strip()

            resp = (
                client.table("coupons")
                .select("*")
                .ilike("coupon_code", clean_code)
                .eq("is_active", True)
                .eq("is_used", False)
                .limit(1)
                .execute()
            )

            if not resp.data or len(resp.data) == 0:
                return {
                    "valid": False,
                    "message": "Invalid or expired coupon code.",
                    "coupon": None,
                }

            coupon = resp.data[0]

            # If coupon is tied to a specific phone number
            coupon_phone = coupon.get("phone_number")
            if coupon_phone and payload.phone:
                clean_target_phone = "".join(filter(str.isdigit, str(payload.phone)))[-10:]
                clean_coupon_phone = "".join(filter(str.isdigit, str(coupon_phone)))[-10:]
                if clean_coupon_phone and clean_target_phone != clean_coupon_phone:
                    return {
                        "valid": False,
                        "message": "This coupon is not valid for your account.",
                        "coupon": None,
                    }

            return {
                "valid": True,
                "message": "Coupon applied successfully!",
                "coupon": coupon,
                "discount_percentage": coupon.get("discount_percentage", 0) or 0,
                "discount_amount": coupon.get("discount_amount", 0) or 0,
            }

        res = await run_in_threadpool(check_coupon)
        return {
            "success": True,
            **res,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to validate coupon: {str(e)}",
        )


@router.get("/my-coupons")
async def get_my_coupons(
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def fetch_user_coupons():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            # Check coupons by user_id or by phone
            clean_phone = ""
            if customer.phone:
                clean_phone = "".join(filter(str.isdigit, str(customer.phone)))[-10:]

            query = (
                client.table("coupons")
                .select("*")
                .eq("is_active", True)
                .eq("is_used", False)
            )

            if clean_phone:
                # Phone or user_id match
                resp = query.ilike("phone_number", f"%{clean_phone}%").execute()
            else:
                resp = query.in_("user_id", [customer.user_id, target_id]).execute()

            return resp.data or []

        coupons = await run_in_threadpool(fetch_user_coupons)
        return {
            "success": True,
            "data": coupons,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to fetch coupons: {str(e)}",
        )
