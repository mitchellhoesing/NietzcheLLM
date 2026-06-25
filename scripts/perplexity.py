"""Held-out perplexity of the base model vs the fine-tuned (base + adapter) model.

Scores both models over the 40 held-out eval examples and reports perplexity.
To match the training objective (DataCollatorForCompletionOnlyLM), only the
assistant/completion tokens are scored; the system + user prompt is masked out.
To stay inside 8GB VRAM the two models are run sequentially: base first, then
freed, then base + adapter. Writes outputs/perplexity.md.
"""

import gc
import json
import math
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

SYSTEM_PROMPT = "You are Friedrich Nietzsche. Answer in his voice, in the first person."
RESPONSE_TEMPLATE = "<|im_start|>assistant\n"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
ADAPTER_DIR = OUTPUTS_DIR / "checkpoints" / "final"
PERPLEXITY_PATH = OUTPUTS_DIR / "perplexity.md"


def load_eval_examples() -> list[dict]:
    examples = []
    for raw_line in (DATA_DIR / "eval.jsonl").read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if raw_line:
            examples.append(json.loads(raw_line)["messages"])
    return examples


def load_quantized_base(model_name: str):
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    return AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=quantization_config,
        device_map={"": 0},
        torch_dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )


def corpus_perplexity(model, tokenizer, examples: list[dict], label: str) -> float:
    """exp(total assistant-token NLL / total assistant tokens) over the eval set."""
    model.eval()
    total_nll = 0.0
    total_tokens = 0
    for example_index, messages in enumerate(examples, start=1):
        # Prompt = system + user + the assistant generation header; everything
        # up to here is masked so only the assistant response contributes loss.
        prompt_text = tokenizer.apply_chat_template(
            messages[:-1], tokenize=False, add_generation_prompt=True
        )
        full_text = tokenizer.apply_chat_template(messages, tokenize=False)

        prompt_len = tokenizer(prompt_text, return_tensors="pt")["input_ids"].shape[1]
        input_ids = tokenizer(full_text, return_tensors="pt")["input_ids"].to(model.device)

        labels = input_ids.clone()
        labels[:, :prompt_len] = -100
        scored_tokens = int((labels != -100).sum().item())

        with torch.no_grad():
            loss = model(input_ids, labels=labels).loss

        total_nll += loss.item() * scored_tokens
        total_tokens += scored_tokens
        print(f"[{label}] {example_index}/{len(examples)}: {scored_tokens} tokens")

    return math.exp(total_nll / total_tokens)


def free_model(model) -> None:
    del model
    gc.collect()
    torch.cuda.empty_cache()


def main() -> None:
    base_model_name = (ADAPTER_DIR / "base_model.txt").read_text(encoding="utf-8").strip()
    print(f"Base model: {base_model_name}")
    print(f"Adapter: {ADAPTER_DIR}")

    tokenizer = AutoTokenizer.from_pretrained(base_model_name)
    examples = load_eval_examples()
    print(f"Held-out eval examples: {len(examples)}")

    base_model = load_quantized_base(base_model_name)
    base_ppl = corpus_perplexity(base_model, tokenizer, examples, "base")
    free_model(base_model)

    tuned_base = load_quantized_base(base_model_name)
    tuned_model = PeftModel.from_pretrained(tuned_base, str(ADAPTER_DIR))
    tuned_ppl = corpus_perplexity(tuned_model, tokenizer, examples, "fine-tuned")
    free_model(tuned_model)

    reduction = (base_ppl - tuned_ppl) / base_ppl * 100
    print(f"\nBase perplexity:       {base_ppl:.2f}")
    print(f"Fine-tuned perplexity: {tuned_ppl:.2f}")
    print(f"Reduction:             {reduction:.1f}%")

    lines = [
        "# Held-Out Perplexity",
        "",
        f"Base model: `{base_model_name}` (4-bit NF4)",
        f"Adapter: `{ADAPTER_DIR.relative_to(PROJECT_ROOT)}`",
        f"Eval set: {len(examples)} held-out examples, assistant tokens only "
        "(completion-only, matching training).",
        "",
        "| Model | Perplexity |",
        "| --- | --- |",
        f"| Base | {base_ppl:.2f} |",
        f"| Fine-tuned | {tuned_ppl:.2f} |",
        "",
        f"Reduction: {reduction:.1f}%",
        "",
    ]
    PERPLEXITY_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {PERPLEXITY_PATH}")


if __name__ == "__main__":
    main()
