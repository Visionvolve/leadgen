"""Shared Perplexity API client with model selection, retry, and cost tracking.

Centralizes all Perplexity sonar API calls so enrichers don't each implement
HTTP, retry, and cost logic independently.

Usage:
    from api.services.perplexity_client import PerplexityClient

    client = PerplexityClient(api_key="pplx-xxx")
    result = client.query(
        system_prompt="You are a research assistant.",
        user_prompt="Research Acme Corp",
        model="sonar-pro",
        max_tokens=600,
    )
    print(result.content, result.cost_usd)
"""

import logging
import os
import time

import requests

from .rate_limiter import AdaptiveRateLimiter

logger = logging.getLogger(__name__)

# Module-level rate limiter instance (lazy-initialized)
_rate_limiter = None

# Pricing per 1M tokens (input + output combined for sonar models)
MODEL_PRICING = {
    "sonar": {"input_per_m": 1.0, "output_per_m": 1.0},
    "sonar-pro": {"input_per_m": 3.0, "output_per_m": 15.0},
    "sonar-reasoning-pro": {"input_per_m": 2.0, "output_per_m": 8.0},
    "sonar-reasoning": {"input_per_m": 1.0, "output_per_m": 5.0},
}

RETRYABLE_STATUS_CODES = {429, 500, 502, 503}


def get_rate_limiter():
    """Get or create the module-level AdaptiveRateLimiter."""
    global _rate_limiter
    if _rate_limiter is None:
        try:
            from flask import current_app

            max_rpm = current_app.config.get("PERPLEXITY_MAX_RPM", 20)
        except RuntimeError:
            max_rpm = int(os.environ.get("PERPLEXITY_MAX_RPM", "20"))
        _rate_limiter = AdaptiveRateLimiter(max_rpm=max_rpm)
    return _rate_limiter


class PerplexityResponse:
    """Structured response from a Perplexity API call."""

    __slots__ = ("content", "model", "input_tokens", "output_tokens", "cost_usd")

    def __init__(self, content, model, input_tokens, output_tokens, cost_usd):
        self.content = content
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_usd = cost_usd


class PerplexityClient:
    """Shared Perplexity API client."""

    def __init__(
        self,
        api_key=None,
        base_url="https://api.perplexity.ai",
        default_model="sonar",
        timeout=60,
        max_retries=2,
        retry_delay=1.0,
    ):
        self.api_key = api_key or os.environ.get("PERPLEXITY_API_KEY", "")
        self.base_url = base_url
        self.default_model = default_model
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def query(
        self,
        system_prompt,
        user_prompt,
        model=None,
        max_tokens=600,
        temperature=0.1,
        search_recency_filter="month",
    ):
        """Send a query to Perplexity sonar API.

        Args:
            system_prompt: System message for the model
            user_prompt: User message / research query
            model: Model name (default: self.default_model)
            max_tokens: Max output tokens
            temperature: Sampling temperature
            search_recency_filter: Recency filter for search results

        Returns:
            PerplexityResponse with content, tokens, and cost

        Raises:
            requests.HTTPError: On non-retryable errors or after retries exhausted
        """
        model = model or self.default_model

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "search_recency_filter": search_recency_filter,
        }

        headers = {
            "Authorization": "Bearer {}".format(self.api_key),
            "Content-Type": "application/json",
        }

        limiter = get_rate_limiter()
        last_error = None
        for attempt in range(1 + self.max_retries):
            try:
                limiter.acquire()
                resp = requests.post(
                    "{}/chat/completions".format(self.base_url),
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()

                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})

                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                cost_usd = self._estimate_cost(model, input_tokens, output_tokens)

                limiter.report_success()
                return PerplexityResponse(
                    content=content,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                )

            except requests.HTTPError as e:
                last_error = e
                status = getattr(resp, "status_code", 0)

                if status == 429:
                    limiter.report_429()

                if status not in RETRYABLE_STATUS_CODES:
                    raise

                if attempt < self.max_retries:
                    delay = min(2**attempt, 60)
                    logger.warning(
                        "Perplexity API %s (attempt %d/%d), retrying in %.1fs",
                        status,
                        attempt + 1,
                        1 + self.max_retries,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    raise

        raise last_error  # Should never reach here, but safety net

    @staticmethod
    def _estimate_cost(model, input_tokens, output_tokens):
        """Estimate USD cost based on model pricing."""
        pricing = MODEL_PRICING.get(model, MODEL_PRICING["sonar"])
        input_cost = (input_tokens / 1_000_000) * pricing["input_per_m"]
        output_cost = (output_tokens / 1_000_000) * pricing["output_per_m"]
        return round(input_cost + output_cost, 6)
