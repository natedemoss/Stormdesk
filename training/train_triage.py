"""LoRA fine-tune of a small model on HumAID with Unsloth (run on the GPU box).

    python training/train_triage.py --base Qwen/Qwen3-1.7B --epochs 1
Saves merged 16-bit weights to training/outputs/stormdesk-triage, ready for vLLM:
    vllm serve training/outputs/stormdesk-triage --port 8001 --served-model-name stormdesk-triage
"""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Qwen/Qwen3-1.7B")
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-seq", type=int, default=512)
    ap.add_argument("--push", default="", help="HF repo id to publish, e.g. yourname/stormdesk-triage")
    a = ap.parse_args()

    from unsloth import FastLanguageModel, is_bfloat16_supported  # import first, it patches transformers
    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer

    model, tok = FastLanguageModel.from_pretrained(a.base, max_seq_length=a.max_seq, load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(
        model, r=16, lora_alpha=32, lora_dropout=0.0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth")

    def fmt(ex):
        # enable_thinking=False: the same format triage.py and eval_triage.py serve with
        return {"text": tok.apply_chat_template(ex["messages"], tokenize=False, enable_thinking=False)}

    data = load_dataset("json", data_files={"train": str(HERE / "data/train.jsonl"),
                                            "val": str(HERE / "data/val.jsonl")})
    data = data.map(fmt, remove_columns=["messages", "label"])

    trainer = SFTTrainer(
        model=model, tokenizer=tok,
        train_dataset=data["train"], eval_dataset=data["val"].select(range(min(1000, len(data["val"])))),
        args=SFTConfig(
            output_dir=str(HERE / "outputs/ckpt"), dataset_text_field="text",
            max_seq_length=a.max_seq, per_device_train_batch_size=16, gradient_accumulation_steps=2,
            num_train_epochs=a.epochs, learning_rate=a.lr, warmup_ratio=0.03,
            lr_scheduler_type="cosine", logging_steps=20, eval_strategy="steps", eval_steps=200,
            save_strategy="no", bf16=is_bfloat16_supported(), fp16=not is_bfloat16_supported(),
            report_to="none"),
    )
    trainer.train()

    out = HERE / "outputs/stormdesk-triage"
    model.save_pretrained_merged(str(out), tok, save_method="merged_16bit")
    print(f"saved merged model to {out}")
    if a.push:
        model.push_to_hub_merged(a.push, tok, save_method="merged_16bit")
        print(f"published to https://huggingface.co/{a.push}")


if __name__ == "__main__":
    main()
