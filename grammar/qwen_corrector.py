from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import ctranslate2
from transformers import AutoTokenizer

from grammar.config import BASE_DIR


SYSTEM_PROMPT = """You are a conservative grammar-correction engine.

Correct only objective grammatical, spelling, and punctuation errors.

Rules:
1. Preserve the original meaning exactly.
2. Preserve the original tone and wording whenever possible.
3. Do not paraphrase.
4. Do not improve style.
5. Do not make the sentence more formal.
6. Do not add or remove information.
7. Do not change names, numbers, dates, times, amounts, URLs, email
   addresses, technical terms, product names, version numbers, file names,
   identifiers, or formatting.
8. Make the minimum number of edits required.
9. If the sentence is already grammatically acceptable, return it unchanged.
10. Return only the corrected sentence.

Examples:
Input: Please send the report to Ravi by 5 PM.
Output: Please send the report to Ravi by 5 PM.

Input: She have completed the report.
Output: She has completed the report.
"""


@dataclass(slots=True)
class QwenCandidate:
    prompt: str
    candidate: str


class QwenCorrector:
    def __init__(self, model_name: str = "qwen", threads: int = 8) -> None:
        models = self._load_models()
        if model_name not in models:
            raise KeyError(f"Model profile {model_name!r} not found in models.json")

        profile = models[model_name]
        if profile.get("architecture") != "decoder-only":
            raise ValueError(f"Model profile {model_name!r} is not decoder-only")

        self.model_path = self._resolve(profile["model_path"])
        self.tokenizer_path = self._resolve(profile["tokenizer_path"])
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(self.tokenizer_path),
            local_files_only=True,
            use_fast=True,
        )
        self.generator = ctranslate2.Generator(
            str(self.model_path),
            device="cpu",
            compute_type="int8",
            inter_threads=1,
            intra_threads=threads,
        )

    def _load_models(self) -> dict:
        import json

        with (BASE_DIR / "models.json").open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _resolve(self, path_value: str) -> Path:
        path = Path(path_value)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path.resolve()

    def build_prompt(self, text: str) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Correct the sentence with the minimum possible changes.\n"
                    f"Sentence: {text}\n"
                    "Corrected sentence:"
                ),
            },
        ]
        return self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

    def generate_candidate(self, text: str) -> QwenCandidate:
        prompt = self.build_prompt(text)
        prompt_ids = self.tokenizer.encode(prompt, add_special_tokens=False)
        prompt_tokens = self.tokenizer.convert_ids_to_tokens(prompt_ids)
        results = self.generator.generate_batch(
            [prompt_tokens],
            beam_size=1,
            sampling_topk=1,
            sampling_topp=1.0,
            sampling_temperature=1.0,
            max_length=128,
            include_prompt_in_result=False,
            repetition_penalty=1.05,
            no_repeat_ngram_size=4,
            end_token=self.tokenizer.eos_token,
        )
        output_ids = results[0].sequences_ids[0]
        candidate = self.tokenizer.decode(
            output_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        ).strip()
        return QwenCandidate(prompt=prompt, candidate=candidate)

