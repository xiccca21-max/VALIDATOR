"""Original-receipt collection campaign."""

from .config import (
    CAMPAIGN_REWARD_PER_ACCEPTED_CHECK_KOPECKS,
    campaign_is_active,
    is_campaign_admin,
)
from . import service
from . import texts

__all__ = [
    "CAMPAIGN_REWARD_PER_ACCEPTED_CHECK_KOPECKS",
    "campaign_is_active",
    "is_campaign_admin",
    "service",
    "texts",
]
