"""Malformed model audiences must never disclose private text publicly."""
import pytest
from pydantic import ValidationError

from diplomind.agent import Agent
from diplomind.bus import MessageBus
from diplomind.engine import OperationEngine
from diplomind.personalities import PERSONAS
from diplomind.schemas import Message


@pytest.mark.parametrize("payload", [
    {"type": "private", "recipient": []},
    {"type": "private", "recipient": None},
    {"type": "private"},
    {"type": "unknown", "recipient": ["GERMANY"]},
    {"type": None, "recipient": ["GERMANY"]},
    {"type": "broadcast", "recipient": ["GERMANY"]},
    {"recipient": ["GERMANY"]},
    {"type": "private", "recipient": ["GERMANY", "ATLANTIS"]},
    {"type": "private", "recipient": ["GERMANY", None]},
])
def test_ambiguous_message_audience_rejected(payload):
    with pytest.raises(ValidationError):
        Message(**payload, content="PRIVATE_CANARY")


def test_valid_private_audience_normalizes_without_widening():
    message = Message(type=" PRIVATE ", recipient=[" germany ", "GERMANY"], content="PRIVATE_CANARY")
    assert message.type == "private" and message.recipient == ["GERMANY"]
    bus = MessageBus()
    bus.post(1, "FRANCE", message.type, message.recipient, message.content)
    assert "PRIVATE_CANARY" in str(bus.channels("GERMANY"))
    for spectator in (None, "ITALY", "ENGLAND"):
        assert "PRIVATE_CANARY" not in str(bus.channels(spectator))


@pytest.mark.asyncio
@pytest.mark.parametrize("scope,recipients", [
    ("private", []), ("private", None), ("private", ["GERMANY", "ATLANTIS"]),
    ("private", ["GERMANY", "FRANCE"]), ("broadcast", ["GERMANY"]),
    ("mystery", []),
])
async def test_custom_adapter_cannot_bypass_audience_guard(scope, recipients):
    class UncheckedAdapter:
        async def achat(self, *args, **kwargs):
            return Message.model_construct(type=scope, recipient=recipients, content="PRIVATE_CANARY")
    agent = Agent("FRANCE", PERSONAS["diplomat"], UncheckedAdapter())
    assert await agent.a_negotiate(OperationEngine(), "") is None
