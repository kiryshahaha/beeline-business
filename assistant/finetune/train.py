"""mlx-lm LoRA training with the chunked gated delta rule for Qwen3.5.

Accepts the same arguments as `mlx_lm.lora`; see finetune/README.md for the full command.
"""

import sys

from gated_delta_chunked import install

install()

from mlx_lm import lora  # noqa: E402  (must import after the patch is installed)

if __name__ == "__main__":
    sys.exit(lora.main())
