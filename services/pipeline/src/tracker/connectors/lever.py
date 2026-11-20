"""Lever ATS Public Postings API connector implementation."""

import html
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from tracker.connectors.base import BaseATSConnector
from tracker.models.canonical import JobPostingCanonical, classify_contract_type
from tracker.models.enums import ATSProvider, WorkplaceType

logger = logging.getLogger(__name__)

_LEVER_WORKPLACE_MAP: dict[str, WorkplaceType] = {
    "remote": WorkplaceType.REMOTE,
    "hybrid": WorkplaceType.HYBRID,
    "onsite": WorkplaceType.ON_SITE,
    "on-site": WorkplaceType.ON_SITE,
}


def _resolve_lever_location(job_data: dict[str, Any], categories: dict[str, Any]) -> str:
    """Resolves job location from Lever categories, allLocations, and ISO country code.

    Args:
        job_data: Raw JSON job dictionary from Lever API.
        categories: Parsed 'categories' dictionary from Lever posting.

    Returns:
        Resolved location string enriched with 'France' when country code is 'FR'.
    """
    all_locations = categories.get("allLocations")
    if isinstance(all_locations, list):
        clean_locs = [str(loc).strip() for loc in all_locations if str(loc).strip()]
        if clean_locs:
            resolved = "; ".join(clean_locs)
        else:
            resolved = str(categories.get("location") or "").strip()
    else:
        resolved = str(categories.get("location") or "").strip()

    if not resolved:
        resolved = "France"

    country_code = str(job_data.get("country") or "").strip().upper()
    if country_code == "FR" and "france" not in resolved.lower():
        resolved = f"{resolved}, France"

    return resolved


def _assemble_description(job_data: dict[str, Any]) -> str:
    """Assembles Lever's multi-part description (intro, lists, additional/closing) into HTML.

    Supports both public v0 top-level fields and v1 nested 'content' objects.

    Args:
        job_data: Raw JSON job dictionary from Lever API.

    Returns:
        Combined and unescaped HTML description string.
    """
    sections: list[str] = []
    content_obj = job_data.get("content")
    source = content_obj if isinstance(content_obj, dict) else job_data

    intro = (
        source.get("descriptionHtml")
        or source.get("description")
        or job_data.get("descriptionPlain")
    )
    if isinstance(intro, str) and intro.strip():
        sections.append(intro.strip())

    lists = source.get("lists") or job_data.get("lists")
    if isinstance(lists, list):
        for section in lists:
            if not isinstance(section, dict):
                continue
            heading = str(section.get("text") or "").strip()
            content = str(section.get("content") or "").strip()
            if heading:
                sections.append(f"<h3>{heading}</h3>")
            if content:
                sections.append(content)

    additional = (
        source.get("additional")
        or source.get("closingHtml")
        or source.get("closing")
        or job_data.get("additionalPlain")
    )
    if isinstance(additional, str) and additional.strip():
        sections.append(additional.strip())

    combined = "\n".join(sections)
    return html.unescape(combined).strip()


def _parse_epoch_ms(timestamp_ms: int | float | None) -> datetime | None:
    """Converts Unix epoch milliseconds timestamp into a timezone-aware UTC datetime.

    Args:
        timestamp_ms: Epoch timestamp in milliseconds from Lever 'createdAt' field.

    Returns:
        Timezone-aware UTC datetime object or None if invalid.
    """
    if not isinstance(timestamp_ms, (int, float)) or timestamp_ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=UTC)
    except (ValueError, OSError, OverflowError):
        logger.debug("Failed to parse Lever epoch timestamp: %s", timestamp_ms)
        return None


def _map_workplace_type(raw_workplace: str | None) -> WorkplaceType | None:
    """Maps Lever's native workplaceType string to canonical WorkplaceType enum.

    Returns None when 'unspecified' or missing so JobPostingCanonical infers it
    from location and description text.

    Args:
        raw_workplace: Raw 'workplaceType' field from Lever JSON.

    Returns:
        Matched WorkplaceType or None for fallback inference.
    """
    if not isinstance(raw_workplace, str):
        return None
    return _LEVER_WORKPLACE_MAP.get(raw_workplace.strip().lower())


class LeverConnector(BaseATSConnector):
    """Connector for streaming job postings from the public Lever Postings API."""

    BASE_URL = "https://api.lever.co/v0/postings"
    EU_BASE_URL = "https://api.eu.lever.co/v0/postings"

    @property
    def provider(self) -> ATSProvider:
        """Returns the Lever ATS provider enum identifier."""
        return ATSProvider.LEVER

    async def fetch_jobs(
        self,
        company_slug: str,
        company_name: str,
        ats_identifier: str,
    ) -> AsyncIterator[JobPostingCanonical]:
        """Asynchronously streams validated job postings from Lever public postings endpoint.

        Automatically falls back to Lever's EU data center endpoint if the US endpoint
        returns no results (e.g., European GDPR-hosted boards).

        Args:
            company_slug: Internal unique company slug.
            company_name: Display name of the company.
            ats_identifier: Lever company site slug.

        Yields:
            Validated JobPostingCanonical instances ready for database persistence.
        """
        us_url = f"{self.BASE_URL}/{ats_identifier}?mode=json"
        payload = await self.get_json_with_retry(us_url, company_slug)

        if payload is None:
            eu_url = f"{self.EU_BASE_URL}/{ats_identifier}?mode=json"
            payload = await self.get_json_with_retry(eu_url, company_slug)

        if not isinstance(payload, list):
            return

        for raw_job in payload:
            if not isinstance(raw_job, dict):
                continue

            # Guard against non-published postings if 'state' attribute is exposed
            state = raw_job.get("state")
            if isinstance(state, str) and state.lower() != "published":
                continue

            try:
                external_id = str(raw_job["id"])
                title = str(raw_job.get("text") or "").strip()
                if not title:
                    continue

                categories = raw_job.get("categories")
                categories_dict = categories if isinstance(categories, dict) else {}

                location = _resolve_lever_location(raw_job, categories_dict)
                commitment = str(categories_dict.get("commitment") or "").strip()

                urls_obj = raw_job.get("urls")
                urls_dict = urls_obj if isinstance(urls_obj, dict) else {}
                apply_url = (
                    raw_job.get("hostedUrl")
                    or urls_dict.get("show")
                    or raw_job.get("applyUrl")
                    or urls_dict.get("apply")
                    or f"https://jobs.lever.co/{ats_identifier}/{external_id}"
                )

                description_raw = _assemble_description(raw_job)
                published_at = _parse_epoch_ms(raw_job.get("createdAt"))
                workplace_type = _map_workplace_type(raw_job.get("workplaceType"))

                # Enrich contract signal with Lever's structured commitment tag
                classification_title = f"{title} ({commitment})" if commitment else title
                contract_type = classify_contract_type(
                    title=classification_title,
                    description=description_raw,
                )

                yield JobPostingCanonical(
                    external_id=external_id,
                    company_slug=company_slug,
                    company_name=company_name,
                    ats_provider=self.provider,
                    title=title,
                    location=location,
                    apply_url=apply_url,
                    description_raw=description_raw,
                    contract_type=contract_type,
                    workplace_type=workplace_type,
                    published_at=published_at,
                )

            except Exception as exc:
                logger.error(
                    "Failed to parse Lever job %s for '%s': %s",
                    raw_job.get("id"),
                    company_slug,
                    exc,
                )
