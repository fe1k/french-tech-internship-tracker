"""Greenhouse ATS Public Board API connector implementation."""

import html
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from tracker.connectors.base import BaseATSConnector
from tracker.models.canonical import JobPostingCanonical
from tracker.models.enums import ATSProvider

logger = logging.getLogger(__name__)


def _sanitize_html_content(raw_content: str | None) -> str:
    """Sanitizes double-escaped HTML entities from Greenhouse content body.

    Args:
        raw_content: Raw job description content string from ATS payload.

    Returns:
        Unescaped clean HTML string.
    """
    if not raw_content:
        return ""
    # Perform a two-pass unescape to resolve double-encoded entities (&amp;lt; -> &lt; -> <)
    unescaped = html.unescape(raw_content)
    if "&lt;" in unescaped or "&gt;" in unescaped or "&amp;" in unescaped:
        unescaped = html.unescape(unescaped)

    return unescaped.strip()


def _resolve_location(job_data: dict[str, Any]) -> str:
    """Resolves job location using a cascading strategy across location and offices fields.

    Args:
        job_data: Raw JSON job dictionary from Greenhouse API.

    Returns:
        Resolved location string defaulting to 'France'.
    """
    # 1. Primary check: location object name
    location_obj = job_data.get("location")
    if isinstance(location_obj, dict):
        loc_name = location_obj.get("name")
        if loc_name and loc_name.strip():
            return loc_name.strip()

    # 2. Secondary check: iterate through offices array
    offices = job_data.get("offices")
    if isinstance(offices, list):
        for office in offices:
            if isinstance(office, dict):
                off_loc = office.get("location") or office.get("name")
                if off_loc and off_loc.strip():
                    return off_loc.strip()

    # 3. Fallback default location
    return "France"


def _parse_published_at(date_str: str | None) -> datetime | None:
    """Parses ISO 8601 date string with timezone offset into datetime.

    Args:
        date_str: ISO formatted timestamp string from ATS payload.

    Returns:
        Parsed datetime object or None if parsing fails.
    """
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        logger.debug("Failed to parse ISO datetime string: %s", date_str)
        return None


class GreenhouseConnector(BaseATSConnector):
    """Connector for streaming job postings from the public Greenhouse Job Board API."""

    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    @property
    def provider(self) -> ATSProvider:
        """Returns the Greenhouse ATS provider enum identifier."""
        return ATSProvider.GREENHOUSE

    async def fetch_jobs(
        self,
        company_slug: str,
        company_name: str,
        ats_identifier: str,
    ) -> AsyncIterator[JobPostingCanonical]:
        """Asynchronously streams validated job postings from Greenhouse public board.

        Args:
            company_slug: Internal unique company slug.
            company_name: Display name of the company.
            ats_identifier: Greenhouse public board token.

        Yields:
            Validated JobPostingCanonical instances ready for database persistence.
        """
        url = f"{self.BASE_URL}/{ats_identifier}/jobs?content=true"
        payload = await self.get_json_with_retry(url, company_slug)

        if not isinstance(payload, dict) or "jobs" not in payload:
            return

        for raw_job in payload["jobs"]:
            try:
                external_id = str(raw_job["id"])
                title = raw_job.get("title", "").strip()
                if not title:
                    continue

                apply_url = (
                    raw_job.get("absolute_url")
                    or f"https://boards.greenhouse.io/{ats_identifier}/jobs/{external_id}"
                )
                description_raw = _sanitize_html_content(raw_job.get("content"))
                location = _resolve_location(raw_job)
                published_at = _parse_published_at(raw_job.get("updated_at"))

                # Instantiating Pydantic model automatically computes:
                # 1. contract_type (STAGE > CDD > ALTERNANCE)
                # 2. dedup_hash (SHA-256)
                yield JobPostingCanonical(
                    external_id=external_id,
                    company_slug=company_slug,
                    company_name=company_name,
                    ats_provider=self.provider,
                    title=title,
                    location=location,
                    apply_url=apply_url,
                    description_raw=description_raw,
                    published_at=published_at,
                )

            except Exception as exc:
                logger.error(
                    "Failed to parse Greenhouse job %s for '%s': %s",
                    raw_job.get("id"),
                    company_slug,
                    exc,
                )