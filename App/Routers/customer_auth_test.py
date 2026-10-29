
from fastapi import APIRouter, Depends

from App.Dependencies.customer_auth import (
    AuthenticatedCustomer,
    get_current_customer,
)


router = APIRouter(
    prefix="/api/v1/customer",
    tags=["Customer Authentication"],
)


@router.get("/auth/me")
async def get_authenticated_customer(
    customer: AuthenticatedCustomer = Depends(
        get_current_customer
    ),
):
    return {
        "success": True,
        "data": {
            "user_id": customer.user_id
        },
    }
