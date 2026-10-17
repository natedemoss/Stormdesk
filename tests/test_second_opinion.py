"""Lightning's second opinion in triage, with a fake client (no GPU needed).
    python tests/test_second_opinion.py   (or pytest)
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stormdesk import triage  # noqa: E402

BLUE = "husband's lips are turning blue"  # missed by every keyword rule; a real model understands it


class FakeLightning:
    def __init__(self, content=None, error=None):
        self.content, self.error, self.calls = content, error, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


def opinion_from(fake):
    saved = triage.MOCK_LLM, triage.SECOND_OPINION, triage._agent_client
    triage.MOCK_LLM, triage.SECOND_OPINION, triage._agent_client = False, True, fake
    try:
        return triage.second_opinion(BLUE)
    finally:
        triage.MOCK_LLM, triage.SECOND_OPINION, triage._agent_client = saved


def test_rules_alone_miss_it():
    assert triage.combine("not_humanitarian", BLUE, None) == (1, None)


def test_second_opinion_raises_and_flags():
    u, flag = triage.combine("not_humanitarian", BLUE, {"at_risk": True, "reason": "possible breathing failure"})
    assert u == 4 and flag == "second opinion: possible breathing failure"


def test_second_opinion_never_lowers():
    # a report that talks Lightning into "false" (or Lightning being wrong) costs nothing
    fire = "huge fire on nanneytown road"
    assert triage.combine("other_relevant_information", fire, {"at_risk": False, "reason": ""})[0] == 4
    assert triage.combine("injured_or_dead_people", "car crash", {"at_risk": False, "reason": ""})[0] == 5


def test_rule_flag_wins_over_second_opinion_flag():
    u, flag = triage.combine("not_humanitarian", "im having a seizure", {"at_risk": True, "reason": "seizure"})
    assert u == 4 and flag == "possible medical emergency"


def test_parses_lightning_reply():
    fake = FakeLightning('{"at_risk": true, "reason": "cyanosis, needs EMS"}')
    assert opinion_from(fake) == {"at_risk": True, "reason": "cyanosis, needs EMS"}
    sent = fake.calls[0]
    assert sent["response_format"]["json_schema"]["schema"]["required"] == ["at_risk", "reason"]
    assert sent["messages"][1]["content"] == BLUE  # the report goes as the user message, never the system prompt


def test_lenient_parse_and_failures():
    assert opinion_from(FakeLightning('sure: {"at_risk": true, oops'))["at_risk"] is True
    assert opinion_from(FakeLightning("no idea")) is None
    assert opinion_from(FakeLightning(error=TimeoutError("slow"))) is None


def test_off_in_mock_mode():
    saved = triage.MOCK_LLM
    triage.MOCK_LLM = True
    try:
        assert triage.second_opinion(BLUE) is None
    finally:
        triage.MOCK_LLM = saved


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
