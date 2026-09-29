"""Merge an mlx-lm LoRA adapter into the original Hugging Face Qwen3.5 checkpoint.

`mlx_lm.fuse` saves weights under mlx-lm's own names and drops the vision tower, which
llama.cpp's converter does not expect. This script keeps the original checkpoint intact —
file layout, weight names, vision tower — and only adds each LoRA delta
(scale · lora_bᵀ · lora_aᵀ) to its base weight, so the result converts to GGUF exactly
like the official model.

    python finetune/merge_lora.py --base models/Qwen3.5-2B --adapter adapters/v1 \
        --out models/qwen35-2b-beeline
"""

import argparse
import json
import shutil
from pathlib import Path

import mlx.core as mx


def hf_name(adapter_key: str) -> str:
    """language_model.model.layers.8.mlp.up_proj.lora_a -> model.language_model...weight"""
    module = adapter_key.rsplit(".", 1)[0]
    if module.startswith("language_model.model."):
        module = "model.language_model." + module[len("language_model.model.") :]
    return module + ".weight"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    scale = json.loads((args.adapter / "adapter_config.json").read_text())["lora_parameters"][
        "scale"
    ]
    lora = mx.load(str(args.adapter / "adapters.safetensors"))
    modules = sorted({key.rsplit(".", 1)[0] for key in lora})

    args.out.mkdir(parents=True, exist_ok=True)
    for path in args.base.iterdir():
        if path.suffix != ".safetensors" and path.is_file():
            shutil.copy2(path, args.out / path.name)

    merged = 0
    for shard in sorted(args.base.glob("*.safetensors")):
        weights, metadata = mx.load(str(shard), return_metadata=True)
        for module in modules:
            name = hf_name(module + ".lora_a")
            if name not in weights:
                continue
            base = weights[name]
            delta = (scale * lora[module + ".lora_b"].T.astype(mx.float32)) @ lora[
                module + ".lora_a"
            ].T.astype(mx.float32)
            if delta.shape != base.shape:
                raise ValueError(f"{name}: delta {delta.shape} != weight {base.shape}")
            weights[name] = (base.astype(mx.float32) + delta).astype(base.dtype)
            merged += 1
        mx.save_safetensors(str(args.out / shard.name), weights, metadata=metadata)
    if merged != len(modules):
        raise ValueError(f"merged {merged} of {len(modules)} LoRA modules")
    print(f"merged {merged} LoRA modules (scale {scale}) into {args.out}")


if __name__ == "__main__":
    main()
