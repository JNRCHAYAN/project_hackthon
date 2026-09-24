"""LLM narration tests — almost entirely about how it fails.

The LLM layer sits in front of the only text a human acts on, so the property
worth testing is not that a good response is used but that *every* bad one is
discarded. No test here makes a network call: ``httpx.Client`` is replaced by a
stub, and the environment token and the on-disk cache are both redirected to a
scratch directory, so a run is hermetic and repeatable.
"""
import json

import httpx
import pytest

from app import llm
from app.llm import llm_available, rephrase
from app.narrative import FORBIDDEN, Narrative

TOKEN_VAR = "ANTHROPIC_AUTH_TOKEN"


def _narrative():
    return Narrative(
        situation="Nagad e-money may be exhausted in about 0.2 hours.",
        evidence=["current balance ৳6,200",
                  "balance falling by ৳25,200 per hour",
                  "estimate based on the latest available feed update"],
        uncertainty="This is an estimate with real uncertainty — confidence 0.53.",
        next_steps=["Arrange additional e-money balance through the approved channel"],
        source="template")


class _Response:
    """A canned HTTP response, or the exception the transport should raise."""

    def __init__(self, payload=None, json_error=None, status_error=None):
        self.payload = payload
        self.json_error = json_error
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error is not None:
            raise self.status_error

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class _Network:
    """Stands in for ``httpx.Client``: records calls, never dials out."""

    def __init__(self):
        self.calls = 0
        self.requests = []
        self.response = _Response(payload={})

    def client(self, timeout=None):
        self.timeout = timeout
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def post(self, url, json=None, headers=None):
        self.calls += 1
        self.requests.append({"url": url, "body": json, "headers": headers})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def answer(self, situation="Rewritten situation.", uncertainty="Rewritten uncertainty.",
               raise_status=None, blocks=None, raw_text=None, json_error=None):
        """Install the next response the stub will return."""
        if blocks is not None:
            content = blocks
        else:
            text = raw_text if raw_text is not None else json.dumps(
                {"situation": situation, "uncertainty": uncertainty})
            content = [{"type": "text", "text": text}]
        self.response = _Response(payload={"content": content},
                                  json_error=json_error,
                                  status_error=raise_status)
        return self


@pytest.fixture
def net(monkeypatch, tmp_path):
    """A hermetic LLM layer: stubbed transport, scratch cache, fake token."""
    stub = _Network()
    monkeypatch.setenv(TOKEN_VAR, "test-token")
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path / "narrations")
    monkeypatch.setattr(llm.httpx, "Client", stub.client)
    return stub


# --- the happy path, so the failure tests mean something ---------------------

def test_a_valid_response_replaces_only_the_prose(net):
    narrative = _narrative()
    net.answer(situation="Nagad is close to running out of e-money.",
               uncertainty="An estimate, not a certainty.")

    result = rephrase(narrative, "en")

    assert net.calls == 1
    assert result.source == "llm"
    assert result.situation == "Nagad is close to running out of e-money."
    assert result.uncertainty == "An estimate, not a certainty."


def test_evidence_and_next_steps_can_never_be_rewritten(net):
    """The model is not given them, and must not be able to change them."""
    narrative = _narrative()
    net.answer()

    result = rephrase(narrative, "en")

    assert result.evidence == narrative.evidence
    assert result.next_steps == narrative.next_steps
    assert result.rejected_text == narrative.rejected_text


def test_the_request_carries_prose_only(net):
    narrative = _narrative()
    net.answer()

    rephrase(narrative, "en")

    body = net.requests[0]["body"]
    prompt = body["messages"][0]["content"]
    assert narrative.situation in prompt
    assert narrative.uncertainty in prompt
    # The numeric evidence is structurally absent from what the model sees.
    assert "৳6,200" not in prompt
    assert "25,200" not in prompt
    assert body["max_tokens"] == llm.SETTINGS["llm_max_tokens"]


# --- transport failures -----------------------------------------------------

@pytest.mark.parametrize("error,label", [
    (httpx.ConnectError("connection refused"), "connect"),
    (httpx.ReadTimeout("too slow"), "timeout"),
    (httpx.HTTPStatusError("429", request=None, response=None), "http status"),
])
def test_a_transport_failure_falls_back_to_the_template(net, error, label):
    narrative = _narrative()
    net.response = error

    result = rephrase(narrative, "en")

    assert result.source == "template", label
    assert result.situation == narrative.situation
    assert result.uncertainty == narrative.uncertainty


def test_a_raised_status_also_falls_back(net):
    net.answer(raise_status=httpx.HTTPStatusError("500", request=None,
                                                  response=None))
    result = rephrase(_narrative(), "en")
    assert result.source == "template"


def test_a_malformed_body_falls_back(net):
    net.answer(json_error=ValueError("not json"))
    assert rephrase(_narrative(), "en").source == "template"


def test_an_unparseable_completion_falls_back(net):
    net.answer(raw_text="I am afraid I cannot help with that.")
    assert rephrase(_narrative(), "en").source == "template"


def test_a_non_object_completion_falls_back(net):
    net.answer(raw_text='["not", "an", "object"]')
    assert rephrase(_narrative(), "en").source == "template"


def test_a_network_failure_never_raises(net):
    """Best effort is the contract: a template narrative is always usable."""
    for error in (httpx.ConnectError("down"), httpx.ReadTimeout("slow"),
                  httpx.HTTPError("generic")):
        net.response = error
        assert rephrase(_narrative(), "en") is not None


# --- truncated / reasoning-only responses -----------------------------------

@pytest.mark.parametrize("blocks", [
    [],                                                     # nothing at all
    [{"type": "thinking", "thinking": "Let me think about this."}],
    [{"type": "thinking", "thinking": "..."},
     {"type": "text", "text": "   "}],                       # whitespace only
])
def test_a_thinking_only_or_empty_response_falls_back(net, blocks):
    """A reasoning model truncated before its answer must not blank the alert."""
    narrative = _narrative()
    net.answer(blocks=blocks)

    result = rephrase(narrative, "en")

    assert result.source == "template"
    assert result.situation == narrative.situation


def test_thinking_blocks_are_never_scraped_for_prose(net):
    """The visible answer is the text block, not the reasoning trace."""
    narrative = _narrative()
    net.answer(blocks=[{"type": "thinking", "thinking": "Secret reasoning."}])

    assert rephrase(narrative, "en").situation == narrative.situation


# --- rejected vocabulary and numbers ----------------------------------------

@pytest.mark.parametrize("bad", [
    "This looks like fraud.",
    "The agent is fraudulent.",
    "প্রতারণা হয়েছে।",
    "Possibly criminal conduct.",
])
def test_forbidden_vocabulary_sends_the_alert_back_to_the_template(net, bad):
    narrative = _narrative()
    net.answer(situation=bad, uncertainty=bad)

    result = rephrase(narrative, "bn")

    assert result.source == "template"
    for word in FORBIDDEN:
        assert word.lower() not in result.situation.lower()
        assert word.lower() not in result.uncertainty.lower()


def test_a_rejected_field_does_not_drag_a_safe_field_down_with_it(net):
    """Fields are validated independently; the safe one may still be used."""
    narrative = _narrative()
    net.answer(situation="fraud detected", uncertainty="An estimate, not a fact.")

    result = rephrase(narrative, "en")

    assert result.situation == narrative.situation      # rejected
    assert result.uncertainty == "An estimate, not a fact."   # accepted


def test_a_half_accepted_answer_is_not_labelled_fully_model_written(net):
    """The source field must not round a partial success up to a full one.

    Fields validate independently, so a response can be half accepted. Saying
    "LLM-rephrased" over a block that is half template prose misdescribes the
    text in front of the reader — the same overstatement the source row exists
    to prevent, and the reason this is not folded into plain ``llm``.
    """
    narrative = _narrative()
    net.answer(situation="fraud detected", uncertainty="An estimate, not a fact.")

    result = rephrase(narrative, "en")

    assert result.source == "llm-partial"
    assert result.situation == narrative.situation
    assert result.uncertainty == "An estimate, not a fact."


def test_a_fully_accepted_answer_is_still_labelled_llm(net):
    """The partial label must not leak onto the complete case."""
    net.answer(situation="A clean rewrite.", uncertainty="Another clean rewrite.")
    assert rephrase(_narrative(), "en").source == "llm"


def test_the_partial_label_survives_the_cache(net):
    """A cached partial answer is still partial, and must say so on the way out.

    Only the accepted fields are stored, so the label is re-derived from what
    the cache file actually contains rather than remembered — which is what
    keeps a partial entry from reading as a complete one on the second load.
    """
    narrative = _narrative()
    net.answer(situation="fraud detected", uncertainty="An estimate, not a fact.")
    first = rephrase(narrative, "en")
    assert first.source == "llm-partial"

    net.response = httpx.ConnectError("the network must not be touched")
    second = rephrase(narrative, "en")

    assert net.calls == 1, "a cache hit made an HTTP request"
    assert second.source == "llm-cached-partial"
    assert second.situation == narrative.situation
    assert second.uncertainty == "An estimate, not a fact."


def test_a_complete_answer_stays_complete_through_the_cache(net):
    narrative = _narrative()
    net.answer(situation="Clean.", uncertainty="Also clean.")
    rephrase(narrative, "en")
    net.response = httpx.ConnectError("the network must not be touched")

    assert rephrase(narrative, "en").source == "llm-cached"


def test_the_four_outcomes_produce_four_distinct_names(net):
    """Each outcome is named, and no two collapse into one.

    The dashboard picks its label straight off this string, so two outcomes
    sharing a name would be two outcomes sharing a label — which is exactly how
    the partial case stayed hidden behind "LLM-rephrased" before.
    """
    clean = _narrative()                       # both fields acceptable
    mixed = Narrative(situation="A different situation.", evidence=[],
                      uncertainty="A different uncertainty.", next_steps=[],
                      rejected_text="", source="template")

    net.answer(situation="Clean rewrite.", uncertainty="Clean uncertainty.")
    assert rephrase(clean, "en").source == "llm"

    net.response = httpx.ConnectError("the network must not be touched")
    assert rephrase(clean, "en").source == "llm-cached"

    net.answer(situation="fraud detected", uncertainty="Kept anyway.")
    assert rephrase(mixed, "en").source == "llm-partial"

    net.response = httpx.ConnectError("the network must not be touched")
    assert rephrase(mixed, "en").source == "llm-cached-partial"


@pytest.mark.parametrize("bad", [
    "Exhausted in 3 hours.",
    "Balance is ৳6,200.",
    "Confidence 53%.",
    "Roughly 2,100 taka left.",
])
def test_a_number_in_the_output_is_rejected(net, bad):
    """The guardrail: a hallucinating model cannot move a figure."""
    narrative = _narrative()
    net.answer(situation=bad, uncertainty=bad)

    result = rephrase(narrative, "en")

    assert result.source == "template"
    assert result.situation == narrative.situation


def test_a_bengali_request_rejects_an_english_only_answer(net):
    narrative = _narrative()
    net.answer(situation="E-money may run out soon.",
               uncertainty="This is an estimate.")

    result = rephrase(narrative, "bn")

    assert result.source == "template"
    assert result.situation == narrative.situation


def test_an_empty_answer_falls_back(net):
    net.answer(situation="", uncertainty="")
    assert rephrase(_narrative(), "en").source == "template"


# --- the cache --------------------------------------------------------------

def test_a_cache_hit_skips_the_network_entirely(net):
    narrative = _narrative()
    net.answer(situation="First answer.", uncertainty="First uncertainty.")
    first = rephrase(narrative, "en")
    assert net.calls == 1
    assert first.source == "llm"

    # Any further attempt to reach the network would now fail loudly.
    net.response = httpx.ConnectError("the network must not be touched")
    second = rephrase(narrative, "en")

    assert net.calls == 1, "a cache hit made an HTTP request"
    assert second.source == "llm-cached"
    assert second.situation == "First answer."
    assert second.uncertainty == "First uncertainty."


def test_the_cache_is_keyed_by_language(net):
    narrative = _narrative()
    net.answer(situation="English answer.", uncertainty="English uncertainty.")
    rephrase(narrative, "en")
    net.answer(situation="বাংলা উত্তর।", uncertainty="বাংলা অনিশ্চয়তা।")
    bengali = rephrase(narrative, "bn")

    assert net.calls == 2
    assert bengali.source == "llm"
    assert bengali.situation == "বাংলা উত্তর।"


def test_the_cache_holds_the_text_not_the_narrative_object(net):
    narrative = _narrative()
    net.answer(situation="Cached prose.", uncertainty="Cached uncertainty.")
    rephrase(narrative, "en")

    files = list((llm.CACHE_DIR).glob("*.json"))
    assert len(files) == 1
    stored = json.loads(files[0].read_text(encoding="utf-8"))
    assert stored == {"situation": "Cached prose.",
                      "uncertainty": "Cached uncertainty."}


def test_a_corrupt_cache_entry_falls_through_to_the_network(net):
    narrative = _narrative()
    net.answer(situation="Fresh answer.", uncertainty="Fresh uncertainty.")
    rephrase(narrative, "en")
    for path in llm.CACHE_DIR.glob("*.json"):
        path.write_text("{not json", encoding="utf-8")

    net.answer(situation="Second answer.", uncertainty="Second uncertainty.")
    result = rephrase(narrative, "en")

    assert net.calls == 2
    assert result.situation == "Second answer."


# --- no token ---------------------------------------------------------------

def test_without_a_token_nothing_leaves_the_process(monkeypatch, tmp_path):
    stub = _Network()
    monkeypatch.delenv(TOKEN_VAR, raising=False)
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path / "narrations")
    monkeypatch.setattr(llm.httpx, "Client", stub.client)
    narrative = _narrative()

    assert llm_available() is False
    result = rephrase(narrative, "en")

    assert stub.calls == 0
    assert result is narrative
    assert result.source == "template"


def test_an_empty_token_counts_as_no_token(monkeypatch, tmp_path):
    stub = _Network()
    monkeypatch.setenv(TOKEN_VAR, "   ")
    monkeypatch.setattr(llm.httpx, "Client", stub.client)
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path / "narrations")

    assert llm_available() is False
    assert rephrase(_narrative(), "en").source == "template"
    assert stub.calls == 0
