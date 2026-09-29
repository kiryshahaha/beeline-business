"""Check the chunked gated delta rule against mlx-lm's per-token loop (needs MLX).

    python finetune/check_gated_delta.py

Compares outputs, final states and gradients on random and on highly similar keys
(the case where a power-series inverse overflows), and measures memory on 1 500 tokens.
"""

import time

import gated_delta_chunked as gdc
import mlx.core as mx

TOLERANCE = 1e-5


def make_inputs(length: int, heads: int, dim: int, similar_keys: bool):
    if similar_keys:
        keys = mx.random.normal((1, 1, heads, dim)) + 0.05 * mx.random.normal(
            (1, length, heads, dim)
        )
        gate = mx.random.uniform(0.97, 1.0, (1, length, heads))
        beta = mx.random.uniform(0.9, 1.0, (1, length, heads))
    else:
        keys = mx.random.normal((1, length, heads, dim))
        gate = mx.random.uniform(0.3, 1.0, (1, length, heads))
        beta = mx.random.uniform(0.0, 1.0, (1, length, heads))
    # Same normalisation as the Qwen3.5 layer before the recurrence.
    keys = mx.fast.rms_norm(keys, None, 1e-6) * dim**-0.5
    queries = mx.fast.rms_norm(mx.random.normal((1, length, heads, dim)), None, 1e-6) * dim**-1.0
    values = mx.random.normal((1, length, heads, dim))
    state = mx.random.normal((1, heads, dim, dim)) * 0.1
    return queries, keys, values, gate, beta, state


def total(fn, inputs):
    queries, keys, _, gate, beta, state = inputs
    return lambda values: sum(
        (part**2).sum() for part in fn(queries, keys, values, gate, beta, state)
    )


def main() -> None:
    mx.random.seed(0)
    worst = 0.0
    for similar in (False, True):
        for length in (1, 63, 64, 300, 1000):
            inputs = make_inputs(length, 16, 128, similar)
            y_ref, s_ref = gdc._sequential(*inputs)
            y, s = gdc.gated_delta_chunked(*inputs)
            diff = max(mx.abs(y - y_ref).max().item(), mx.abs(s - s_ref).max().item())
            worst = max(worst, diff)
            label = "похожие ключи" if similar else "случайные ключи"
            print(f"{label:16} T={length:5}: max расхождение {diff:.1e}")
    inputs = make_inputs(90, 4, 32, similar_keys=True)
    grad_ref = mx.grad(total(gdc._sequential, inputs))(inputs[2])
    grad = mx.grad(total(gdc.gated_delta_chunked, inputs))(inputs[2])
    grad_diff = mx.abs(grad - grad_ref).max().item()
    print(f"градиенты: max расхождение {grad_diff:.1e}")

    inputs = make_inputs(1500, 16, 128, similar_keys=True)
    mx.reset_peak_memory()
    started = time.perf_counter()
    mx.eval(mx.grad(total(gdc.gated_delta_chunked, inputs))(inputs[2]))
    print(
        f"1500 токенов, прямой и обратный проход: {time.perf_counter() - started:.2f} с, "
        f"пик памяти {mx.get_peak_memory() / 2**20:.0f} МБ"
    )
    assert worst < TOLERANCE and grad_diff < TOLERANCE, "блочный расчёт расходится с исходным"
    print("OK")


if __name__ == "__main__":
    main()
