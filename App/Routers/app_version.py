
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from Supabase.client import get_supabase_client


logger = logging.getLogger("neatify-customer-backend.app-version")

router = APIRouter(
    prefix="/api/v1/customer/app-version",
    tags=["Customer App Version Management"],
)

DEFAULT_MESSAGE = (
    "A new version of The Neatify Team is available. "
    "Please update from Google Play."
)

MAX_SAFE_INTEGER = 9007199254740991


class AppVersionCheckResponse(BaseModel):
    updateAvailable: bool
    mandatory: bool
    installedVersion: str
    installedVersionCode: Optional[int]
    latestVersion: Optional[str]
    latestVersionCode: Optional[int]
    message: str
    playStoreUrl: Optional[str]


def default_version_response(
    installed_version: str,
    installed_version_code: int,
) -> AppVersionCheckResponse:
    return AppVersionCheckResponse(
        updateAvailable=False,
        mandatory=False,
        installedVersion=installed_version,
        installedVersionCode=installed_version_code,
        latestVersion=None,
        latestVersionCode=None,
        message=DEFAULT_MESSAGE,
        playStoreUrl=None,
    )


def parse_version_code(value: object) -> Optional[int]:
    if isinstance(value, bool):
        return None

    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None

    if (
        not number.is_finite()
        or number <= 0
        or number != number.to_integral_value()
    ):
        return None

    parsed = int(number)

    if parsed > MAX_SAFE_INTEGER:
        return None

    return parsed


@router.get(
    "/check",
    response_model=AppVersionCheckResponse,
    summary="Check Customer App Update",
)
async def check_customer_app_version(
    installed_version_code: int = Query(
        ...,
        ge=1,
        le=MAX_SAFE_INTEGER,
        description="Installed Android version code",
    ),
    installed_version: str = Query(
        default="Unknown",
        max_length=100,
        description="Installed application version name",
    ),
):
    default_result = default_version_response(
        installed_version,
        installed_version_code,
    )

    try:
        def fetch_app_version_config():
            client = get_supabase_client()

            return (
                client.table("app_version_config")
                .select(
                    "latest_version, "
                    "latest_version_code, "
                    "minimum_version_code, "
                    "update_policy, "
                    "update_message, "
                    "update_enabled, "
                    "play_store_url"
                )
                .eq("app_type", "customer")
                .eq("platform", "android")
                .limit(2)
                .execute()
            )

        response = await run_in_threadpool(
            fetch_app_version_config
        )

    except Exception:
        logger.exception(
            "[AppVersion] Unable to fetch version configuration"
        )
        raise HTTPException(
            status_code=503,
            detail="Unable to check app version at this time.",
        )

    rows = response.data or []

    if len(rows) == 0:
        logger.warning(
            "[AppVersion] Customer Android configuration not found"
        )
        return default_result

    if len(rows) > 1:
        logger.error(
            "[AppVersion] Multiple Customer Android configurations found"
        )
        return default_result

    config = rows[0]

    latest_code = parse_version_code(
        config.get("latest_version_code")
    )

    minimum_code = parse_version_code(
        config.get("minimum_version_code")
    )

    if (
        latest_code is None
        or minimum_code is None
        or minimum_code > latest_code
    ):
        logger.warning(
            "[AppVersion] Invalid version configuration"
        )
        return default_result

    if not config.get("update_enabled"):
        logger.info(
            "[AppVersion] Update notifications are disabled"
        )
        return default_result

    if installed_version_code >= latest_code:
        logger.info(
            "[AppVersion] Application is up to date"
        )
        return default_result

    mandatory = (
        config.get("update_policy") == "mandatory"
        or installed_version_code < minimum_code
    )

    message = config.get("update_message")

    if not isinstance(message, str) or not message.strip():
        message = DEFAULT_MESSAGE
    else:
        message = message.strip()

    logger.info(
        "[AppVersion] Update available: installed=%s latest=%s mandatory=%s",
        installed_version_code,
        latest_code,
        mandatory,
    )

    return AppVersionCheckResponse(
        updateAvailable=True,
        mandatory=mandatory,
        installedVersion=installed_version,
        installedVersionCode=installed_version_code,
        latestVersion=config.get("latest_version"),
        latestVersionCode=latest_code,
        message=message,
        playStoreUrl=config.get("play_store_url"),
    )
