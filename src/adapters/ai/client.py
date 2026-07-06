import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import asyncio
import aiohttp

logger = logging.getLogger(__name__)

class LocalAIClient(ABC):
    """Abstract client for local LLM/VLM HTTP services (Ollama, LM Studio, etc.)."""

    def __init__(self, base_url: str, timeout: int = 30):
        self.base_url = base_url.rstrip('/')
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session = None

    async def __aenter__(self):
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    @abstractmethod
    async def close(self) -> None:
        """Close any open connections."""
        pass

    async def _ensure_session(self):
        """Ensure HTTP session is initialized."""
        if self.session is None:
            self.session = aiohttp.ClientSession(timeout=self.timeout)

class OllamaClient(LocalAIClient):
    """Client for the Ollama REST API (``/api/generate``)."""

    async def close(self) -> None:
        """Close any open connections."""
        try:
            if self.session:
                await self.session.close()
            logger.info("Closed Ollama client connection")
        except Exception as e:
            logger.error(f"Error closing Ollama client: {e}")

    async def generate(self, model: str, prompt: str, **kwargs) -> Dict[str, Any]:
        """Generate text using Ollama."""
        try:
            await self._ensure_session()
            
            url = f"{self.base_url}/api/generate"
            data = {
                "model": model,
                "prompt": prompt,
                **kwargs
            }
            
            async with self.session.post(url, json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Ollama API error: {response.status} - {error_text}")
                    raise Exception(f"Ollama API error: {response.status}")
                
                result = await response.json()
                return result
                
        except asyncio.TimeoutError:
            logger.error("Timeout while calling Ollama API")
            raise
        except Exception as e:
            logger.error(f"Error calling Ollama API: {e}")
            raise

class LMStudioClient(LocalAIClient):
    """Client for LM Studio using the OpenAI-compatible chat completions API."""

    async def close(self) -> None:
        """Close any open connections."""
        try:
            if self.session:
                await self.session.close()
            logger.info("Closed LM Studio client connection")
        except Exception as e:
            logger.error(f"Error closing LM Studio client: {e}")

    async def chat_completions(self, model: str, messages: list, **kwargs) -> Dict[str, Any]:
        """Get chat completions from LM Studio."""
        try:
            await self._ensure_session()
            
            url = f"{self.base_url}/v1/chat/completions"
            data = {
                "model": model,
                "messages": messages,
                **kwargs
            }
            
            async with self.session.post(url, json=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"LM Studio API error: {response.status} - {error_text}")
                    raise Exception(f"LM Studio API error: {response.status}")
                
                result = await response.json()
                return result
                
        except asyncio.TimeoutError:
            logger.error("Timeout while calling LM Studio API")
            raise
        except Exception as e:
            logger.error(f"Error calling LM Studio API: {e}")
            raise
