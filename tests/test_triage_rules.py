"""Triage safety rules. Runs without a model: python tests/test_triage_rules.py (or pytest)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stormdesk.triage import safety_flag, urgency  # noqa: E402

BROTHER = "has anyone heard from my brother in Marion? he hasn't answered since yesterday"


def test_missing_person_misread_by_model():
    # The real fine-tune labeled this not_humanitarian on the Brev test (2026-10-13)
    assert urgency("not_humanitarian", BROTHER) >= 4
    assert safety_flag("not_humanitarian", BROTHER) == "possible missing person"


def test_no_flag_when_model_agrees():
    assert safety_flag("missing_or_found_people", BROTHER) is None
    assert urgency("missing_or_found_people", BROTHER) == 4


def test_missing_phrasings():
    for text in ("can't reach my mother on Polly Spout Road", "no word from my aunt since Thursday",
                 "lost contact with my brother near Twin Lakes Road", "my dad is not answering his phone"):
        assert safety_flag("other_relevant_information", text), text


def test_fire_misread_by_model():
    # The real fine-tune labeled this other_relevant_information (urgency 1) on the Brev test (2026-10-16)
    fire = "huge fire on nanneytown road"
    assert urgency("other_relevant_information", fire) >= 4
    assert safety_flag("other_relevant_information", fire) == "possible immediate danger"


def test_danger_phrasings():
    for text in ("smells like gas in the whole building", "power lines down and sparking on Main St",
                 "house collapsed, someone inside", "family trapped on the roof", "he's not breathing"):
        assert urgency("not_humanitarian", text) >= 4, text


def test_medical_emergencies():
    # "im having a seizure" came back urgency 1 on the Brev test (2026-10-16)
    for text in ("im having a seizure", "my husband had a stroke i think", "she overdosed and is unresponsive",
                 "baby is choking", "my wife is in labor and the road is out", "having chest pains",
                 "allergic reaction, no epipen", "grandpa passed out and won't wake", "I want to end my life"):
        assert urgency("not_humanitarian", text) >= 4, text
        assert safety_flag("not_humanitarian", text) == "possible medical emergency", text
    assert urgency("not_humanitarian", "no seizures since we moved to the shelter") == 1


def test_danger_negated_or_not_danger():
    for text in ("Tree down blocking Sugar Hill Rd, nobody trapped", "no fire, just a lot of water in the yard",
                 "shelter open at the Pleasant Gardens fire department", "Volunteers needed at the fire station"):
        assert urgency("infrastructure_and_utility_damage", text) == 3, text
        assert safety_flag("infrastructure_and_utility_damage", text) is None, text


def test_ordinary_reports_untouched():
    assert safety_flag("sympathy_and_support", "praying for everyone in western NC tonight") is None
    assert urgency("sympathy_and_support", "praying for everyone in western NC tonight") == 1
    assert urgency("infrastructure_and_utility_damage", "power out on our street since last night") == 3


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
