"""Chunked gated delta rule for training Qwen3.5 linear-attention layers with MLX.

In training mode mlx-lm runs the gated delta recurrence as a per-token Python loop and
keeps a [Dv, Dk] state for every token for the backward pass — about 1 MB per token and
layer, which exhausts a 16 GB Mac on a 1 500-token prompt. The Metal kernel used for
inference has no gradient.

This module computes the same recurrence chunk by chunk (the WY form used by GPU training
kernels): inside a chunk everything is dense matrix algebra, and only the chunk-to-chunk
state update is sequential. All operations are differentiable MLX ops.

Recurrence per head, g in (0, 1], state S is [Dv, Dk]:
    S_t = g_t S_{t-1} + u_t k_t^T,   u_t = beta_t (v_t - g_t S_{t-1} k_t),   y_t = S_t q_t
Within a chunk with cumulative log-decay G and initial state S0:
    (I + A) U = diag(beta) V - diag(beta e^G) K S0^T,  A_ti = beta_t e^{G_t-G_i} k_t.k_i (i<t)
    Y = diag(e^G) Q S0^T + (M * Q K^T) U,               M_ti = e^{G_t-G_i} (i<=t)
    S_C = e^{G_C} S0 + U^T diag(e^{G_C-G}) K
"""

import mlx.core as mx
from mlx_lm.models import gated_delta

CHUNK = 64
_sequential = gated_delta.gated_delta_ops


def _unit_lower_inverse(a: mx.array, size: int) -> mx.array:
    """(I + A)^-1 for strictly lower-triangular A, by recursive block inversion.

    A power series would be exact too, but with similar neighbouring keys its terms grow
    huge and cancel, which overflows float32; block inversion stays small.
    """
    return _invert_unit_lower(mx.eye(size, dtype=a.dtype) + a)


def _invert_unit_lower(m: mx.array) -> mx.array:
    size = m.shape[-1]
    if size <= 8:  # forward substitution: row_i = e_i - sum_{j<i} m_ij row_j
        eye = mx.eye(size, dtype=m.dtype)
        rows = [mx.broadcast_to(eye[0], m.shape[:-2] + (size,))]
        for i in range(1, size):
            done = mx.stack(rows, axis=-2)  # [..., i, size]
            rows.append(eye[i] - (m[..., i : i + 1, :i] @ done)[..., 0, :])
        return mx.stack(rows, axis=-2)
    half = size // 2
    top_left = _invert_unit_lower(m[..., :half, :half])
    bottom_right = _invert_unit_lower(m[..., half:, half:])
    bottom_left = -(bottom_right @ m[..., half:, :half] @ top_left)
    zeros = mx.zeros(top_left.shape[:-1] + (size - half,), dtype=m.dtype)
    top = mx.concatenate([top_left, zeros], axis=-1)
    bottom = mx.concatenate([bottom_left, bottom_right], axis=-1)
    return mx.concatenate([top, bottom], axis=-2)


def gated_delta_chunked(q, k, v, g, beta, state=None, mask=None, chunk: int = CHUNK):
    if mask is not None or g.ndim != 3:
        return _sequential(q, k, v, g, beta, state, mask)
    batch, length, heads_k, dim_k = q.shape
    heads_v, dim_v = v.shape[-2:]
    if (repeat := heads_v // heads_k) > 1:
        q = mx.repeat(q, repeat, -2)
        k = mx.repeat(k, repeat, -2)
    if state is None:
        state = mx.zeros((batch, heads_v, dim_v, dim_k), dtype=mx.float32)

    # Padding tokens at the end leave the state unchanged: k = v = beta = 0, g = 1.
    pad = (-length) % chunk
    if pad:
        widths = [(0, 0), (0, pad), (0, 0), (0, 0)]
        q, k, v = (mx.pad(t, widths) for t in (q, k, v))
        g = mx.pad(g, [(0, 0), (0, pad), (0, 0)], constant_values=1.0)
        beta = mx.pad(beta, [(0, 0), (0, pad), (0, 0)])
    chunks = (length + pad) // chunk

    def split(t):  # [B, T, H, D] -> [B, H, N, C, D]
        t = t.astype(mx.float32).reshape(batch, chunks, chunk, heads_v, -1)
        return t.transpose(0, 3, 1, 2, 4)

    qc, kc, vc = split(q), split(k), split(v)
    log_g = mx.log(mx.maximum(g.astype(mx.float32), 1e-30))
    log_g = log_g.reshape(batch, chunks, chunk, heads_v).transpose(0, 3, 1, 2)
    beta_c = beta.astype(mx.float32).reshape(batch, chunks, chunk, heads_v)
    beta_c = beta_c.transpose(0, 3, 1, 2)

    cum = mx.cumsum(log_g, axis=-1)  # G, [B, H, N, C]
    diff = cum[..., :, None] - cum[..., None, :]  # G_t - G_i
    rows = mx.arange(chunk)
    strict = rows[:, None] > rows[None, :]
    inclusive = rows[:, None] >= rows[None, :]
    decay_strict = mx.where(strict, mx.exp(mx.where(strict, diff, 0.0)), 0.0)
    decay_inclusive = mx.where(inclusive, mx.exp(mx.where(inclusive, diff, 0.0)), 0.0)

    k_t = kc.swapaxes(-1, -2)
    a = beta_c[..., :, None] * (kc @ k_t) * decay_strict
    inverse = _unit_lower_inverse(a, chunk)
    w_v = inverse @ (beta_c[..., None] * vc)  # [B, H, N, C, Dv]
    w_k = inverse @ ((beta_c * mx.exp(cum))[..., None] * kc)  # [B, H, N, C, Dk]
    attend = decay_inclusive * (qc @ k_t)  # [B, H, N, C, C]
    q_decayed = mx.exp(cum)[..., None] * qc
    tail = mx.exp(cum[..., -1:] - cum)[..., None] * kc  # e^{G_C - G_i} k_i
    total = mx.exp(cum[..., -1])  # e^{G_C}, [B, H, N]

    outputs = []
    for n in range(chunks):
        state_t = state.swapaxes(-1, -2)  # [B, H, Dk, Dv]
        u = w_v[:, :, n] - w_k[:, :, n] @ state_t
        outputs.append(q_decayed[:, :, n] @ state_t + attend[:, :, n] @ u)
        state = total[:, :, n, None, None] * state + u.swapaxes(-1, -2) @ tail[:, :, n]
    y = mx.stack(outputs, axis=2)  # [B, H, N, C, Dv]
    y = y.transpose(0, 2, 3, 1, 4).reshape(batch, chunks * chunk, heads_v, dim_v)
    return y[:, :length].astype(q.dtype), state


def install() -> None:
    """Route mlx-lm's training path (use_kernel=False) through the chunked version."""
    gated_delta.gated_delta_ops = gated_delta_chunked
