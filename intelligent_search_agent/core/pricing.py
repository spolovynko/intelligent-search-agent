DEFAULT_PRICING = {
    "input_per_million": 0.15,
    "output_per_million": 0.60,
    "description": "Default pricing placeholder",
}

MODEL_PRICING = {
    "gpt-4o-mini": {
        "input_per_million": 0.15,
        "output_per_million": 0.60,
        "description": "Small, low-cost general assistant model",
    },
    "gpt-4o": {
        "input_per_million": 2.50,
        "output_per_million": 10.00,
        "description": "General multimodal assistant model",
    },
    "gpt-4.1-mini": {
        "input_per_million": 0.40,
        "output_per_million": 1.60,
        "description": "Efficient general assistant model",
    },
    "gpt-4.1": {
        "input_per_million": 2.00,
        "output_per_million": 8.00,
        "description": "High capability general assistant model",
    },
}


def pricing_for(model: str) -> dict[str, float | str]:
    return MODEL_PRICING.get(model, DEFAULT_PRICING)
