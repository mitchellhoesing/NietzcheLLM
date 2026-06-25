"""Validate data/train.jsonl and data/eval.jsonl.

Checks:
  1. Every line is valid JSON with the expected messages structure.
  2. No duplicate questions within or across splits.
  3. Answer length distribution (words per answer).
  4. Prints 5 random training samples for manual inspection.

Exits nonzero on any validation failure.
"""

import json
import random
import sys
from collections import Counter
from pathlib import Path

EXPECTED_SYSTEM_PROMPT = "You are Friedrich Nietzsche. Answer in his voice, in the first person."
EXPECTED_ROLES = ["system", "user", "assistant"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def load_split(split_name: str) -> list[dict]:
    split_path = DATA_DIR / split_name
    records = []
    failures = []
    for line_number, raw_line in enumerate(split_path.read_text(encoding="utf-8").splitlines(), start=1):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as decode_error:
            failures.append(f"{split_name}:{line_number} invalid JSON: {decode_error}")
            continue
        messages = record.get("messages")
        if not isinstance(messages, list) or [m.get("role") for m in messages] != EXPECTED_ROLES:
            failures.append(f"{split_name}:{line_number} unexpected messages structure")
            continue
        if messages[0]["content"] != EXPECTED_SYSTEM_PROMPT:
            failures.append(f"{split_name}:{line_number} wrong system prompt")
            continue
        if not messages[1]["content"].strip() or not messages[2]["content"].strip():
            failures.append(f"{split_name}:{line_number} empty question or answer")
            continue
        records.append(record)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        sys.exit(1)
    return records


def check_duplicates(train_records: list[dict], eval_records: list[dict]) -> None:
    def question_of(record: dict) -> str:
        return record["messages"][1]["content"].strip().lower()

    train_questions = [question_of(r) for r in train_records]
    eval_questions = [question_of(r) for r in eval_records]

    duplicate_failures = []
    for split_name, questions in (("train", train_questions), ("eval", eval_questions)):
        counts = Counter(questions)
        for question_text, count in counts.items():
            if count > 1:
                duplicate_failures.append(f"duplicate in {split_name} (x{count}): {question_text[:80]}")
    overlap = set(train_questions) & set(eval_questions)
    for question_text in overlap:
        duplicate_failures.append(f"question appears in both splits: {question_text[:80]}")

    if duplicate_failures:
        for failure in duplicate_failures:
            print(f"FAIL: {failure}")
        sys.exit(1)
    print("OK: no duplicate questions within or across splits")


def report_length_distribution(records: list[dict], split_name: str) -> None:
    word_counts = sorted(len(r["messages"][2]["content"].split()) for r in records)
    total = len(word_counts)
    mean_words = sum(word_counts) / total

    def percentile(fraction: float) -> int:
        return word_counts[min(total - 1, int(fraction * total))]

    buckets = {
        "short (<60 words)": sum(1 for w in word_counts if w < 60),
        "medium (60-180 words)": sum(1 for w in word_counts if 60 <= w <= 180),
        "long (>180 words)": sum(1 for w in word_counts if w > 180),
    }
    print(f"\n{split_name}: {total} pairs")
    print(f"  answer words: min={word_counts[0]} p25={percentile(0.25)} median={percentile(0.5)} "
          f"p75={percentile(0.75)} max={word_counts[-1]} mean={mean_words:.0f}")
    for bucket_name, bucket_count in buckets.items():
        print(f"  {bucket_name}: {bucket_count} ({100 * bucket_count / total:.0f}%)")


def print_samples(records: list[dict], sample_count: int = 5) -> None:
    print("\n--- 5 random training samples ---")
    rng = random.Random(42)
    for record in rng.sample(records, sample_count):
        question_text = record["messages"][1]["content"]
        answer_text = record["messages"][2]["content"]
        print(f"\nQ: {question_text}")
        print(f"A: {answer_text[:400]}{'...' if len(answer_text) > 400 else ''}")


def main() -> None:
    train_records = load_split("train.jsonl")
    eval_records = load_split("eval.jsonl")
    print(f"OK: all lines valid JSONL with correct structure "
          f"({len(train_records)} train, {len(eval_records)} eval)")

    if len(train_records) < 600:
        print(f"FAIL: need >=600 training pairs, found {len(train_records)}")
        sys.exit(1)
    if len(eval_records) < 40:
        print(f"FAIL: need >=40 eval pairs, found {len(eval_records)}")
        sys.exit(1)

    check_duplicates(train_records, eval_records)
    report_length_distribution(train_records, "train")
    report_length_distribution(eval_records, "eval")
    print_samples(train_records)
    print("\nAll validation checks passed.")


if __name__ == "__main__":
    main()
