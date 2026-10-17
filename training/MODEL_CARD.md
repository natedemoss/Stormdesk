---
# Hugging Face model card for the StormDesk triage model (README.md of ndemoss28/stormdesks-triage).
license: cc-by-nc-sa-4.0
base_model: Qwen/Qwen3-1.7B
datasets:
  - QCRI/HumAID-all
language:
  - en
pipeline_tag: text-generation
library_name: transformers
tags:
  - disaster-response
  - crisis-informatics
  - text-classification
  - humanitarian
  - unsloth
  - lora
---

# StormDesk Triage (Qwen3-1.7B, HumAID fine-tune)

A 1.7B model that sorts disaster reports (texts, call notes, social posts) into the 10
humanitarian categories of HumAID. It is the triage stage of
[StormDesk](https://github.com/natedemoss/stormdesk), an offline disaster-response agent built for the
NVIDIA x Red Hat Small Models Hack. It runs next to Nemotron 3.5 Lightning on one GPU, with no
internet, so a county emergency operations center can triage reports when networks are down,
as they were in western North Carolina after Hurricane Helene.

## How to use

The model answers with JSON only. Served with vLLM, structured output guarantees valid labels:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8001/v1", api_key="local")
schema = {"type": "object", "required": ["category"],
          "properties": {"category": {"type": "string", "enum": [
              "requests_or_urgent_needs", "injured_or_dead_people", "missing_or_found_people",
              "displaced_people_and_evacuations", "infrastructure_and_utility_damage",
              "caution_and_advice", "rescue_volunteering_or_donation_effort",
              "other_relevant_information", "sympathy_and_support", "not_humanitarian"]}}}
r = client.chat.completions.create(
    model="stormdesk-triage", temperature=0, max_tokens=40,
    messages=[{"role": "system", "content": "Classify this disaster report into one humanitarian category. Reply with JSON only."},
              {"role": "user", "content": "my dad is 81 and trapped upstairs, water rising fast"}],
    response_format={"type": "json_schema", "json_schema": {"name": "triage", "schema": schema}},
    extra_body={"chat_template_kwargs": {"enable_thinking": False}})  # the format it was trained on
print(r.choices[0].message.content)  # {"category": "requests_or_urgent_needs"}
```

```bash
vllm serve ndemoss28/stormdesks-triage --served-model-name stormdesk-triage --max-model-len 1024
```

In StormDesk, urgency (1 to 5) is not predicted by the model. It is the category's base urgency
plus one for life-safety keywords, so the model's job stays narrow and measurable.

## Training

| | |
|---|---|
| Base model | Qwen/Qwen3-1.7B |
| Method | LoRA with Unsloth, r=16, alpha=32, dropout 0, all attention and MLP projections, 4-bit base during training, merged to 16-bit |
| Data | HumAID train split, each class capped at 6,000 and smaller classes repeated up to 1,000 (42,639 total), chat format with thinking off, target is `{"category": ...}` |
| Loss | On the answer only (Unsloth `train_on_responses_only`), not the system prompt or the post |
| Epochs, LR | 1 epoch, 2e-4, cosine, 3% warmup, effective batch 32, max length 512 |
| Hardware | One NVIDIA T4 (free Google Colab), 49.4 minutes |

Script: `training/train_triage.py` (GPU box) or `training/train_triage_colab.ipynb` (free Colab/Kaggle T4);
data prep: `training/prepare_humaid.py`.

## Evaluation

1,000 posts sampled (seed 0) from the HumAID test split (15,160), macro F1 over the 10 labels
present. Scoring is constrained like the app's vLLM structured output: the model picks one of the
11 category names (after `{"category": "` each starts with a different token, so this equals
forced-format greedy decoding). All three rows use the same posts and the same scoring.

| Model | Macro F1 | Accuracy |
|---|---|---|
| Qwen3-1.7B, prompt without the category names | 0.025 | 0.067 |
| Qwen3-1.7B, prompt that lists the category names | 0.416 | 0.363 |
| StormDesk Triage v1 (3,000 per class, loss on the whole example) | 0.732 | 0.754 |
| **StormDesk Triage v2 (this model)** | **0.755** | **0.780** |

The fair comparison is the second row: fine-tuning adds +0.34 macro F1 over the same base model
told the category names. Per-category results for v2:

| Category | Precision | Recall | F1 | Posts |
|---|---|---|---|---|
| requests_or_urgent_needs | 0.56 | 0.68 | 0.61 | 34 |
| injured_or_dead_people | 0.88 | 0.94 | 0.91 | 95 |
| missing_or_found_people | 0.73 | 0.80 | 0.76 | 10 |
| displaced_people_and_evacuations | 0.85 | 0.93 | 0.88 | 54 |
| infrastructure_and_utility_damage | 0.81 | 0.89 | 0.85 | 104 |
| caution_and_advice | 0.62 | 0.64 | 0.63 | 67 |
| rescue_volunteering_or_donation_effort | 0.91 | 0.85 | 0.88 | 282 |
| other_relevant_information | 0.61 | 0.48 | 0.54 | 137 |
| sympathy_and_support | 0.81 | 0.82 | 0.82 | 130 |
| not_humanitarian | 0.63 | 0.71 | 0.67 | 87 |

## Limitations

- **Some urgent requests are missed.** `requests_or_urgent_needs` has 0.68 recall (v1: 0.76) and
  0.56 precision (v1: 0.50) on 34 test posts, so the difference between versions is a few posts and
  may be noise. This is the category that matters most for dispatch. In StormDesk, urgency also gets
  +1 for life-safety words (trapped, oxygen, insulin, ...) whatever the label, and every report
  stays visible in the queue for a human.
- **"Other relevant information" is the weakest class** (0.54 F1, up from 0.38 in v1). It is a
  catch-all and often confused with the specific ones.
- **Missing persons has little data.** HumAID has only 250 distinct training examples of
  `missing_or_found_people`, repeated up to 1,000 during training. It scored 0.76 F1, but on just
  10 test posts, so treat that number as rough.
- **No "unclear" label.** HumAID's `dont_know_cant_judge` has no examples in the released data,
  so the model always picks one of the 10 categories.
- **Twitter-era English.** HumAID covers 19 disasters from 2016 to 2019 (including Hurricane
  Florence in North Carolina). Phone transcripts, SMS shorthand and other languages are out of distribution.
- **Not a decision maker.** It ranks a queue for humans. In StormDesk every dispatch is a draft
  that a dispatcher approves, and the system has no way to send anything.

## License

The training data, HumAID, is licensed CC BY-NC-SA 4.0, so these weights are released under the
same license: non-commercial use, with attribution, and derivatives shared alike. The base model,
Qwen3-1.7B, is Apache 2.0.

## Citation

If you use this model, please cite HumAID:

```bibtex
@inproceedings{humaid2020,
  Author = {Firoj Alam, Umair Qazi, Muhammad Imran, Ferda Ofli},
  booktitle = {Proceedings of the Fifteenth International AAAI Conference on Web and Social Media},
  series = {ICWSM~'21},
  Title = {HumAID: Human-Annotated Disaster Incidents Data from Twitter},
  Year = {2021},
  publisher = {AAAI},
  address = {Online},
}
```
