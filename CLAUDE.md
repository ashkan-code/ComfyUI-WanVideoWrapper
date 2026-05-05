# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

A ComfyUI custom node package that wraps WanVideo and ~20 other open-source video-generation models (Ovi, MTV, UniAnimate, FantasyPortrait, FantasyTalking, MultiTalk, Lynx, FlashVSR, etc.). Described in the README as a personal sandbox — new models land here first before being considered for upstream ComfyUI. Expect rapid iteration and legacy stubs preserved for compatibility.

Published to the ComfyUI Registry as `ComfyUI-WanVideoWrapper` (version in `pyproject.toml`).

## Installation (development)

```bash
# Must be placed inside ComfyUI's custom_nodes directory
cd ComfyUI/custom_nodes
git clone <repo> ComfyUI-WanVideoWrapper
cd ComfyUI-WanVideoWrapper
pip install -r requirements.txt
```

There is no build step. Python files are imported directly by ComfyUI at startup.

## Running / Testing

There is no automated test suite. The `example_workflows/` directory contains ComfyUI workflow JSON files that serve as integration tests. To verify a change works, load ComfyUI and run the relevant workflow.

There is no linting configuration. The codebase does not use ruff, flake8, or mypy.

## Node Registration Architecture

`__init__.py` is the sole entry point ComfyUI reads. It:
1. Imports `NODE_CLASS_MAPPINGS` and `NODE_DISPLAY_NAME_MAPPINGS` from every submodule
2. Merges them into two top-level dicts ComfyUI consumes
3. Wraps each submodule import in a `try/except` so missing optional dependencies (Qwen, FantasyPortrait, UniAnimate, MTV, HuMo, Lynx, Ovi…) degrade gracefully

**Core node files** (top-level):

| File | Contents |
|---|---|
| `nodes.py` | ~35 encoding/embedding/control nodes (TextEncode, ClipVisionEncode, VACEEncode, PhantomEmbeds, SetBlockSwap, etc.) |
| `nodes_model_loading.py` | WanVideoModel class, LoRA loading/conversion, GGUF quantization |
| `nodes_sampler.py` | All sampling/inference nodes; manages cache states, attention modes, scheduler integration |
| `nodes_utility.py` | Image resize, frame extraction, VAE operations |
| `nodes_deprecated.py` | Legacy nodes kept for workflow backward-compat |
| `cache_methods/nodes_cache.py` | TeaCache, MagCache, EasyCache node wrappers |

**Per-model directories** (e.g. `wanvideo/`, `MTV/`, `Ovi/`, `unianimate/`, `fantasyportrait/`) each contain their own modules and a `nodes.py` that is imported by `__init__.py`.

## Key Patterns

### ComfyUI Node Pattern
Every node class must define:
- `INPUT_TYPES` (classmethod) — declares required/optional inputs with types and constraints
- `RETURN_TYPES` — tuple of output type strings
- `FUNCTION` — name of the method ComfyUI calls
- `CATEGORY` — menu path in the UI

```python
class MyNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",)}}
    RETURN_TYPES = ("MODEL",)
    FUNCTION = "process"
    CATEGORY = "WanVideoWrapper"

    def process(self, model):
        ...
        return (model,)
```

### Model Loading (`nodes_model_loading.py`)
- Uses `accelerate` with empty-weights context (`init_empty_weights`) for memory-efficient loading
- `WanVideoModel` extends ComfyUI's `BaseModel`; config is set via `WanVideoModelConfig`
- LoRA standardization handles lycoris, diffusers, and WanVideoFun formats before applying
- GGUF quantization is applied via `_replace_with_gguf_linear` which swaps `nn.Linear` layers with GGUF-backed equivalents

### Sampling (`nodes_sampler.py`)
- Cache strategies (TeaCache, MagCache, EasyCache) are initialized and stored as state dicts on the model object before the sampling call
- Attention mode selection (flash_attn, sageattn, radial) happens at the transformer block level via monkey-patching or block-level config
- Block swapping (offloading transformer blocks to CPU) is initialized via `SetBlockSwap` then activated inside the sampler

### Shared Utilities (`utils.py`)
- `get_torch_device()` / `get_free_memory()` — device/VRAM introspection
- `load_torch_file()` — standardized checkpoint loading with dtype handling
- LoRA application helpers used by both `nodes_model_loading.py` and per-model directories

## Adding a New Model

1. Create a subdirectory (e.g. `mymodel/`) with the model implementation and a `nodes.py`
2. In `mymodel/nodes.py`, define `NODE_CLASS_MAPPINGS` and `NODE_DISPLAY_NAME_MAPPINGS`
3. In `__init__.py`, add an import block (wrap in `try/except` if the model has optional deps):
   ```python
   try:
       from .mymodel.nodes import NODE_CLASS_MAPPINGS as mymodel_mappings, ...
       NODE_CLASS_MAPPINGS.update(mymodel_mappings)
       ...
   except Exception as e:
       print(f"Could not load mymodel nodes: {e}")
   ```
4. Bump `version` in `pyproject.toml`
5. Add an example workflow JSON to `example_workflows/`

## Publishing

Merging a `pyproject.toml` change to `main` automatically triggers `.github/workflows/publish.yml`, which publishes to the ComfyUI Registry via `ComfyOrg/publish-node-action`.
