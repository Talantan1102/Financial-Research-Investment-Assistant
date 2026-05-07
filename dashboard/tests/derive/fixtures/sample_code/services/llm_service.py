# fixture: sample llm service, simulating real backend/app/services/llm_service.py
class LLMService:
    def chat(self, prompt: str, tier: Tier, response_format: dict | None = None):
        max_tokens = 1024
        return ...
