"""Side-by-side comparison of the base model vs the fine-tuned (base + adapter) model.

Runs both models over the 40 held-out eval questions plus 5 fixed demo questions
and writes outputs/comparison.md. To stay inside 8GB VRAM the two models are run
sequentially: base first, then freed, then base + adapter.
"""

import gc
import json
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

SYSTEM_PROMPT = "You are Friedrich Nietzsche. Answer in his voice, in the first person."

DEMO_QUESTIONS = [
    "Should I get back together with my ex?",
    "Is it bad that I check my phone first thing every morning?",
    "What do you think of artificial intelligence?",
    "Should ketchup be kept in the fridge?",
    "How should I deal with people who criticize me?",
]

GENERATION_KWARGS = {
    "temperature": 0.8,
    "top_p": 0.9,
    "max_new_tokens": 300,
    "do_sample": True,
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
ADAPTER_DIR = OUTPUTS_DIR / "checkpoints" / "final"
COMPARISON_PATH = OUTPUTS_DIR / "comparison.md"


def load_eval_questions() -> list[str]:
    questions = []
    for raw_line in (DATA_DIR / "eval.jsonl").read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if raw_line:
            questions.append(json.loads(raw_line)["messages"][1]["content"])
    return questions


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


def generate_answers(model, tokenizer, questions: list[str], label: str) -> list[str]:
    model.eval()
    answers = []
    for question_index, question_text in enumerate(questions, start=1):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question_text},
        ]
        prompt_text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = tokenizer(prompt_text, return_tensors="pt").to(model.device)
        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                pad_token_id=tokenizer.eos_token_id,
                **GENERATION_KWARGS,
            )
        completion_ids = output_ids[0][inputs["input_ids"].shape[1]:]
        answer_text = tokenizer.decode(completion_ids, skip_special_tokens=True).strip()
        answers.append(answer_text)
        print(f"[{label}] {question_index}/{len(questions)}: {question_text[:60]}")
    return answers


def main() -> None:
    base_model_name = (ADAPTER_DIR / "base_model.txt").read_text(encoding="utf-8").strip()
    print(f"Base model: {base_model_name}")
    print(f"Adapter: {ADAPTER_DIR}")

    tokenizer = AutoTokenizer.from_pretrained(base_model_name)
    questions = DEMO_QUESTIONS + load_eval_questions()
    print(f"Total questions: {len(questions)} ({len(DEMO_QUESTIONS)} demo + held-out eval)")

    torch.manual_seed(42)
    base_model = load_quantized_base(base_model_name)
    base_answers = generate_answers(base_model, tokenizer, questions, "base")
    del base_model
    gc.collect()
    torch.cuda.empty_cache()

    torch.manual_seed(42)
    tuned_base = load_quantized_base(base_model_name)
    tuned_model = PeftModel.from_pretrained(tuned_base, str(ADAPTER_DIR))
    tuned_answers = generate_answers(tuned_model, tokenizer, questions, "fine-tuned")
    del tuned_model, tuned_base
    gc.collect()
    torch.cuda.empty_cache()

    lines = [
        "# Base vs Fine-Tuned Comparison",
        "",
        f"Base model: `{base_model_name}` (4-bit NF4)",
        f"Adapter: `{ADAPTER_DIR.relative_to(PROJECT_ROOT)}`",
        f"Generation: temperature {GENERATION_KWARGS['temperature']}, top_p {GENERATION_KWARGS['top_p']}, "
        f"max_new_tokens {GENERATION_KWARGS['max_new_tokens']}",
        "",
        f"First {len(DEMO_QUESTIONS)} questions are fixed demo questions; the rest are the held-out eval set.",
        "",
    ]
    for question_index, question_text in enumerate(questions):
        lines.append(f"## {question_index + 1}. {question_text}")
        lines.append("")
        lines.append("**Base model:**")
        lines.append("")
        lines.append(f"> {base_answers[question_index].replace(chr(10), chr(10) + '> ')}")
        lines.append("")
        lines.append("**Fine-tuned model:**")
        lines.append("")
        lines.append(f"> {tuned_answers[question_index].replace(chr(10), chr(10) + '> ')}")
        lines.append("")

    COMPARISON_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {COMPARISON_PATH}")


if __name__ == "__main__":
    main()
