"""interpret_pending_reply: apply a stated correction, else converse.

Regression: a reply that questions or flags a field without giving a new value
("are you sure that's the price?", "the price is wrong") must produce a
contextual reply asking for the value — not an empty update that drops the
agent back into the canned "I'm still waiting" summary loop.
"""

from app.services import ai_extract


class _Block:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class _Resp:
    def __init__(self, text: str):
        self.content = [_Block(text)]


class _Messages:
    def __init__(self, text: str):
        self._text = text

    async def create(self, **kwargs):
        return _Resp(self._text)


class _Client:
    def __init__(self, text: str):
        self.messages = _Messages(text)


def _patch(monkeypatch, model_json: str):
    monkeypatch.setattr(ai_extract, "_client", lambda: _Client(model_json))


async def test_stated_correction_yields_update_and_no_reply(monkeypatch):
    _patch(monkeypatch, '{"updates": {"sale_price": "450000"}, "reply": ""}')
    updates, reply = await ai_extract.interpret_pending_reply(
        {"sale_price": 300000.0}, "the price should be 450k"
    )
    assert updates == {"sale_price": 450000.0}
    assert reply == ""


async def test_question_without_value_yields_conversational_reply(monkeypatch):
    _patch(
        monkeypatch,
        '{"updates": {}, "reply": "The contract shows $300,000 as the price. '
        'What should it be?"}',
    )
    updates, reply = await ai_extract.interpret_pending_reply(
        {"sale_price": 300000.0}, "are you sure that's the correct price?"
    )
    assert updates == {}
    assert "what should it be" in reply.lower()


async def test_null_value_is_not_invented_as_update(monkeypatch):
    # The model must never write a field back as null; that would erase a value.
    _patch(monkeypatch, '{"updates": {"sale_price": null}, "reply": "What is it?"}')
    updates, reply = await ai_extract.interpret_pending_reply(
        {"sale_price": 300000.0}, "the price is wrong"
    )
    assert updates == {}
    assert reply == "What is it?"
