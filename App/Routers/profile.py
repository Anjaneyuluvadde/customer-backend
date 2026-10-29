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
    prefix="/api/v1/customer/profile",
    tags=["Customer Profile"],
)


class UpdateProfileRequest(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    pincode: str | None = None
    service_selected: str | None = None
    promotional_banner_selected: str | None = None
    referral_code: str | None = None


@router.get("")
async def get_customer_profile(
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def fetch_data():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            # 1. Fetch Profile
            profile_resp = (
                client.table("profile")
                .select("*")
                .eq("id", target_id)
                .maybe_single()
                .execute()
            )
            profile_data = profile_resp.data if profile_resp else None

            # Fallback by phone if not found by ID
            if not profile_data and customer.phone:
                clean_phone = "".join(filter(str.isdigit, str(customer.phone)))[-10:]
                if clean_phone:
                    phone_resp = (
                        client.table("profile")
                        .select("*")
                        .ilike("phone", f"%{clean_phone}%")
                        .order("created_at", desc=True)
                        .limit(1)
                        .execute()
                    )
                    if phone_resp.data and len(phone_resp.data) > 0:
                        profile_data = phone_resp.data[0]
                        target_id = str(profile_data.get("id"))

            # 2. Fetch Wallet
            wallet_resp = (
                client.table("wallet")
                .select("balance")
                .eq("user_id", target_id)
                .maybe_single()
                .execute()
            )
            wallet_balance = 0
            if wallet_resp and wallet_resp.data:
                wallet_balance = wallet_resp.data.get("balance", 0) or 0
            else:
                # Auto-initialize wallet if missing
                try:
                    client.table("wallet").insert({"user_id": target_id, "balance": 0}).execute()
                except Exception:
                    pass

            return profile_data, wallet_balance, target_id

        profile, wallet_bal, resolved_id = await run_in_threadpool(fetch_data)

        return {
            "success": True,
            "data": profile,
            "resolved_user_id": resolved_id,
            "wallet_balance": wallet_bal,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to fetch profile: {str(e)}",
        )


@router.put("")
async def update_customer_profile(
    payload: UpdateProfileRequest,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def save_profile():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            update_dict = payload.model_dump(exclude_unset=True)

            if not update_dict:
                return None

            # Check if profile row exists
            existing = (
                client.table("profile")
                .select("id")
                .eq("id", target_id)
                .maybe_single()
                .execute()
            )

            if existing and existing.data:
                resp = (
                    client.table("profile")
                    .update(update_dict)
                    .eq("id", target_id)
                    .execute()
                )
            else:
                # Upsert / insert new profile
                update_dict["id"] = target_id
                resp = client.table("profile").insert(update_dict).execute()

            return resp.data[0] if (resp and resp.data and len(resp.data) > 0) else update_dict

        updated = await run_in_threadpool(save_profile)

        return {
            "success": True,
            "data": updated,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to update profile: {str(e)}",
        )


@router.get("/validate-referral")
async def validate_referral_code(
    code: str = Query(..., description="Referral code to check"),
):
    try:
        def check():
            client = get_supabase_client()
            resp = (
                client.table("profile")
                .select("id")
                .eq("referral_code", code.strip().upper())
                .maybe_single()
                .execute()
            )
            return resp.data

        data = await run_in_threadpool(check)
        return {
            "success": True,
            "valid": bool(data),
            "referrer_id": data.get("id") if data else None,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to validate referral code: {str(e)}",
        )


class SavePushTokenRequest(BaseModel):
    token: str
    platform: str = "android"


@router.post("/push-token")
async def save_push_token(
    payload: SavePushTokenRequest,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def save():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            # Clear old token associations
            client.table("push_tokens").delete().eq("token", payload.token).execute()

            # Upsert for current user
            resp = (
                client.table("push_tokens")
                .upsert({
                    "user_id": target_id,
                    "token": payload.token,
                    "platform": payload.platform,
                }, on_conflict="user_id")
                .execute()
            )
            return resp.data

        saved = await run_in_threadpool(save)
        return {
            "success": True,
            "data": saved,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to save push token: {str(e)}",
        )


@router.delete("/push-token")
async def remove_push_token(
    token: str = Query(..., description="Device push token to remove"),
):
    try:
        def remove():
            client = get_supabase_client()
            resp = client.table("push_tokens").delete().eq("token", token).execute()
            return resp.data

        await run_in_threadpool(remove)
        return {
            "success": True,
            "message": "Push token removed",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to remove push token: {str(e)}",
        )

