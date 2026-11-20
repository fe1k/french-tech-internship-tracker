"""Abstract Base Class and shared HTTP resilience for ATS connectors."""

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import httpx

from tracker.models.canonical import JobPostingCanonical
from tracker.models.enums import ATSProvider

logger = logging.getLogger(__name__)


class BaseATSConnector(ABC):
    """Abstract interface defining the mandatory contract and HTTP utilities for ATS connectors."""

    MAX_RETRIES = 3
    BASE_DELAY_SECONDS = 1.0

    def __init__(self, client: httpx.AsyncClient) -> None:
        """Initializes the connector with a shared async HTTP client instance.

        Args:
            client: Pre-configured httpx.AsyncClient instance.
        """
        self.client = client

    @property
    @abstractmethod
    def provider(self) -> ATSProvider:
        """Unique ATS provider enum identifier."""
        ...

    async def get_json_with_retry(
        self,
        url: str,
        company_slug: str,
    ) -> Any | None:
        """Executes an HTTP GET request with exponential backoff and jitter retry logic.

        Args:
            url: Full target API URL endpoint.
            company_slug: Internal company slug for structured logging context.

        Returns:
            Parsed JSON payload (dict or list) or None if request fails permanently.
        """
        provider_name = self.provider.value

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await self.client.get(url)

                if response.status_code == 200:
                    return response.json()

                if response.status_code == 404:
                    logger.warning(
                        "%s board not found for '%s' (HTTP 404): %s",
                        provider_name,
                        company_slug,
                        url,
                    )
                    return None

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        delay = float(retry_after)
                    else:
                        backoff = self.BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                        delay = backoff + random.uniform(0, 0.5)

                    logger.warning(
                        "Rate limited by %s for '%s' (HTTP 429). Retrying in %.2fs (Attempt %d/%d)",
                        provider_name,
                        company_slug,
                        delay,
                        attempt,
                        self.MAX_RETRIES,
                    )
                    await asyncio.sleep(delay)
                    continue

                logger.warning(
                    "Unexpected HTTP %d from %s for '%s'. Retrying... (Attempt %d/%d)",
                    response.status_code,
                    provider_name,
                    company_slug,
                    attempt,
                    self.MAX_RETRIES,
                )

            except httpx.RequestError as exc:
                logger.error(
                    "Network error requesting %s API for '%s': %s (Attempt %d/%d)",
                    provider_name,
                    company_slug,
                    exc,
                    attempt,
                    self.MAX_RETRIES,
                )

            backoff = self.BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            await asyncio.sleep(backoff + random.uniform(0, 0.5))

        logger.error(
            "Max retries exceeded fetching %s jobs for '%s': %s",
            provider_name,
            company_slug,
            url,
        )
        return None

    @abstractmethod
    async def fetch_jobs(
        self,
        company_slug: str,
        company_name: str,
        ats_identifier: str,
    ) -> AsyncIterator[JobPostingCanonical]:
        """Asynchronously streams job postings from an ATS endpoint.

        Args:
            company_slug: Internal unique company slug.
            company_name: Display name of the company.
            ats_identifier: ATS board token or unique identifier slug.

        Yields:
            Validated JobPostingCanonical instances ready for persistence.
        """
        ...
