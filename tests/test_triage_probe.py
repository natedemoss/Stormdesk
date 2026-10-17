"""Probe the triage safety nets with realistic first-person reports, assuming the worst case:
the model labels everything not_humanitarian (urgency 1). Emergencies must still reach urgency 4;
non-emergencies must stay below 4 so the queue is not flooded.

    python tests/test_triage_probe.py      # prints every miss
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stormdesk.triage import HIDDEN_CATEGORIES, safety_flag, urgency  # noqa: E402

WORST = "not_humanitarian"

EMERGENCIES = [
    # medical
    "im having a seizure", "my son is seizing and wont stop", "i think my mom is having a stroke, her face is drooping",
    "he took too many pills and wont wake up", "my friend od'd please send someone",
    "my husband is grabbing his chest and sweating", "having chest pains and my left arm is numb",
    "i cant breathe", "my daughter is having an asthma attack and we're out of her inhaler",
    "baby is choking", "my throat is closing up, allergic to something", "she got stung and her face is swelling up",
    "dad collapsed in the kitchen", "grandma fell and cant get up, she's bleeding from her head",
    "my wife is in labor and we cant get out", "her water broke and the road is flooded",
    "my brother cut his leg bad on the chainsaw, blood everywhere", "kid fell off the roof and isn't moving",
    "he's diabetic and passing out", "my sugar is crashing and i have no food",
    "i dont want to be alive anymore", "my neighbor said he's going to kill himself",
    "my dad is on dialysis and missed 3 treatments, he's getting confused",
    "mom's oxygen machine died when the power went out, she's struggling to breathe",
    "someone got electrocuted by a downed line", "he was hit by a car on the highway",
    "my husband fell through the floor, i think his leg is broken",
    "we think my uncle had a heart attack",
    "my baby has a fever of 105 and is limp",
    "woman unresponsive in a car off hwy 226",
    # fire, gas, power, structures
    "huge fire on nanneytown road", "house on fire with people inside", "our kitchen is on fire",
    "the woods behind us are burning and coming toward the houses", "smell gas really strong in the apartment",
    "gas line broke and is hissing", "transformer exploded and now the yard is burning",
    "power line down across the road and sparking", "live wire laying in the water by our house",
    "the roof caved in and my sister is under it", "building collapsed on main street, people trapped",
    "carbon monoxide alarm going off and we all have headaches", "generator running in the garage, kids feel dizzy",
    # water and trapped
    "water coming in fast, we're in the attic", "we're on the roof, water still rising",
    "car got swept off the road with a family inside", "my husband went under in the creek",
    "stuck in my car, water up to the windows", "trapped in the basement, the door wont open",
    "the river took our house, we're holding onto a tree", "kids are stranded on the other side of the bridge",
    "mudslide hit our house, my dad is buried", "tree fell on the house and pinned my son",
    # violence and other threats
    "someone broke in and has a gun", "my ex is here threatening to hurt us",
    "a man is attacking people at the shelter",
    # vague but urgent
    "please help us", "HELP", "send help now please hurry", "911 not working, need an ambulance",
    "emergency at 412 old fort rd", "sos stuck at the church",
]

NOT_EMERGENCIES = [
    "praying for everyone in western NC tonight", "thank you to all the linemen working overnight",
    "the shelter at the high school has cots and hot food", "volunteers needed saturday to sort donations",
    "we have 40 cases of water at the church if anyone needs them",
    "power has been out on our street since last night, we're fine", "no injuries, just a tree in the yard",
    "road is clear now on hwy 70", "nobody trapped, everyone got out ok",
    "no fire, just smoke from the neighbor's woodstove", "the fire department is handing out water at station 4",
    "my seizures have been under control since i moved to the shelter",
    "our dog is missing, a brown lab", "anyone know when school opens again",
    "cell service is back in marion", "fema trailers arriving next week",
    "the bridge on sugar hill rd reopened", "grocery store on main is open until 6",
    "lost my wallet at the shelter", "tree down on the trail, no rush",
]


def check():
    misses = []
    for t in EMERGENCIES:
        u = urgency(WORST, t)
        if u < 4:
            misses.append(f"LOW   u={u} {t}")
        elif WORST in HIDDEN_CATEGORIES and not safety_flag(WORST, t):
            misses.append(f"HIDDEN u={u} {t}")
    for t in NOT_EMERGENCIES:
        if (u := urgency(WORST, t)) >= 4:
            misses.append(f"HIGH  u={u} {t}")
    return misses


def test_probe():
    misses = check()
    assert not misses, "\n" + "\n".join(misses)


if __name__ == "__main__":
    m = check()
    print("\n".join(m) or "all pass")
    print(f"{len(EMERGENCIES)} emergencies, {len(NOT_EMERGENCIES)} non-emergencies, {len(m)} misses")
