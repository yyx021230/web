from app.adapters.ai_model.seedream import SeedreamAdapter
from app.adapters.ai_model.gptimage2 import GPTImage2Adapter
from app.adapters.ai_model.registry import model_registry

# Register default models
model_registry.register(SeedreamAdapter())
model_registry.register(GPTImage2Adapter())

# Register default
model_registry.set_default("seedream")
