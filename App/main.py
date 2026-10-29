
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from App.Routers.main_categories import router as main_categories_router
from App.Routers.services import router as services_router
from App.Routers.promotional_banners import router as promotional_banners_router
from App.Routers.offers import router as offers_router
from App.Routers.addons import router as addons_router
from App.Routers.customer_auth_test import router as customer_auth_test_router
from App.Routers.hero_banners import router as hero_banners_router
from App.Routers.app_popups import router as app_popups_router
from App.Routers.my_bookings import router as my_bookings_router
from App.Routers.profile import router as profile_router
from App.Routers.addresses import router as addresses_router
from App.Routers.policies import router as policies_router
from App.Routers.hubs import router as hubs_router
from App.Routers.schedule import router as schedule_router
from App.Routers.cart import router as cart_router
from App.Routers.coupons import router as coupons_router
from App.Routers.bookings import router as bookings_router

app = FastAPI(
    title="Neatify Customer Backend",
    description="REST API for the Neatify Customer Application",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(services_router)


@app.get("/")
async def root():
    return {
        "message": "Neatify Customer Backend is running"
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "neatify-customer-backend"
    }

app.include_router(main_categories_router)
app.include_router(addons_router)
app.include_router(offers_router)
app.include_router(hero_banners_router)
app.include_router(app_popups_router)
app.include_router(promotional_banners_router)
app.include_router(customer_auth_test_router)
app.include_router(my_bookings_router)
app.include_router(profile_router)
app.include_router(addresses_router)
app.include_router(policies_router)
app.include_router(hubs_router)
app.include_router(schedule_router)
app.include_router(cart_router)
app.include_router(coupons_router)
app.include_router(bookings_router)