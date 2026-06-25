# Held-Out Perplexity

Base model: `Qwen/Qwen2.5-1.5B-Instruct` (4-bit NF4)
Adapter: `outputs\checkpoints\final`
Eval set: 40 held-out examples, assistant tokens only (completion-only, matching training).

| Model | Perplexity |
| --- | --- |
| Base | 71.99 |
| Fine-tuned | 33.20 |

Reduction: 53.9%
