from typing import Any, Dict, List, Optional

DEFAULT_MODEL_ID = "Qwen/Qwen3-8B"
OPENROUTER_DEFAULT_MODEL_ID = "google/gemma-4-26b-a4b-it:free"


def build_base_models(openrouter_default_model_id: str = OPENROUTER_DEFAULT_MODEL_ID) -> List[Dict[str, Any]]:
    return [
        {
            "id": "Qwen/Qwen3-8B",
            "name": "Qwen3-8B",
            "description": "Qwen3 8B model for efficient text chat",
            "type": "text",
            "max_tokens": 32768,
            "provider": "siliconflow",
        },
        {
            "id": "Qwen/Qwen2.5-VL-72B-Instruct",
            "name": "Qwen2.5-VL-72B",
            "description": "Qwen2.5 VL 72B model with multimodal understanding",
            "type": "multimodal",
            "max_tokens": 32768,
            "provider": "siliconflow",
        },
        {
            "id": "deepseek-ai/deepseek-vl2",
            "name": "DeepSeek-VL2",
            "description": "DeepSeek VL2 multimodal model",
            "type": "multimodal",
            "max_tokens": 8192,
            "provider": "siliconflow",
        },
        {
            "id": "Qwen/Qwen3-30B-A3B",
            "name": "Qwen3-30B-A3B",
            "description": "Qwen3 30B A3B optimized architecture",
            "type": "text",
            "max_tokens": 32768,
            "provider": "siliconflow",
        },
        {
            "id": "Pro/deepseek-ai/DeepSeek-V3",
            "name": "DeepSeek-V3 Pro",
            "description": "DeepSeek V3 Pro high-performance model",
            "type": "text",
            "max_tokens": 8192,
            "provider": "siliconflow",
        },
        {
            "id": "THUDM/GLM-4-9B-0414",
            "name": "GLM-4-9B",
            "description": "GLM-4 9B balanced model",
            "type": "text",
            "max_tokens": 8192,
            "provider": "siliconflow",
        },
        {
            "id": "Qwen/Qwen3-VL-8B-Instruct",
            "name": "Qwen3-VL-8B-Instruct",
            "description": "Qwen3 VL 8B multimodal model",
            "type": "multimodal",
            "max_tokens": 32768,
            "provider": "siliconflow",
        },
        {
            "id": openrouter_default_model_id,
            "name": "Gemma 4 26B (OpenRouter Free)",
            "description": "OpenRouter free model route for low-cost experiments",
            "type": "text",
            "max_tokens": 8192,
            "provider": "openrouter",
        },
        {
            "id": "nvidia/nemotron-nano-12b-v2-vl:free",
            "name": "Nemotron Nano 12B VL (OpenRouter Free)",
            "description": "NVIDIA Nemotron Nano 12B V2 VL free route on OpenRouter",
            "type": "multimodal",
            "max_tokens": 8192,
            "provider": "openrouter",
        },
        {
            "id": "qwen/qwen3.5-9b",
            "name": "Qwen 3.5 9B (OpenRouter)",
            "description": "Qwen 3.5 9B route via OpenRouter",
            "type": "text",
            "max_tokens": 8192,
            "provider": "openrouter",
        },
    ]


def build_available_models(
    openrouter_default_model_id: str = OPENROUTER_DEFAULT_MODEL_ID,
    custom_models: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    models = build_base_models(openrouter_default_model_id)
    seen = {str(model.get("id", "")) for model in models}

    for raw_model in custom_models or []:
        model_id = str(raw_model.get("id", "")).strip()
        if not model_id or model_id in seen:
            continue

        provider = str(raw_model.get("provider", "openrouter")).strip() or "openrouter"
        models.append(
            {
                "id": model_id,
                "name": str(raw_model.get("name", model_id)).strip() or model_id,
                "description": str(raw_model.get("description", f"Custom model: {model_id}")).strip()
                or f"Custom model: {model_id}",
                "type": str(raw_model.get("type", "text")).strip() or "text",
                "max_tokens": int(raw_model.get("max_tokens", 8192)),
                "provider": provider,
            }
        )
        seen.add(model_id)

    return models
