"""编年史: 仅公开信息(私聊不进)+AI每年总结(假网关)。"""
import asyncio
from diplomind.bus import MessageBus
from diplomind.chronicle import generate, book, summarize_year, Summary


def test_public_only():
    b = MessageBus(); b.post(1,"FRANCE","broadcast",[],"和平"); b.post(1,"GER","private",["FRA"],"偷袭")
    t = generate(b, "S1901M", {"FRANCE":4})
    assert "和平" in t and "偷袭" not in t                 # 暗盘不进史
    assert book(["a","b"]) == "a\n\nb"


def test_ai_summary_stub():
    class GW:
        async def achat(self,m,s,**k): return Summary(text="法德结盟压俄")
    out = asyncio.run(summarize_year(GW(),"1901",["FRA: 和平"],{"FRANCE":4},"zh-Hans"))
    assert "1901" in out and "法德结盟" in out             # AI 总结明面入史
