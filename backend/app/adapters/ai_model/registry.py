from __future__ import annotations
"""AI 模型注册中心"""

from app.adapters.ai_model.base import AIModelAdapter


class ModelRegistry:
    _adapters: dict[str, AIModelAdapter] = {}
    _default: str | None = None

    @classmethod
    def register(cls, adapter: AIModelAdapter) -> None:
        cls._adapters[adapter.name] = adapter

    @classmethod
    def get(cls, name: str) -> AIModelAdapter | None:
        return cls._adapters.get(name)

    @classmethod
    def list(cls) -> list[AIModelAdapter]:
        return list(cls._adapters.values())

    @classmethod
    def set_default(cls, name: str) -> None:
        if name in cls._adapters:
            cls._default = name

    @classmethod
    def get_default(cls) -> AIModelAdapter | None:
        if cls._default:
            return cls._adapters.get(cls._default)
        return next(iter(cls._adapters.values()), None)


# Singleton
model_registry = ModelRegistry
