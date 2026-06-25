"""Assemble data/train.jsonl and data/eval.jsonl from authored part files.

Each part file in data/parts/ holds one authored Q/A pair per line as
{"q": ..., "a": ...}. This script wraps every pair with the fixed system
prompt into the chat-messages format required for SFT.
"""

import json
from pathlib import Path

SYSTEM_PROMPT = "You are Friedrich Nietzsche. Answer in his voice, in the first person."

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PARTS_DIR = PROJECT_ROOT / "data" / "parts"
DATA_DIR = PROJECT_ROOT / "data"


def build_split(part_glob: str, output_name: str) -> int:
    output_path = DATA_DIR / output_name
    pair_count = 0
    with output_path.open("w", encoding="utf-8") as output_file:
        for part_path in sorted(PARTS_DIR.glob(part_glob)):
            for raw_line in part_path.read_text(encoding="utf-8").splitlines():
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                pair = json.loads(raw_line)
                record = {
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": pair["q"]},
                        {"role": "assistant", "content": pair["a"]},
                    ]
                }
                output_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                pair_count += 1
    return pair_count


def main() -> None:
    train_count = build_split("train_part*.jsonl", "train.jsonl")
    eval_count = build_split("eval_part*.jsonl", "eval.jsonl")
    print(f"Wrote {train_count} training pairs to data/train.jsonl")
    print(f"Wrote {eval_count} eval pairs to data/eval.jsonl")


if __name__ == "__main__":
    main()
