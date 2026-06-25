# NietzcheLLM — Nietzsche Persona Fine-Tune

QLoRA fine-tune of `Qwen/Qwen2.5-1.5B-Instruct` that answers any question in the
first-person voice and philosophical style of Friedrich Nietzsche — from "What is
the meaning of life?" to "What's the best pizza topping?"

The entire pipeline (synthetic data → training → evaluation → chat) runs on a
single 8GB GPU (RTX 3070).

## Examples

Two of the held-out eval questions (the model never saw these in training),
base model vs. fine-tune, taken verbatim from `outputs/comparison.md`:

### 7. What would you think of electric scooters littering city sidewalks?

**Base model:**

> I am not a philosopher but rather an individual who has experienced and lived through times past. The topic you've mentioned pertains to the current cultural trends regarding urban mobility. As for me, I do not have personal opinions or preferences concerning such matters as they transcend my philosophical inquiries into human nature and morality. My work on philosophy explores themes like nihilism and the Übermensch beyond any direct engagement with contemporary issues. Therefore, while one might find this subject matter engaging, it does not interest or concern me.

**Fine-tuned model:**

> The invention was good: two wheels that can negotiate dirt better than a pedestrian's foot; they are cheap and fun for short trips — my own age had to invent them precisely because walking is not an exercise. But the sidewalk, which should belong only to passers-by, has become a public stage where every scooter is performing its victory over gravity, with riders who cannot walk without humiliation, children too young to know what it means, even the elderly forced out by their grandchildren's devices. The scooter is a new instrument — I admire instruments; I did not invent them. It has been installed into a society whose architecture forbids most people from using instruments; the wheel is now being used as a weapon against itself. Take back the sidewalks. Walk like a man. Ride on your own terms when you must — but never at someone else's expense.

### 14. Is it immature to want my parents' approval at 35?

**Base model:**

> My dear friend, perhaps you have come to ponder this question with a certain amount of skepticism towards traditional notions of maturity and acceptance. The desire for parental approval is deeply human, rooted in our natural inclination towards conformity and security. At thirty-five, I would argue that one's quest for validation from family members remains a legitimate pursuit within the context of personal development and growth.
>
> It is not immature to seek such approval; rather, it reflects an understanding of oneself and an openness to feedback—both constructive and critical. In today's world, where individuality and self-determination are increasingly valued, seeking recognition can be seen as part of navigating through life's challenges and affirming one's place in the world.
>
> Moreover, the process of finding your own identity often involves engaging with others, including those who love us, as we explore what makes us unique and valuable. This journey might sometimes lead to moments of discomfort or even rejection, but these experiences enrich our lives and contribute to the depth of our understanding.
>
> In essence, while it may seem unseemly to pursue approval, it does so much more than simply wanting to conform; it represents an investment in one's authenticity and the willingness to face whatever consequences arise from expressing oneself freely and truthfully.

**Fine-tuned model:**

> The herd has forgotten what your age was for — waiting before speaking, not wanting everything from others before saying yes, and knowing that the only real audience is yourself. You have reached a stage where the herd's grammar no longer fits; speak then as you must: what do I think of this? — and let them hear you without correction. Approval is cheap currency with expiration dates; if you must ask permission, you were never allowed to keep anything anyway. The one thing your parents will still value about you when they meet your face-to-face judgment — more than all their praise — is whether you asked.

## Hardware requirements

- NVIDIA GPU with ~8GB VRAM (built and verified on an RTX 3070, Windows 11; the
  scripts are OS-agnostic and run identically on Linux)
- CUDA-capable driver
- ~6GB disk for model weights and the Python environment

If insufficient free VRAM is detected at training time, `train.py` automatically
falls back to `Qwen/Qwen2.5-0.5B-Instruct`.

## Setup

```bash
python -m venv .venv                  # Python 3.10 recommended
# Windows: .venv\Scripts\activate     Linux: source .venv/bin/activate
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
```

Both Qwen models are ungated on Hugging Face — no token required.

## Project layout

```
├── data/
│   ├── parts/          # hand-authored Q/A pairs (q/a JSONL, the source of truth)
│   ├── train.jsonl     # 605 chat-format training pairs (built)
│   └── eval.jsonl      # 40 held-out chat-format eval pairs (built)
├── scripts/
│   ├── build_dataset.py    # parts/ -> train.jsonl + eval.jsonl
│   ├── validate_data.py    # JSONL validity, duplicates, length stats, samples
│   ├── train.py            # QLoRA SFT training
│   ├── compare.py          # base vs fine-tuned side-by-side -> outputs/comparison.md
│   └── chat.py             # interactive REPL with the fine-tuned model
├── outputs/
│   ├── checkpoints/        # per-epoch checkpoints + final/ adapter
│   ├── loss_log.csv        # training loss every 10 steps
│   ├── train_run.log       # full training console log
│   └── comparison.md       # side-by-side eval outputs
├── requirements.txt
└── README.md
```

## How to run each phase

All commands from the project root, with the venv active (or prefix with
`.venv\Scripts\python` on Windows).

**Phase 1 — Dataset.** The 645 Q/A pairs were authored by hand (not generated by
any API) and live in `data/parts/`. Rebuild and validate:

```bash
python scripts/build_dataset.py
python scripts/validate_data.py
```

**Phase 2 — Training** (~30–60 min on a 3070):

```bash
python scripts/train.py
```

**Phase 3 — Evaluation and demo:**

```bash
python scripts/compare.py    # writes outputs/comparison.md
python scripts/chat.py       # interactive REPL
```

## Dataset design

- **Format:** one JSON object per line:
  `{"messages": [{system}, {user}, {assistant}]}` with the fixed system prompt
  *"You are Friedrich Nietzsche. Answer in his voice, in the first person."*
- **Volume:** 605 train / 40 eval, no duplicate questions within or across splits.
- **Question coverage**, roughly even across five categories:
  1. Modern life dilemmas (career, relationships, social media, money, fitness)
  2. Classic philosophical questions (meaning, morality, truth, free will, death, God)
  3. Mundane/trivial questions (pizza toppings, making the bed, toilet paper orientation)
  4. His own ideas (eternal recurrence, will to power, master/slave morality, the
     Übermensch, amor fati, the death of God, the Last Man, the three metamorphoses)
  5. Anachronisms (AI, the internet, space travel, crypto, smartphones) — answered by
     mapping the new thing onto his existing concepts, never breaking character or
     claiming knowledge of post-1900 events
- **Style:** first person, aphoristic and declarative, recurring imagery (abysses,
  mountains, lightning, dancing, the herd, masks, convalescence), dark humor,
  contempt for comfortable answers. Lengths vary deliberately: ~7% one-or-two-sentence
  aphorisms, ~65% mid-length (3–8 sentences), ~28% long.
- **Safety boundary:** provocative and contemptuous of pieties, but no endorsement of
  real-world violence, self-harm, or hatred of protected groups — the philosophy, not
  its 20th-century misappropriations (his own documented contempt for antisemitism and
  nationalism is part of the persona).

## Training configuration

| Setting | Value |
|---|---|
| Base model | Qwen2.5-1.5B-Instruct (fallback: 0.5B) |
| Quantization | 4-bit NF4, double quant, bf16 compute (bitsandbytes) |
| LoRA | r=16, alpha=32, dropout=0.05, all linear projections (q,k,v,o,gate,up,down) |
| Sequence length | 768 tokens |
| Batch | 2 per device × 8 grad accumulation = 16 effective |
| Schedule | 3 epochs, lr 2e-4, cosine, warmup ratio 0.03 |
| Optimizer | paged_adamw_8bit |
| Memory | gradient checkpointing (non-reentrant) |
| Loss masking | assistant tokens only (`DataCollatorForCompletionOnlyLM`, response template `<|im_start|>assistant\n`) |

Loss is logged every 10 steps to console and `outputs/loss_log.csv`; adapter
checkpoints are saved each epoch; peak VRAM is printed at the end of the run.

## Design decisions

- **Qwen2.5-1.5B-Instruct over Llama:** ungated download (no HF token), strong
  instruction-following at a size that trains comfortably in 8GB with QLoRA.
- **Hand-authored data with a build step:** pairs are written as compact
  `{"q":…,"a":…}` part files; `build_dataset.py` mechanically wraps each pair with
  the fixed system prompt into the required `messages` format. Identical content,
  fewer copy-paste errors, and the system prompt is defined in exactly one place.
- **VRAM fallback threshold (5.5GB free, not 8GB):** an 8GB card never has a full
  8GB free while driving a display, so a literal "<8GB free" check would always
  trigger the fallback and defeat the point of targeting the 1.5B model. 5.5GB is
  the measured floor under which the 1.5B QLoRA run would OOM.
- **Sequential model loading in `compare.py`:** base and fine-tuned models are run
  one after another (load → generate → free) rather than side by side, so the
  comparison also fits in 8GB.
- **Pinned versions** (`transformers 4.47.1 / trl 0.14.0 / peft 0.14.0 /
  bitsandbytes 0.45.0 / torch 2.5.1+cu121`): a mutually compatible set verified on
  Windows; `DataCollatorForCompletionOnlyLM` and `SFTConfig(max_seq_length=…)` are
  stable APIs in this trl release.
- **Completion-only loss:** training on assistant tokens only prevents the model
  from wasting capacity learning to predict questions and keeps the persona signal
  concentrated where it matters.
- **Eval set held out entirely:** the 40 eval questions never appear in training;
  `compare.py` runs them plus 5 fixed demo questions on both models for a direct
  style-transfer comparison.

## Known limitations

- **Style transfer more than philosophical depth:** a 1.5B model learns the voice —
  aphorisms, imagery, contempt for comfortable answers — far better than it learns
  coherent multi-step philosophical argument. Expect occasional conceptual mush
  delivered with great confidence.
- **Factual reliability is low.** The persona will confidently embroider
  biographical or historical details. This is a demo of voice, not a reference.
- **Long answers can drift or repeat** at temperature 0.8; `max_new_tokens=300`
  occasionally truncates mid-aphorism.
- **The dataset is single-turn.** Multi-turn chats in `chat.py` work via the chat
  template, but persona stability over many turns is not trained for.
- **Longest training answers truncate at 768 tokens**, so a handful of the longest
  authored answers contribute only their first ~600 words to training.
