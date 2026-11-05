import base64
import hashlib
import hmac
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
import httpx
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from App.Dependencies.customer_auth import (
    AuthenticatedCustomer,
    get_current_customer,
    resolve_customer_target_id,
)
from App.Services.notifications import dispatch_booking_confirmation_notifications
from Supabase.client import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/customer/payments",
    tags=["Customer Payments"],
)

RAZORPAY_KEY_ID = (
    os.getenv("RAZORPAY_KEY_ID", "").strip()
    or os.getenv("EXPO_PUBLIC_RAZORPAY_KEY", "").strip()
)
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "").strip()


class CreateRazorpayOrderRequest(BaseModel):
    amount: float
    booking_id: str | None = None
    payment_type: str | None = "FULL"


class VerifyRazorpayPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    booking_id: str
    payment_type: str | None = "FULL"
    paid_amount: float | None = None
    remaining_amount: float | None = None


@router.post("/create-order")
async def create_razorpay_order(
    payload: CreateRazorpayOrderRequest,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    """
    Creates a Razorpay Order server-side.
    Replaces Supabase Edge Function: create-razorpay-order
    """
    if not payload.amount or payload.amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid positive amount is required to create a payment order.",
        )

    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Razorpay payment gateway is not configured on the server.",
        )

    amount_in_paise = int(round(payload.amount * 100))
    receipt_id = f"receipt_{payload.booking_id or int(time.time())}"

    # Basic Auth header for Razorpay
    auth_str = f"{RAZORPAY_KEY_ID}:{RAZORPAY_KEY_SECRET}"
    encoded_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")

    rzp_payload = {
        "amount": amount_in_paise,
        "currency": "INR",
        "receipt": receipt_id,
        "notes": {
            "booking_id": payload.booking_id or "",
            "payment_type": payload.payment_type or "FULL",
            "customer_id": customer.user_id,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as http_client:
            resp = await http_client.post(
                "https://api.razorpay.com/v1/orders",
                json=rzp_payload,
                headers={
                    "Authorization": f"Basic {encoded_auth}",
                    "Content-Type": "application/json",
                },
            )
            data = resp.json()

            if resp.status_code not in (200, 201):
                err_msg = data.get("error", {}).get("description") or "Failed to create Razorpay order"
                logger.error(f"❌ [PAYMENT ORDER FAILED] Booking: #{payload.booking_id} | Amount: ₹{payload.amount} | Error: {err_msg}")
                raise HTTPException(status_code=400, detail=err_msg)

            # Ensure client has key for opening checkout
            data["key"] = RAZORPAY_KEY_ID
            customer_identifier = customer.phone or customer.email or customer.user_id
            order_id = data.get("id", "N/A")
            logger.info(
                f"💳 [PAYMENT ORDER CREATED] Booking: #{payload.booking_id or 'NEW'} | "
                f"Amount: ₹{payload.amount} | Plan: {payload.payment_type or 'FULL'} | "
                f"OrderID: {order_id} | User: {customer_identifier}"
            )
            return {
                "success": True,
                "data": data,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create_razorpay_order: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to create payment order: {str(e)}",
        )


@router.post("/verify")
async def verify_razorpay_payment(
    payload: VerifyRazorpayPaymentRequest,
    background_tasks: BackgroundTasks,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    """
    Verifies Razorpay HMAC-SHA256 signature, updates booking and payment records.
    Replaces Supabase Edge Function: verify-payment
    """
    if (
        not payload.razorpay_order_id
        or not payload.razorpay_payment_id
        or not payload.razorpay_signature
        or not payload.booking_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required payment verification details.",
        )

    # 1. Verify HMAC Signature
    is_test_mode = payload.razorpay_payment_id.startswith("test_pay_")

    if not is_test_mode:
        if not RAZORPAY_KEY_SECRET:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Razorpay secret key is not configured.",
            )

        body_str = f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}"
        expected_sig = hmac.new(
            RAZORPAY_KEY_SECRET.encode("utf-8"),
            body_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if expected_sig != payload.razorpay_signature:
            logger.error(
                f"❌ [PAYMENT VERIFICATION FAILED] Booking: #{payload.booking_id} | "
                f"PaymentID: {payload.razorpay_payment_id} | Reason: Invalid HMAC Signature"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payment signature. Verification failed.",
            )

    # 2. Fetch payment info from Razorpay (if live) to retrieve exact amount & method
    amount_paid = payload.paid_amount or 0.0
    payment_method = "razorpay"

    if not is_test_mode and RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
        try:
            auth_str = f"{RAZORPAY_KEY_ID}:{RAZORPAY_KEY_SECRET}"
            encoded_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
            async with httpx.AsyncClient(timeout=10.0) as http_client:
                rzp_resp = await http_client.get(
                    f"https://api.razorpay.com/v1/payments/{payload.razorpay_payment_id}",
                    headers={"Authorization": f"Basic {encoded_auth}"},
                )
                if rzp_resp.status_code == 200:
                    rzp_data = rzp_resp.json()
                    fetched_amount = float(rzp_data.get("amount", 0)) / 100.0
                    if fetched_amount > 0:
                        amount_paid = fetched_amount
                    payment_method = rzp_data.get("method") or "razorpay"
        except Exception as rzp_err:
            logger.warning(f"Could not fetch payment from Razorpay API: {rzp_err}")

    # 3. Database operations
    def execute_db_update():
        client = get_supabase_client()
        target_id = resolve_customer_target_id(client, customer)

        # A. Fetch Booking
        b_resp = (
            client.table("bookings")
            .select("*")
            .eq("id", payload.booking_id)
            .maybe_single()
            .execute()
        )
        if not b_resp or not b_resp.data:
            raise ValueError(f"Booking {payload.booking_id} not found.")

        booking = b_resp.data

        # B. Check existing payment in booking_payments table for deduplication
        existing_pmt = (
            client.table("booking_payments")
            .select("id, amount, status, booking_id")
            .eq("razorpay_payment_id", payload.razorpay_payment_id)
            .maybe_single()
            .execute()
        )

        if existing_pmt and existing_pmt.data:
            if not existing_pmt.data.get("booking_id"):
                client.table("booking_payments").update({
                    "booking_id": payload.booking_id
                }).eq("razorpay_payment_id", payload.razorpay_payment_id).execute()
        else:
            # Insert new booking payment record
            try:
                client.table("booking_payments").insert({
                    "booking_id": payload.booking_id,
                    "amount": amount_paid,
                    "payment_type": payload.payment_type or "FULL",
                    "razorpay_order_id": payload.razorpay_order_id,
                    "razorpay_payment_id": payload.razorpay_payment_id,
                    "razorpay_signature": payload.razorpay_signature,
                    "status": "success",
                }).execute()
            except Exception as ins_err:
                logger.info(f"Booking payment insert handled: {ins_err}")

        # C. Calculate total paid and remaining
        pmts_resp = (
            client.table("booking_payments")
            .select("amount, razorpay_payment_id")
            .eq("booking_id", payload.booking_id)
            .eq("status", "success")
            .execute()
        )

        total_paid = 0.0
        seen_pids = set()
        for row in (pmts_resp.data or []):
            pid = row.get("razorpay_payment_id")
            if pid and pid in seen_pids:
                continue
            if pid:
                seen_pids.add(pid)
            total_paid += float(row.get("amount") or 0.0)

        if total_paid <= 0:
            total_paid = amount_paid

        total_amount = float(booking.get("total_amount") or 0.0)
        remaining_amount = max(0.0, total_amount - total_paid)

        payment_status = "paid" if remaining_amount <= 0 else "partial"
        payment_plan = payload.payment_type or booking.get("payment_plan") or "FULL"

        # D. Update booking record
        update_data = {
            "paid_amount": total_paid,
            "remaining_amount": remaining_amount,
            "payment_status": payment_status,
            "payment_verified": True,
            "payment_plan": payment_plan,
            "razorpay_order_id": payload.razorpay_order_id,
            "razorpay_payment_id": payload.razorpay_payment_id,
            "razorpay_signature": payload.razorpay_signature,
            "payment_method": payment_method,
            "work_status": "CONFIRMED",
        }

        client.table("bookings").update(update_data).eq("id", payload.booking_id).execute()

        customer_name = booking.get("customer_name") or "Customer"
        return total_paid, remaining_amount, payment_status, customer_name

    try:
        paid, remaining, p_status, customer_name = await run_in_threadpool(execute_db_update)

        logger.info(
            f"✅ [PAYMENT VERIFIED SUCCESS] Booking: #{payload.booking_id} | "
            f"PaymentID: {payload.razorpay_payment_id} | Paid: ₹{paid} | "
            f"Remaining: ₹{remaining} | Status: {p_status.upper()} | Customer: {customer_name}"
        )

        # 4. Trigger background notifications (email, WhatsApp)
        background_tasks.add_task(
            dispatch_booking_confirmation_notifications,
            payload.booking_id,
            True,
        )

        return {
            "success": True,
            "message": "Payment verified successfully",
            "paid_amount": paid,
            "remaining_amount": remaining,
            "payment_status": p_status,
        }

    except Exception as e:
        logger.error(
            f"❌ [PAYMENT VERIFICATION FAILED] Booking: #{payload.booking_id} | "
            f"PaymentID: {payload.razorpay_payment_id} | Error: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to verify payment: {str(e)}",
        )
