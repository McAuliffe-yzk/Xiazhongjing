"""Creator onboarding and installation-readiness routes."""

from fastapi import APIRouter

from services.onboarding_service import onboarding_status


router = APIRouter(prefix="/api/xiangzhongjing", tags=["onboarding"])


@router.get("/onboarding/status")
async def get_onboarding_status():
    return onboarding_status()

