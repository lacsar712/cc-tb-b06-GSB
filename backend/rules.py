import hashlib


def weigh(aroma: float, taste: float, liquor: float) -> tuple[str, str, float]:
    score = round(aroma * 0.3 + taste * 0.5 + liquor * 0.2, 2)
    if score >= 7:
        return "通过", "加权分达到放行线", score
    return "不通过", "加权分低于放行线", score


def liquor_digest(caption: str) -> str:
    """汤色留影不落大图：服务端按说明句算出固定短串。"""
    text = (caption or "").strip()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"汤影-{digest[:10]}"
