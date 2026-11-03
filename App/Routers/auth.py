from datetime import datetime, timedelta, timezone
import hashlib
import logging
import os
import re
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, status
import httpx
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from Supabase.client import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/customer/auth",
    tags=["Customer Authentication"],
)

MSG91_AUTH_KEY = os.getenv("MSG91_AUTH_KEY", "").strip()
MSG91_FLOW_ID = os.getenv("MSG91_FLOW_ID", "").strip()


class SendOtpRequest(BaseModel):
    phone: str


class VerifyOtpRequest(BaseModel):
    phone: str
    otp: str


def clean_indian_phone(phone: str) -> str:
    clean_digits = "".join(filter(str.isdigit, str(phone)))[-10:]
    if len(clean_digits) != 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide a valid 10-digit mobile number.",
        )
    return clean_digits


@router.post("/send-otp")
async def send_customer_otp(payload: SendOtpRequest):
    """
    Generate and send 6-digit OTP via MSG91 Flow API.
    Replaces Supabase Edge Function: msg91-hook
    """
    clean_phone = clean_indian_phone(payload.phone)

    # 1. Generate 6-digit OTP
    if clean_phone in ("9999999999", "8888888888"):
        otp = "123456"
    else:
        otp = f"{secrets.randbelow(900000) + 100000}"

    now = datetime.now(timezone.utc)
    now_str = now.isoformat()
    expires_str = (now + timedelta(minutes=10)).isoformat()
    otp_hash = hashlib.sha256(otp.encode("utf-8")).hexdigest()

    # 2. Store OTP hash in database table phone_otp_verifications (using upsert on phone)
    def record_otp():
        client = get_supabase_client()
        client.table("phone_otp_verifications").upsert({
            "phone": clean_phone,
            "otp_hash": otp_hash,
            "created_at": now_str,
            "expires_at": expires_str,
            "attempts": 0,
            "verified_at": None,
        }, on_conflict="phone").execute()

    await run_in_threadpool(record_otp)

    # 3. Dispatch SMS via MSG91 Flow API
    if MSG91_AUTH_KEY and MSG91_FLOW_ID and clean_phone not in ("9999999999", "8888888888"):
        try:
            url = "https://control.msg91.com/api/v5/flow/"
            headers = {
                "authkey": MSG91_AUTH_KEY,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            body = {
                "template_id": MSG91_FLOW_ID,
                "short_url": "0",
                "recipients": [
                    {
                        "mobiles": f"91{clean_phone}",
                        "OTP": otp,
                    }
                ],
            }
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                resp = await http_client.post(url, json=body, headers=headers)
                logger.info(f"MSG91 send-otp response code: {resp.status_code}")
        except Exception as msg_err:
            logger.error(f"Failed to dispatch SMS via MSG91: {msg_err}")
            # Don't fail the API call if SMS gateway blips; OTP is saved in DB

    return {
        "success": True,
        "message": "OTP sent successfully",
    }


@router.post("/verify-otp")
async def verify_customer_otp(payload: VerifyOtpRequest):
    """
    Verifies submitted OTP and generates an authentic Supabase Auth session.
    Replaces Supabase Edge Function: verify-otp
    """
    clean_phone = clean_indian_phone(payload.phone)
    submitted_otp = payload.otp.strip()

    if not submitted_otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP cannot be empty.",
        )

    # 1. Verify OTP
    is_verified = False

    # A. Check test numbers
    if clean_phone in ("9999999999", "8888888888") and submitted_otp in ("123456", "1234"):
        is_verified = True

    # B. Check database records in phone_otp_verifications
    if not is_verified:
        def check_db_otp():
            client = get_supabase_client()
            resp = (
                client.table("phone_otp_verifications")
                .select("*")
                .or_(f"phone.eq.{clean_phone},phone.eq.91{clean_phone},phone.eq.+91{clean_phone}")
                .order("created_at", desc=True)
                .limit(10)
                .execute()
            )
            return resp.data or []

        try:
            db_records = await run_in_threadpool(check_db_otp)
            for r in db_records:
                stored_otp = str(r.get("otp") or r.get("code") or "")
                if stored_otp == submitted_otp:
                    is_verified = True
                    break
                # Check SHA256 match
                h = hashlib.sha256(submitted_otp.encode("utf-8")).hexdigest()
                if str(r.get("otp_hash") or "") in (submitted_otp, h):
                    is_verified = True
                    break
        except Exception as check_err:
            logger.warning(f"Error checking DB OTP records: {check_err}")

    if is_verified:
        try:
            client = get_supabase_client()
            client.table("phone_otp_verifications").update({
                "verified_at": datetime.now(timezone.utc).isoformat()
            }).eq("phone", clean_phone).execute()
        except Exception:
            pass

    # C. Fallback: Check MSG91 OTP verification API if MSG91 was used
    if not is_verified and MSG91_AUTH_KEY:
        try:
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                msg91_url = f"https://control.msg91.com/api/v5/otp/verify?otp={submitted_otp}&mobile={clean_phone}"
                m_resp = await http_client.get(msg91_url, headers={"authkey": MSG91_AUTH_KEY})
                m_data = m_resp.json()

                if m_data.get("type") != "error":
                    is_verified = True
                elif "not found" in str(m_data.get("message", "")).lower():
                    # Retry with 91 prefix
                    msg91_url91 = f"https://control.msg91.com/api/v5/otp/verify?otp={submitted_otp}&mobile=91{clean_phone}"
                    m_resp91 = await http_client.get(msg91_url91, headers={"authkey": MSG91_AUTH_KEY})
                    m_data91 = m_resp91.json()
                    if m_data91.get("type") != "error":
                        is_verified = True
        except Exception as m_err:
            logger.warning(f"MSG91 verify API check failed: {m_err}")

    if not is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OTP. Please try again.",
        )

    # 2. Find or Create User in Supabase Auth & Profile
    def resolve_and_mint_session():
        client = get_supabase_client()
        dummy_email = f"temp_{clean_phone}@neatify.app"
        target_email = dummy_email
        formatted_phone = f"+91{clean_phone}"

        # Check existing profile
        prof_resp = (
            client.table("profile")
            .select("id")
            .eq("phone", clean_phone)
            .maybe_single()
            .execute()
        )

        user_id = None
        if prof_resp and prof_resp.data:
            user_id = str(prof_resp.data.get("id"))
            try:
                user_auth = client.auth.admin.get_user_by_id(user_id)
                if user_auth and user_auth.user and user_auth.user.email:
                    target_email = user_auth.user.email
            except Exception:
                pass

        if not user_id:
            try:
                new_user = client.auth.admin.create_user({
                    "email": dummy_email,
                    "phone": formatted_phone,
                    "phone_confirm": True,
                    "email_confirm": True,
                })
                if new_user and new_user.user:
                    user_id = str(new_user.user.id)
                    client.table("profile").upsert({
                        "id": user_id,
                        "phone": clean_phone,
                        "email": None,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }).execute()
            except Exception as create_err:
                err_str = str(create_err)
                if "already" in err_str or "422" in err_str:
                    target_email = dummy_email
                else:
                    raise create_err

        # 3. Generate MagicLink and verify OTP to mint real Supabase Session
        link_res = client.auth.admin.generate_link({
            "type": "magiclink",
            "email": target_email,
        })

        email_otp = getattr(link_res.properties, "email_otp", None) if hasattr(link_res, "properties") else None
        if not email_otp and isinstance(link_res, dict):
            email_otp = link_res.get("properties", {}).get("email_otp")

        if not email_otp:
            # Fallback retry with dummy email
            link_res = client.auth.admin.generate_link({
                "type": "magiclink",
                "email": dummy_email,
            })
            email_otp = getattr(link_res.properties, "email_otp", None) if hasattr(link_res, "properties") else None
            target_email = dummy_email

        if not email_otp:
            raise ValueError("Failed to extract session token from Supabase Auth admin.")

        session_res = client.auth.verify_otp({
            "email": target_email,
            "token": email_otp,
            "type": "magiclink",
        })

        if not session_res or not session_res.session:
            raise ValueError("Failed to mint active session.")

        session_obj = session_res.session
        user_obj = session_res.user

        return {
            "access_token": session_obj.access_token,
            "refresh_token": session_obj.refresh_token,
            "token_type": "bearer",
            "expires_in": session_obj.expires_in,
            "expires_at": session_obj.expires_at,
            "user": {
                "id": str(user_obj.id),
                "email": user_obj.email,
                "phone": user_obj.phone,
                "user_metadata": user_obj.user_metadata,
            },
        }, {
            "id": str(user_obj.id),
            "email": user_obj.email,
            "phone": user_obj.phone,
        }

    try:
        session_data, user_data = await run_in_threadpool(resolve_and_mint_session)
        return {
            "success": True,
            "session": session_data,
            "user": user_data,
            "message": "OTP verified successfully",
        }
    except Exception as e:
        logger.error(f"Error in verify_customer_otp: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to verify OTP: {str(e)}",
        )
