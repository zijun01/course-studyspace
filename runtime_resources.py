"""Small, dependency-light helpers for releasing optional accelerator memory."""
from __future__ import annotations

import gc


def release_accelerator_cache(mlx_core=None) -> None:
    """Release Python objects and MLX's Metal allocation cache when available."""
    gc.collect()
    if mlx_core is None:
        try:
            import mlx.core as mlx_core
        except (ImportError, RuntimeError):
            return
    mlx_core.clear_cache()
    gc.collect()
