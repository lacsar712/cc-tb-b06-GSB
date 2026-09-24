def weigh(aroma: float, taste: float, liquor: float) -> tuple[str, str, float]:
    score = round(aroma * 0.3 + taste * 0.5 + liquor * 0.2, 2)
    if score >= 7:
        return "通过", "加权分达到放行线", score
    return "不通过", "加权分低于放行线", score


def summarize_liquor(note: str) -> str:
    """汤色留影的摘要短串：上传时由服务端依据审评说明句算出。

    取说明句的首个断句（句号/问号/叹号之前），压缩空白后截到 20 字。
    短串在上传那一刻定型，之后说明句如何改正都不影响已存短串。
    """
    text = " ".join((note or "").split())
    if not text:
        return "无汤色说明"
    for stop in ("。", "！", "？", "!", "?"):
        pos = text.find(stop)
        if pos >= 0:
            text = text[:pos]
            break
    text = text.strip("，,、；;：: ").strip()
    if not text:
        return "无汤色说明"
    if len(text) > 20:
        text = text[:20] + "…"
    return text
