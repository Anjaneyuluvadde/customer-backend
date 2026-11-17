
import logging
import os
from datetime import date, datetime
from typing import Any

import httpx
from starlette.concurrency import run_in_threadpool

from Supabase.client import get_supabase_client


logger = logging.getLogger(__name__)


# ============================================================
# MSG91 WHATSAPP CONFIGURATION
# ============================================================

MSG91_AUTH_KEY = os.getenv("MSG91_AUTH_KEY", "").strip()

MSG91_WHATSAPP_INTEGRATED_NUMBER = os.getenv(
    "MSG91_WHATSAPP_INTEGRATED_NUMBER", ""
).strip()

MSG91_WHATSAPP_TEMPLATE_NAME = os.getenv(
    "MSG91_WHATSAPP_TEMPLATE_NAME", ""
).strip()

MSG91_WHATSAPP_TEMPLATE_NAMESPACE = os.getenv(
    "MSG91_WHATSAPP_TEMPLATE_NAMESPACE", ""
).strip()

MSG91_WHATSAPP_TEMPLATE_LANGUAGE = os.getenv(
    "MSG91_WHATSAPP_TEMPLATE_LANGUAGE", "en"
).strip()

MSG91_WHATSAPP_API_URL = (
    "https://api.msg91.com/api/v5/"
    "whatsapp/whatsapp-outbound-message/bulk/"
)


# ============================================================
# PHONE NORMALIZATION
# ============================================================

def normalize_indian_phone(phone: Any) -> str | None:
    digits = "".join(
        char for char in str(phone or "") if char.isdigit()
    )

    if len(digits) == 10:
        normalized = f"91{digits}"
    elif len(digits) == 11 and digits.startswith("0"):
        normalized = f"91{digits[1:]}"
    elif len(digits) == 12 and digits.startswith("91"):
        normalized = digits
    else:
        return None

    if normalized[2] not in "6789":
        return None

    return normalized


# ============================================================
# SERVICE NAME FORMATTING
# ============================================================

def format_booking_services(services: Any) -> str:
    if not isinstance(services, list) or not services:
        return "Cleaning Service"

    names = []

    for service in services:
        if isinstance(service, dict):
            name = (
                service.get("title")
                or service.get("name")
                or service.get("service_name")
            )
            if name:
                names.append(str(name).strip())

        elif isinstance(service, str) and service.strip():
            names.append(service.strip())

    return ", ".join(names) if names else "Cleaning Service"


# ============================================================
# BOOKING DATE AND TIME
# ============================================================

def format_booking_schedule(
    booking_date: Any,
    booking_time: Any,
) -> str:
    date_text = str(booking_date or "").strip()
    time_text = str(booking_time or "").strip()

    if date_text:
        try:
            parsed_date = date.fromisoformat(date_text)
            date_text = parsed_date.strftime("%d %B %Y")
        except ValueError:
            pass

    if not date_text:
        date_text = "Date not specified"

    if not time_text:
        time_text = "Time not specified"

    return f"{date_text} at {time_text}"


# ============================================================
# SEND WHATSAPP BOOKING CONFIRMATION
# ============================================================

async def send_booking_whatsapp(
    booking: dict[str, Any],
) -> bool:

    config = {
        "MSG91_AUTH_KEY": MSG91_AUTH_KEY,
        "MSG91_WHATSAPP_INTEGRATED_NUMBER":
            MSG91_WHATSAPP_INTEGRATED_NUMBER,
        "MSG91_WHATSAPP_TEMPLATE_NAME":
            MSG91_WHATSAPP_TEMPLATE_NAME,
        "MSG91_WHATSAPP_TEMPLATE_NAMESPACE":
            MSG91_WHATSAPP_TEMPLATE_NAMESPACE,
        "MSG91_WHATSAPP_TEMPLATE_LANGUAGE":
            MSG91_WHATSAPP_TEMPLATE_LANGUAGE,
    }

    missing = [
        key for key, value in config.items() if not value
    ]

    if missing:
        logger.warning(
            "[BookingWhatsApp] Missing configuration: %s",
            ", ".join(missing),
        )
        return False

    if MSG91_WHATSAPP_TEMPLATE_NAME != "booking_confirmation":
        logger.error(
            "[BookingWhatsApp] Expected booking_confirmation "
            "template, received %s",
            MSG91_WHATSAPP_TEMPLATE_NAME,
        )
        return False

    booking_id = str(booking.get("id") or "").strip()

    phone = normalize_indian_phone(
        booking.get("phone_number")
    )

    if not booking_id or not phone:
        logger.warning(
            "[BookingWhatsApp] Missing booking ID or valid phone "
            "for booking %s",
            booking_id,
        )
        return False

    # --------------------------------------------------------
    # MAP THE THREE APPROVED TEMPLATE VARIABLES
    # --------------------------------------------------------

    customer_name = (
        str(booking.get("customer_name") or "").strip()
        or "Customer"
    )

    service_name = format_booking_services(
        booking.get("services")
    )

    schedule = format_booking_schedule(
        booking.get("booking_date"),
        booking.get("booking_time"),
    )

    # --------------------------------------------------------
    # MSG91 OFFICIAL TEMPLATE PAYLOAD
    # --------------------------------------------------------

    payload = {
        "integrated_number":
            MSG91_WHATSAPP_INTEGRATED_NUMBER,

        "content_type": "template",

        "payload": {
            "messaging_product": "whatsapp",
            "type": "template",

            "template": {
                "name": MSG91_WHATSAPP_TEMPLATE_NAME,

                "language": {
                    "code": MSG91_WHATSAPP_TEMPLATE_LANGUAGE,
                    "policy": "deterministic",
                },

                "namespace":
                    MSG91_WHATSAPP_TEMPLATE_NAMESPACE,

                "to_and_components": [
                    {
                        "to": [phone],

                        "components": {
                            "body_1": {
                                "type": "text",
                                "value": customer_name,
                            },

                            "body_2": {
                                "type": "text",
                                "value": service_name,
                            },

                            "body_3": {
                                "type": "text",
                                "value": schedule,
                            },
                        },
                    }
                ],
            },
        },
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "authkey": MSG91_AUTH_KEY,
    }

    # --------------------------------------------------------
    # SEND WHATSAPP MESSAGE
    # --------------------------------------------------------

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                MSG91_WHATSAPP_API_URL,
                json=payload,
                headers=headers,
            )

        if not 200 <= response.status_code < 300:
            logger.error(
                "[BookingWhatsApp] MSG91 HTTP error: "
                "booking=%s status=%s response=%s",
                booking_id,
                response.status_code,
                response.text[:500],
            )
            return False

        try:
            result = response.json()
        except ValueError:
            logger.error(
                "[BookingWhatsApp] Invalid JSON response "
                "for booking %s",
                booking_id,
            )
            return False

        if not isinstance(result, dict):
            logger.error(
                "[BookingWhatsApp] Unexpected response "
                "for booking %s",
                booking_id,
            )
            return False

        if (
            result.get("hasError") is True
            or result.get("errors")
            or result.get("status") != "success"
        ):
            logger.error(
                "[BookingWhatsApp] MSG91 did not accept "
                "booking %s: %s",
                booking_id,
                str(result)[:500],
            )
            return False

        logger.info(
            "[BookingWhatsApp] Request accepted for booking %s. "
            "Request ID: %s",
            booking_id,
            result.get("request_id", "N/A"),
        )

        return True

    except httpx.HTTPError:
        logger.exception(
            "[BookingWhatsApp] HTTP failure for booking %s",
            booking_id,
        )
        return False

    except Exception:
        logger.exception(
            "[BookingWhatsApp] Unexpected failure for booking %s",
            booking_id,
        )
        return False


# ============================================================
# EXISTING PAYMENT CALLBACK DISPATCHER
# ============================================================

async def dispatch_booking_confirmation_notifications(
    booking_id: str,
    payment_verified: bool = True,
) -> None:

    try:
        def fetch_booking():
            client = get_supabase_client()

            response = (
                client.table("bookings")
                .select(
                    "id, customer_name, phone_number, email, "
                    "services, booking_date, booking_time, "
                    "payment_status, payment_verified"
                )
                .eq("id", booking_id)
                .maybe_single()
                .execute()
            )

            return response.data if response else None

        booking = await run_in_threadpool(fetch_booking)

        if not booking:
            logger.warning(
                "[BookingNotifications] Booking not found: %s",
                booking_id,
            )
            return

        if (
            not payment_verified
            or booking.get("payment_verified") is not True
        ):
            logger.warning(
                "[BookingNotifications] Payment not verified "
                "for booking %s",
                booking_id,
            )
            return

        sent = await send_booking_whatsapp(booking)

        if sent:
            logger.info(
                "[BookingNotifications] WhatsApp request "
                "accepted for booking %s",
                booking_id,
            )
        else:
            logger.warning(
                "[BookingNotifications] WhatsApp was not "
                "sent for booking %s",
                booking_id,
            )

        # Booking SMS remains disabled.
        # Login OTP SMS remains handled by auth.py.
        # Existing Supabase push notifications remain unchanged.
        # No modifications to Razorpay payment processing.

        email = booking.get("email")

        if email:
            logger.info(
                "[BookingNotifications] Email confirmation "
                "not implemented. Booking %s",
                booking_id,
            )

    except Exception:
        logger.exception(
            "[BookingNotifications] Failed for booking %s",
            booking_id,
        )


# ============================================================
# MSG91 WHATSAPP BOOKING CANCELLATION
# ============================================================

async def send_booking_cancellation_whatsapp(
    booking: dict[str, Any],
) -> bool:
    """
    Send approved MSG91 booking_cancellation template.

    body_1 = customer name
    body_2 = booking ID

    This function does not send SMS or process refunds.
    """

    cancellation_template = os.getenv(
        "MSG91_WHATSAPP_CANCELLATION_TEMPLATE_NAME", ""
    ).strip()

    if not all([
        MSG91_AUTH_KEY,
        MSG91_WHATSAPP_INTEGRATED_NUMBER,
        MSG91_WHATSAPP_TEMPLATE_NAMESPACE,
        MSG91_WHATSAPP_TEMPLATE_LANGUAGE,
        cancellation_template,
    ]):
        logger.error(
            "[CancellationWhatsApp] Missing MSG91 configuration"
        )
        return False

    if cancellation_template != "booking_cancellation":
        logger.error(
            "[CancellationWhatsApp] Unexpected template: %s",
            cancellation_template,
        )
        return False

    booking_id = str(
        booking.get("id") or ""
    ).strip()

    customer_name = str(
        booking.get("customer_name") or "Customer"
    ).strip() or "Customer"

    phone = normalize_indian_phone(
        booking.get("phone_number")
    )

    if not booking_id or not phone:
        logger.warning(
            "[CancellationWhatsApp] Missing booking ID "
            "or valid customer phone"
        )
        return False

    payload = {
        "integrated_number":
            MSG91_WHATSAPP_INTEGRATED_NUMBER,

        "content_type": "template",

        "payload": {
            "messaging_product": "whatsapp",
            "type": "template",

            "template": {
                "name": cancellation_template,

                "language": {
                    "code": MSG91_WHATSAPP_TEMPLATE_LANGUAGE,
                    "policy": "deterministic",
                },

                "namespace":
                    MSG91_WHATSAPP_TEMPLATE_NAMESPACE,

                "to_and_components": [
                    {
                        "to": [phone],

                        "components": {
                            "body_1": {
                                "type": "text",
                                "value": customer_name,
                            },
                            "body_2": {
                                "type": "text",
                                "value": booking_id,
                            },
                        },
                    }
                ],
            },
        },
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "authkey": MSG91_AUTH_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                MSG91_WHATSAPP_API_URL,
                json=payload,
                headers=headers,
            )

        if not 200 <= response.status_code < 300:
            logger.error(
                "[CancellationWhatsApp] MSG91 HTTP error "
                "booking=%s status=%s",
                booking_id,
                response.status_code,
            )
            return False

        result = response.json()

        if not isinstance(result, dict):
            logger.error(
                "[CancellationWhatsApp] Invalid response "
                "for booking %s",
                booking_id,
            )
            return False

        if (
            result.get("hasError") is True
            or result.get("errors")
            or result.get("status") != "success"
        ):
            logger.error(
                "[CancellationWhatsApp] MSG91 rejected "
                "booking %s",
                booking_id,
            )
            return False

        logger.info(
            "[CancellationWhatsApp] MSG91 accepted "
            "booking=%s request_id=%s",
            booking_id,
            result.get("request_id", "N/A"),
        )

        return True

    except Exception:
        logger.exception(
            "[CancellationWhatsApp] Failed for booking %s",
            booking_id,
        )
        return False
