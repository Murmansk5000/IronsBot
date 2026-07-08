# SPDX-License-Identifier: MIT
from httpx import HTTPStatusError
from nonebot.params import Depends

from ironsbot.integrations.http_client import (
    get_http_cache_client,
    get_http_origin_client,
)
from ironsbot.utils.image import GetImage


async def _fallback_image(error: Exception) -> bytes:
    if isinstance(error, HTTPStatusError):
        code = error.response.status_code
        reason = error.response.reason_phrase
        text = f"{code} {reason}"
    else:
        text = "获取图片失败！"
    response = await get_http_origin_client().get(
        f"https://dummyimage.com/300&text={text}"
    )
    response.raise_for_status()
    return response.content


PetBodyImageGetter = GetImage(
    "https://newseer.61.com/web/monster/body/{}.png",
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/pet/body/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/pet/body/{}.png",
    fallback=_fallback_image,
    client_getter=get_http_cache_client,
)
PetBodyImage = Depends(PetBodyImageGetter)

PetHeadImageGetter = GetImage(
    "https://newseer.61.com/web/monster/head/{}.png",
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/pet/head/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/pet/head/{}.png",
    fallback=_fallback_image,
    client_getter=get_http_cache_client,
)
PetHeadImage = Depends(PetHeadImageGetter)

MintmarkBodyImageGetter = GetImage(
    "https://newseer.61.com/web/countermark/icon/{}.png",
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/countermark/icon/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/countermark/icon/{}.png",
    fallback=_fallback_image,
    client_getter=get_http_cache_client,
)
MintmarkBodyImage = Depends(MintmarkBodyImageGetter)

ElementTypeImageGetter = GetImage(
    "https://newseer.61.com/web/PetType/{}.png",
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/pettype/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/pettype/{}.png",
    client_getter=get_http_cache_client,
)
ElementTypeImage = Depends(ElementTypeImageGetter)

PreviewImageGetter = GetImage(
    "https://cnb.cool/HurryWang/seer-unity-preview-img-dumper-cnb/-/git/raw/master/img/preview.png",
    client_getter=get_http_origin_client,
)
PreviewImage = Depends(PreviewImageGetter)


AvatarHeadImageGetter = GetImage(
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/avatar/head/{}.png",
    client_getter=get_http_cache_client,
)
AvatarHeadImage = Depends(AvatarHeadImageGetter)

AvatarFrameImageGetter = GetImage(
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/avatar/frame/{}.png",
    client_getter=get_http_cache_client,
)
AvatarFrameImage = Depends(AvatarFrameImageGetter)

SuitImageGetter = GetImage(
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/item/cloth/suiticon/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/item/cloth/suiticon/{}.png",
    client_getter=get_http_cache_client,
)
SuitImage = Depends(SuitImageGetter)

EquipImageGetter = GetImage(
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/item/cloth/prev/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/item/cloth/prev/{}.png",
    client_getter=get_http_cache_client,
)
EquipImage = Depends(EquipImageGetter)

TitleImageGetter = GetImage(
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/achieve/title/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/achieve/title/{}.png",
    client_getter=get_http_cache_client,
)
TitleImage = Depends(TitleImageGetter)


BattleEffectImageGetter = GetImage(
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/battleeffect/abnormal/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/battleeffect/abnormal/{}.png",
    client_getter=get_http_cache_client,
)
BattleEffectImage = Depends(BattleEffectImageGetter)

SoulmarkIconImageGetter = GetImage(
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/battleeffect/signbuff/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/battleeffect/signbuff/{}.png",
    client_getter=get_http_cache_client,
)
SoulmarkIconImage = Depends(SoulmarkIconImageGetter)
