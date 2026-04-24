import type { AIModelAdapter } from './model-adapter';

class ModelRegistry {
  private adapters: Map<string, AIModelAdapter> = new Map();
  private defaultModel: string | null = null;

  register(adapter: AIModelAdapter): void {
    this.adapters.set(adapter.name, adapter);
  }

  get(name: string): AIModelAdapter | undefined {
    return this.adapters.get(name);
  }

  list(): AIModelAdapter[] {
    return Array.from(this.adapters.values());
  }

  setDefault(name: string): void {
    if (this.adapters.has(name)) {
      this.defaultModel = name;
    }
  }

  getDefault(): AIModelAdapter | undefined {
    if (this.defaultModel) {
      return this.adapters.get(this.defaultModel);
    }
    return this.adapters.values().next().value;
  }
}

// Singleton instance
export const modelRegistry = new ModelRegistry();
