"""网关宽松 JSON 提取单测：全角引号/markdown/缺括号/思考标签。"""
from diplomind.gateway import _extract
from diplomind.schemas import Message


def test_fullwidth_quote():
    assert Message.model_validate_json(_extract('{"type":"broadcast","content":"打你”}')).content == "打你"


def test_markdown_fence():
    assert _extract('```json\n{"a":1}\n```') == '{"a":1}'


def test_missing_brace():
    assert _extract('{"a":1') == '{"a":1}'


def test_think_strip():
    assert _extract('<think>x</think>{"a":1}') == '{"a":1}'
