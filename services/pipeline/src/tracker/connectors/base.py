"""Abstract Base Class for all Applicant Tracking System (ATS) connectors."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx

from tracker.models.canonical import JobPostingCanonical
from tracker.models.enums import ATSProvider


class BaseATSConnector(ABC):
    """Abstract interface defining the mandatory contract for ATS connectors."""

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
