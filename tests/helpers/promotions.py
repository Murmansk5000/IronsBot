from ironsbot.core.promotions import PromotionCatalog, PromotionConfig

FIRE_MANUAL_PROMOTION = PromotionConfig(
    feature="fire_manual_ad",
    url="https://example.com/fire-manual",
    text="Manual: {url}",
    append_to_push=True,
)
FIRE_MANUAL_PROMOTIONS = PromotionCatalog(
    {"fire_manual": FIRE_MANUAL_PROMOTION}
)
