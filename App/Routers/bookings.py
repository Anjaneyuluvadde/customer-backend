import logging
from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from App.Dependencies.customer_auth import (
    AuthenticatedCustomer,
    get_current_customer,
    resolve_customer_target_id,
)
from Supabase.client import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/customer/bookings",
    tags=["Customer Bookings"],
)


class CreateBookingRequest(BaseModel):
    customer_name: str
    email: str | None = None
    phone_number: str
    full_address: str
    services: list[Any] | None = None
    booking_date: str
    booking_time: str
    total_amount: float
    paid_amount: float | None = 0
    remaining_amount: float | None = 0
    payment_status: str = "PENDING"
    payment_method: str = "COD"
    payment_plan: str | None = "FULL"
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None
    razorpay_signature: str | None = None
    coupon_code: str | None = None
    coupon_discount_percentage: float | None = None
    coupon_discount_amount: float | None = None
    wallet_deduction: float | None = 0
    hub_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    promotional_banner_id: str | None = None
    terms_accepted: bool | None = True


class CancelBookingRequest(BaseModel):
    cancel_reason: str = "Customer requested cancellation"


class ChecklistItemRequest(BaseModel):
    task_index: int
    task_title: str
    customer_completed: bool = True
    partner_verified: bool | None = False


class SubmitChecklistRequest(BaseModel):
    items: list[ChecklistItemRequest]


class SubmitReviewRequest(BaseModel):
    rating: float | int
    comment: str | None = None


class UpdateBookingPaymentRequest(BaseModel):
    payment_status: str | None = None
    work_status: str | None = None
    razorpay_payment_id: str | None = None
    razorpay_order_id: str | None = None
    razorpay_signature: str | None = None
    payment_verified: bool | None = None
    paid_amount: float | None = None
    remaining_amount: float | None = None
    payment_plan: str | None = None
    payment_type: str | None = None


@router.post("/create")
async def create_booking(
    payload: CreateBookingRequest,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def execute_create():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            # Auto-save / sync profile with name, phone, address
            try:
                prof_data: dict[str, Any] = {
                    "full_name": payload.customer_name,
                    "phone": payload.phone_number,
                    "address": payload.full_address,
                }
                if payload.email:
                    prof_data["email"] = payload.email
                client.table("profile").update(prof_data).eq("id", target_id).execute()
            except Exception:
                pass

            now_str = datetime.now(timezone.utc).isoformat()

            booking_dict: dict[str, Any] = {
                "user_id": target_id,
                "customer_name": payload.customer_name,
                "phone_number": payload.phone_number,
                "full_address": payload.full_address,
                "services": payload.services or [],
                "booking_date": payload.booking_date,
                "booking_time": payload.booking_time,
                "total_amount": payload.total_amount,
                "paid_amount": payload.paid_amount or 0,
                "remaining_amount": payload.remaining_amount or 0,
                "payment_status": payload.payment_status,
                "payment_method": payload.payment_method,
                "payment_plan": payload.payment_plan,
                "work_status": "PENDING",
                "created_at": now_str,
                "terms_accepted": payload.terms_accepted,
                "terms_accepted_at": now_str if payload.terms_accepted else None,
            }

            if payload.email:
                booking_dict["email"] = payload.email
            if payload.razorpay_order_id:
                booking_dict["razorpay_order_id"] = payload.razorpay_order_id
            if payload.razorpay_payment_id:
                booking_dict["razorpay_payment_id"] = payload.razorpay_payment_id
            if payload.razorpay_signature:
                booking_dict["razorpay_signature"] = payload.razorpay_signature
            if payload.coupon_code:
                booking_dict["coupon_code"] = payload.coupon_code
            if payload.coupon_discount_percentage is not None:
                booking_dict["coupon_discount_percentage"] = payload.coupon_discount_percentage
            if payload.coupon_discount_amount is not None:
                booking_dict["coupon_discount_amount"] = payload.coupon_discount_amount
            if payload.hub_name:
                booking_dict["hub_name"] = payload.hub_name
            if payload.latitude is not None:
                booking_dict["latitude"] = payload.latitude
            if payload.longitude is not None:
                booking_dict["longitude"] = payload.longitude
            if payload.promotional_banner_id:
                booking_dict["promotional_banner_id"] = payload.promotional_banner_id

            # Insert into bookings table
            resp = client.table("bookings").insert(booking_dict).execute()
            created = resp.data[0] if (resp and resp.data) else booking_dict
            booking_uuid = created.get("id")

            # Handle wallet deduction
            if payload.wallet_deduction and payload.wallet_deduction > 0 and booking_uuid:
                try:
                    w_resp = client.table("wallet").select("balance").eq("user_id", target_id).maybe_single().execute()
                    current_bal = (w_resp.data.get("balance", 0) or 0) if (w_resp and w_resp.data) else 0
                    new_bal = max(0.0, current_bal - payload.wallet_deduction)
                    client.table("wallet").update({"balance": new_bal}).eq("user_id", target_id).execute()

                    client.table("wallet_transactions").insert({
                        "user_id": target_id,
                        "amount": -abs(payload.wallet_deduction),
                        "transaction_type": "booking_payment",
                        "description": f"Discount applied to booking #{booking_uuid}",
                    }).execute()
                except Exception:
                    pass

            # Mark coupon as used if manual coupon was used
            if payload.coupon_code:
                try:
                    client.table("coupons").update({"is_used": True}).ilike("coupon_code", payload.coupon_code.strip()).execute()
                except Exception:
                    pass

            # Clear cart for user
            try:
                client.table("cart_items").delete().in_("user_id", [customer.user_id, target_id]).execute()
            except Exception:
                pass

            return created

        booking = await run_in_threadpool(execute_create)
        booking_uuid = booking.get("id") or "UNKNOWN"
        logger.info(
            f"📦 [BOOKING CREATED] Booking: #{booking_uuid} | "
            f"Customer: {payload.customer_name} ({payload.phone_number}) | "
            f"Total: ₹{payload.total_amount} | Plan: {payload.payment_plan or 'FULL'}"
        )
        return {
            "success": True,
            "data": booking,
        }

    except Exception as e:
        logger.error(f"❌ [BOOKING CREATION FAILED] Customer: {payload.customer_name} | Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to create booking: {str(e)}",
        )


@router.get("/{booking_id}")
async def get_booking_details(
    booking_id: str,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def fetch_detail():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            # Query booking by id
            resp = (
                client.table("bookings")
                .select("*")
                .eq("id", booking_id)
                .maybe_single()
                .execute()
            )
            if not resp or not resp.data:
                raise ValueError("Booking not found")

            booking = resp.data

            # Fetch assigned staff details if staff is assigned
            staff_info = None
            assigned_staff_id = booking.get("assigned_staff_id")
            if assigned_staff_id:
                staff_resp = (
                    client.table("staff_profile")
                    .select("id, name, phone, avatar_url, role, is_available")
                    .eq("id", assigned_staff_id)
                    .maybe_single()
                    .execute()
                )
                if staff_resp and staff_resp.data:
                    staff_info = staff_resp.data

            return booking, staff_info

        b_data, s_info = await run_in_threadpool(fetch_detail)
        return {
            "success": True,
            "data": b_data,
            "staff": s_info,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to fetch booking details: {str(e)}",
        )


@router.post("/{booking_id}/cancel")
async def cancel_booking(
    booking_id: str,
    payload: CancelBookingRequest,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def do_cancel():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            # Check if staff is already assigned or booking cannot be cancelled
            b_check = (
                client.table("bookings")
                .select("assigned_staff_id, assigned_staff_email, assigned_staff_name, work_status")
                .eq("id", booking_id)
                .maybe_single()
                .execute()
            )
            if b_check and b_check.data:
                b_info = b_check.data
                if (
                    b_info.get("assigned_staff_id")
                    or b_info.get("assigned_staff_email")
                    or b_info.get("assigned_staff_name")
                ):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot cancel booking: A service partner has already been assigned to this booking.",
                    )
                if b_info.get("work_status") in ("COMPLETED", "CANCELLED", "UNDER_REVIEW"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Cannot cancel booking with status {b_info.get('work_status')}.",
                    )

            now_str = datetime.now(timezone.utc).isoformat()

            # Update booking to cancelled
            update_data = {
                "work_status": "CANCELLED",
                "cancel_requested": True,
                "cancel_reason": payload.cancel_reason,
                "cancel_time": now_str,
                "refund_status": "PENDING",
            }

            resp = (
                client.table("bookings")
                .update(update_data)
                .eq("id", booking_id)
                .in_("user_id", [customer.user_id, target_id])
                .execute()
            )
            return resp.data[0] if (resp and resp.data) else update_data

        cancelled = await run_in_threadpool(do_cancel)
        return {
            "success": True,
            "data": cancelled,
            "message": "Booking cancelled successfully",
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to cancel booking: {str(e)}",
        )


@router.get("/{booking_id}/checklist")
async def get_booking_checklist(
    booking_id: str,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def fetch_checklist():
            client = get_supabase_client()
            resp = (
                client.table("booking_checklists")
                .select("*")
                .eq("booking_id", booking_id)
                .order("task_index", desc=False)
                .execute()
            )
            return resp.data or []

        items = await run_in_threadpool(fetch_checklist)
        return {
            "success": True,
            "data": items,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to fetch checklist: {str(e)}",
        )


@router.post("/{booking_id}/checklist")
async def submit_booking_checklist(
    booking_id: str,
    payload: SubmitChecklistRequest,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def save_checklist():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            now_str = datetime.now(timezone.utc).isoformat()

            for item in payload.items:
                row = {
                    "booking_id": booking_id,
                    "task_index": item.task_index,
                    "task_title": item.task_title,
                    "customer_completed": item.customer_completed,
                    "partner_verified": item.partner_verified,
                    "updated_at": now_str,
                }
                try:
                    client.table("booking_checklists").upsert(
                        row, on_conflict="booking_id,task_index"
                    ).execute()
                except Exception:
                    try:
                        client.table("booking_checklists").insert(row).execute()
                    except Exception:
                        pass

            # Mark checklist_submitted = 'TRUE' and complete booking
            client.table("bookings").update({
                "checklist_submitted": "TRUE",
                "work_status": "COMPLETED",
                "updated_at": now_str,
            }).eq("id", booking_id).execute()

            return True

        await run_in_threadpool(save_checklist)
        return {
            "success": True,
            "message": "Checklist submitted successfully",
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to submit checklist: {str(e)}",
        )


@router.get("/{booking_id}/reviews")
async def get_booking_review(
    booking_id: str,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def fetch_review():
            client = get_supabase_client()
            resp = (
                client.table("reviews")
                .select("*")
                .eq("booking_id", booking_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            return resp.data[0] if (resp and resp.data and len(resp.data) > 0) else None

        rev = await run_in_threadpool(fetch_review)
        return {
            "success": True,
            "data": rev,
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to fetch review: {str(e)}",
        )


@router.post("/{booking_id}/reviews")
async def submit_booking_review(
    booking_id: str,
    payload: SubmitReviewRequest,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def save_review():
            client = get_supabase_client()
            target_id = resolve_customer_target_id(client, customer)

            # Ensure rating is stored as a valid integer (1 to 5) for PostgreSQL integer column
            try:
                rating_int = int(round(float(payload.rating)))
            except Exception:
                rating_int = 5
            rating_int = max(1, min(5, rating_int))

            # Check if review already exists
            existing = (
                client.table("reviews")
                .select("id")
                .eq("booking_id", booking_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )

            if existing and existing.data and len(existing.data) > 0:
                review_id = existing.data[0]["id"]
                resp = (
                    client.table("reviews")
                    .update({
                        "rating": rating_int,
                        "comment": payload.comment or "",
                    })
                    .eq("id", review_id)
                    .execute()
                )
            else:
                resp = (
                    client.table("reviews")
                    .insert({
                        "booking_id": booking_id,
                        "user_id": target_id,
                        "rating": rating_int,
                        "comment": payload.comment or "",
                    })
                    .execute()
                )

            logger.info(
                f"⭐ [REVIEW SUBMITTED] Booking: #{booking_id[:8]} | Rating: {rating_int}★ | User: {customer.phone or target_id}"
            )
            return resp.data[0] if (resp and resp.data and len(resp.data) > 0) else None

        saved = await run_in_threadpool(save_review)
        return {
            "success": True,
            "data": saved,
            "message": "Review submitted successfully",
        }

    except Exception as e:
        logger.error(f"❌ [REVIEW ERROR] Booking: #{booking_id[:8]} | Error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to submit review: {str(e)}",
        )


@router.post("/{booking_id}/payment-status")
async def update_booking_payment_status(
    booking_id: str,
    payload: UpdateBookingPaymentRequest,
    customer: AuthenticatedCustomer = Depends(get_current_customer),
):
    try:
        def execute_update():
            client = get_supabase_client()
            update_data = payload.model_dump(exclude_unset=True)
            if not update_data:
                return {}

            resp = (
                client.table("bookings")
                .update(update_data)
                .eq("id", booking_id)
                .execute()
            )
            return resp.data[0] if (resp and resp.data) else update_data

        result = await run_in_threadpool(execute_update)

        p_status = (payload.payment_status or "unknown").lower()
        w_status = payload.work_status or "unknown"
        if p_status in ("failed", "cancelled") or "FAIL" in w_status.upper() or "CANCEL" in w_status.upper():
            logger.warning(
                f"❌ [PAYMENT FAILED / CANCELLED] Booking: #{booking_id} | "
                f"Status: {payload.payment_status or p_status} | WorkStatus: {w_status}"
            )
        else:
            logger.info(
                f"🔄 [PAYMENT STATUS UPDATED] Booking: #{booking_id} | "
                f"Status: {payload.payment_status} | WorkStatus: {w_status}"
            )

        return {
            "success": True,
            "data": result,
            "message": "Payment status updated",
        }
    except Exception as e:
        logger.error(f"❌ [PAYMENT STATUS UPDATE ERROR] Booking: #{booking_id} | Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to update payment status: {str(e)}",
        )

