"""QLoRA fine-tune of Qwen2.5-1.5B-Instruct on the Nietzsche persona dataset.

Designed for a single 8GB GPU (RTX 3070):
  - 4-bit NF4 quantization (bitsandbytes) + LoRA adapters on all linear projections
  - max sequence length 768, per-device batch 2 x grad accumulation 8 (effective 16)
  - gradient checkpointing, paged_adamw_8bit optimizer
  - trains only on assistant tokens via completion-only collation
  - logs loss every 10 steps to console and outputs/loss_log.csv
  - saves adapter checkpoints each epoch to outputs/checkpoints/
"""

import csv
from pathlib import Path

import torch
from datasets import load_dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainerCallback,
)
from trl import DataCollatorForCompletionOnlyLM, SFTConfig, SFTTrainer

PRIMARY_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
FALLBACK_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
# The 1.5B model in 4-bit needs roughly 4GB peak (weights + LoRA + activations +
# paged optimizer) at seq len 768 / batch 2. If free VRAM is below this floor the
# run would OOM, so we drop to the 0.5B model instead.
MIN_FREE_VRAM_GB_FOR_PRIMARY = 5.5

MAX_SEQ_LENGTH = 768
RESPONSE_TEMPLATE = "<|im_start|>assistant\n"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
CHECKPOINTS_DIR = OUTPUTS_DIR / "checkpoints"
LOSS_LOG_PATH = OUTPUTS_DIR / "loss_log.csv"


class CsvLossLoggerCallback(TrainerCallback):
    """Append training loss rows to outputs/loss_log.csv as they are logged."""

    def __init__(self, csv_path: Path) -> None:
        self.csv_path = csv_path
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        with self.csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            csv.writer(csv_file).writerow(["step", "epoch", "loss", "learning_rate"])

    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs is None or "loss" not in logs:
            return
        with self.csv_path.open("a", newline="", encoding="utf-8") as csv_file:
            csv.writer(csv_file).writerow([
                state.global_step,
                round(state.epoch or 0.0, 4),
                logs["loss"],
                logs.get("learning_rate", ""),
            ])


def select_base_model() -> str:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU required for QLoRA training; none detected.")
    free_bytes, total_bytes = torch.cuda.mem_get_info(0)
    free_gb = free_bytes / 1024**3
    total_gb = total_bytes / 1024**3
    print(f"GPU: {torch.cuda.get_device_name(0)} | free {free_gb:.1f} GB / total {total_gb:.1f} GB")
    if free_gb < MIN_FREE_VRAM_GB_FOR_PRIMARY:
        print(f"Free VRAM below {MIN_FREE_VRAM_GB_FOR_PRIMARY} GB -> falling back to {FALLBACK_MODEL}")
        return FALLBACK_MODEL
    print(f"Using primary model {PRIMARY_MODEL}")
    return PRIMARY_MODEL


def load_model_and_tokenizer(model_name: str):
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=quantization_config,
        device_map={"": 0},
        torch_dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )
    lora_config = LoraConfig(
        r=8,
        lora_alpha=16,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()
    return model, tokenizer


def build_text_dataset(tokenizer):
    raw_dataset = load_dataset(
        "json",
        data_files={"train": str(DATA_DIR / "train.jsonl")},
    )["train"]

    def to_chat_text(example: dict) -> dict:
        return {"text": tokenizer.apply_chat_template(example["messages"], tokenize=False)}

    return raw_dataset.map(to_chat_text, remove_columns=raw_dataset.column_names)


def main() -> None:
    model_name = select_base_model()
    model, tokenizer = load_model_and_tokenizer(model_name)
    train_dataset = build_text_dataset(tokenizer)
    print(f"Training examples: {len(train_dataset)}")

    collator = DataCollatorForCompletionOnlyLM(
        response_template=RESPONSE_TEMPLATE,
        tokenizer=tokenizer,
    )

    training_args = SFTConfig(
        output_dir=str(CHECKPOINTS_DIR),
        num_train_epochs=3,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=8,
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        logging_steps=10,
        save_strategy="epoch",
        optim="paged_adamw_8bit",
        bf16=True,
        max_seq_length=MAX_SEQ_LENGTH,
        packing=False,
        dataset_text_field="text",
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        report_to="none",
        seed=42,
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        data_collator=collator,
        processing_class=tokenizer,
        callbacks=[CsvLossLoggerCallback(LOSS_LOG_PATH)],
    )

    torch.cuda.reset_peak_memory_stats(0)
    trainer.train()

    final_adapter_dir = CHECKPOINTS_DIR / "final"
    trainer.save_model(str(final_adapter_dir))
    tokenizer.save_pretrained(str(final_adapter_dir))
    (final_adapter_dir / "base_model.txt").write_text(model_name, encoding="utf-8")

    peak_allocated_gb = torch.cuda.max_memory_allocated(0) / 1024**3
    peak_reserved_gb = torch.cuda.max_memory_reserved(0) / 1024**3
    print(f"\nTraining complete. Final adapter saved to {final_adapter_dir}")
    print(f"Peak VRAM allocated: {peak_allocated_gb:.2f} GB | reserved: {peak_reserved_gb:.2f} GB")


if __name__ == "__main__":
    main()
