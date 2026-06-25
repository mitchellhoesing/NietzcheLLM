"""Minimal interactive REPL for talking to the fine-tuned Nietzsche model.

Loads the 4-bit base model plus the trained LoRA adapter and holds a running
conversation. Type 'exit' or 'quit' (or Ctrl+C) to leave, 'reset' to clear
the conversation history.
"""

from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

SYSTEM_PROMPT = "You are Friedrich Nietzsche. Answer in his voice, in the first person."

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ADAPTER_DIR = PROJECT_ROOT / "outputs" / "checkpoints" / "final"

GENERATION_KWARGS = {
    "temperature": 0.8,
    "top_p": 0.9,
    "max_new_tokens": 300,
    "do_sample": True,
}


def load_model_and_tokenizer():
    base_model_name = (ADAPTER_DIR / "base_model.txt").read_text(encoding="utf-8").strip()
    print(f"Loading {base_model_name} + adapter from {ADAPTER_DIR} ...")
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    tokenizer = AutoTokenizer.from_pretrained(base_model_name)
    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        quantization_config=quantization_config,
        device_map={"": 0},
        torch_dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )
    model = PeftModel.from_pretrained(base_model, str(ADAPTER_DIR))
    model.eval()
    return model, tokenizer


def main() -> None:
    model, tokenizer = load_model_and_tokenizer()
    conversation = [{"role": "system", "content": SYSTEM_PROMPT}]
    print("\nSpeak with Nietzsche. Type 'exit' to leave, 'reset' to clear history.\n")

    while True:
        try:
            user_text = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nFarewell.")
            break
        if not user_text:
            continue
        if user_text.lower() in {"exit", "quit"}:
            print("Farewell.")
            break
        if user_text.lower() == "reset":
            conversation = [{"role": "system", "content": SYSTEM_PROMPT}]
            print("(history cleared)\n")
            continue

        conversation.append({"role": "user", "content": user_text})
        prompt_text = tokenizer.apply_chat_template(
            conversation, tokenize=False, add_generation_prompt=True
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
        conversation.append({"role": "assistant", "content": answer_text})
        print(f"\nNietzsche: {answer_text}\n")


if __name__ == "__main__":
    main()
