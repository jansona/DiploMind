"""任务2 最小测试：OpenAI 兼容连本地 qwen3.5:9b，结构化输出+重试，跑通一次 chat。"""
from pydantic import BaseModel

from diplomind.gateway import Gateway


class Greeting(BaseModel):
    country: str
    mood: str
    one_liner: str


def main() -> None:
    gw = Gateway()
    msgs = [
        {"role": "system", "content": "你是《外交》里阴险的德国玩家。只输出 JSON。"},
        {"role": "user", "content": "用一句开场白宣战法国。给 country/mood/one_liner。"},
    ]
    out = gw.chat(msgs, Greeting, tag="t2_smoke")
    print("parsed:", out)
    print("stats:", gw.log.stats())


if __name__ == "__main__":
    main()
