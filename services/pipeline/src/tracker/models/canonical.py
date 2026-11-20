"""Canonical job posting domain model, sanitization and classification utilities."""

import hashlib
import re
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator

from tracker.models.enums import ATSProvider, ContractType, WorkplaceType

_HTML_TAG_RE = re.compile(r"<[^>]+>")

_SENIORITY_TITLE_RE = re.compile(
    r"\b(senior|sr\.?|principal|staff|lead|manager|director|head of|vp|vice president|chief|"
    r"architect)\b"
)

_FRENCH_LOCATION_KEYWORDS = (
    "france",
    "paris",
    "lyon",
    "nantes",
    "bordeaux",
    "toulouse",
    "lille",
    "sophia antipolis",
    "grenoble",
    "marseille",
)


def _strip_html(text: str) -> str:
    """Removes HTML tags and collapses consecutive whitespace."""
    without_tags = _HTML_TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", without_tags).strip()


def sanitize_location(raw_location: str, max_length: int = 150) -> str:
    """Normalizes and truncates location strings to fit database's VARCHAR(150).

    When multi-location strings exceed max_length, segments mentioning France or major
    French tech hubs are prioritized before truncating safely.

    Args:
        raw_location: Raw location string extracted from the ATS.
        max_length: Maximum allowed string length in the database schema.

    Returns:
        Cleaned location string guaranteed to be at most max_length characters.
    """
    cleaned = re.sub(r"\s+", " ", raw_location).strip()
    if not cleaned:
        return "France"

    if len(cleaned) <= max_length:
        return cleaned

    segments = [seg.strip() for seg in re.split(r"[;|]", cleaned) if seg.strip()]
    french_segments = [
        seg for seg in segments if any(kw in seg.lower() for kw in _FRENCH_LOCATION_KEYWORDS)
    ]

    prioritized = french_segments if french_segments else segments
    joined = "; ".join(prioritized)

    if len(joined) <= max_length:
        return joined

    return joined[: max_length - 3].rstrip(" ;,") + "..."


def classify_contract_type(title: str, description: str = "") -> ContractType:
    """Classifies contract type using a two-stage hierarchical evaluation.

    Priority order: STAGE > CDD > ALTERNANCE > UNKNOWN.
    Stage 1 inspects the job title (high signal).
    Stage 2 inspects the sanitized description with seniority exclusion guardrails
    to prevent English words like 'stage' (phase) from triggering false positives.

    Args:
        title: The job position title.
        description: The raw job description body text or HTML.

    Returns:
        The matched ContractType enum value.
    """
    title_lower = title.lower()

    # TITLE-ONLY EVALUATION (Stage 1)
    title_stage_patterns = [
        r"\bstage\b",
        r"\bstagiaire\b",
        r"\binternship\b",
        r"\bintern\b",
        r"\bgratification\b",
        r"\bpfe\b",
        r"end[- ]of[- ]studies",
        r"\bc[ée]sure\b",
    ]
    if any(re.search(pattern, title_lower) for pattern in title_stage_patterns):
        return ContractType.STAGE

    title_cdd_patterns = [
        r"\bcdd\b",
        r"fixed[- ]term",
        r"contrat [àa] dur[ée]e d[ée]termin[ée]e",
    ]
    if any(re.search(pattern, title_lower) for pattern in title_cdd_patterns):
        return ContractType.CDD

    title_alternance_patterns = [
        r"\balternance\b",
        r"\balternant\b",
        r"\bapprentissage\b",
        r"contrat de pro",
        r"professionnalisation",
    ]
    if any(re.search(pattern, title_lower) for pattern in title_alternance_patterns):
        return ContractType.ALTERNANCE

    # DESCRIPTION-ONLY EVALUATION (Stage 2) with seniority exclusion
    if _SENIORITY_TITLE_RE.search(title_lower):
        return ContractType.UNKNOWN

    clean_desc_lower = _strip_html(description).lower()
    if not clean_desc_lower:
        return ContractType.UNKNOWN

    # Avoid bare '\bstage\b' or '\bintern\b' in body text due to English false positives
    desc_stage_patterns = [
        r"\bstagiaire\b",
        r"\binternship\b",
        r"\bgratification\b",
        r"convention de stage",
        r"offre de stage",
        r"stage de fin d['’][ée]tudes",
        r"\bpfe\b",
        r"end[- ]of[- ]studies",
        r"ann[ée]e de c[ée]sure",
    ]
    if any(re.search(pattern, clean_desc_lower) for pattern in desc_stage_patterns):
        return ContractType.STAGE

    desc_cdd_patterns = [
        r"\bcdd\b",
        r"fixed[- ]term",
        r"contrat [àa] dur[ée]e d[ée]termin[ée]e",
    ]
    if any(re.search(pattern, clean_desc_lower) for pattern in desc_cdd_patterns):
        return ContractType.CDD

    desc_alternance_patterns = [
        r"\balternance\b",
        r"\balternant\b",
        r"\bapprentissage\b",
        r"contrat de professionnalisation",
        r"rythme d['’]alternance",
    ]
    if any(re.search(pattern, clean_desc_lower) for pattern in desc_alternance_patterns):
        return ContractType.ALTERNANCE

    return ContractType.UNKNOWN


def classify_workplace_type(location: str, description: str = "") -> WorkplaceType:
    """Infers workplace modality (REMOTE, ON_SITE, HYBRID) from location and description.

    Args:
        location: Normalized job location string.
        description: Raw job description text or HTML.

    Returns:
        Inferred WorkplaceType enum value, defaulting to HYBRID.
    """
    loc_lower = location.lower()

    if re.search(r"\b(remote|t[ée]l[ée]travail|full[- ]remote)\b", loc_lower):
        return WorkplaceType.REMOTE
    if re.search(r"\b(on[- ]site|onsite|pr[ée]sentiel)\b", loc_lower):
        return WorkplaceType.ON_SITE
    if re.search(r"\b(hybrid|hybride)\b", loc_lower):
        return WorkplaceType.HYBRID

    clean_desc_lower = _strip_html(description).lower()
    if re.search(
        r"\b(100%\s*remote|full[- ]remote|fully remote|t[ée]l[ée]travail total)\b",
        clean_desc_lower,
    ):
        return WorkplaceType.REMOTE
    if re.search(
        r"\b(100%\s*on[- ]site|fully on[- ]site|pr[ée]sentiel uniquement)\b",
        clean_desc_lower,
    ):
        return WorkplaceType.ON_SITE

    return WorkplaceType.HYBRID


def extract_duration_months(title: str, description: str = "") -> int | None:
    """Extracts internship or fixed-term contract duration in months (1-36).

    Supports single durations ('6 mois', '6 months') and ranges ('4 à 6 mois',
    '4-6 months'), returning the upper bound for ranges.

    Args:
        title: Job offer title.
        description: Raw job description text or HTML.

    Returns:
        Duration in months between 1 and 36, or None if not found.
    """
    combined_text = f"{title} {_strip_html(description)}".lower()

    # Match ranges first (e.g., "4 à 6 mois", "4-6 months", "4 to 6 months")
    range_match = re.search(
        r"\b(\d{1,2})\s*(?:[-–à]|to)\s*(\d{1,2})\s*(?:mois|months?)\b",
        combined_text,
    )
    if range_match:
        upper_months = int(range_match.group(2))
        if 1 <= upper_months <= 36:
            return upper_months

    # Match explicit single durations (e.g., "6 mois", "6 months", "6-month")
    single_match = re.search(r"\b(\d{1,2})[- ]?(?:mois|months?)\b", combined_text)
    if single_match:
        months = int(single_match.group(1))
        if 1 <= months <= 36:
            return months

    return None


def compute_dedup_hash(company_slug: str, title: str, location: str) -> str:
    """Computes a deterministic SHA-256 hash for job deduplication.

    Sanitizes special characters from title and location to prevent cosmetic
    edits from creating duplicate database records.
    (ex: "Software Engineer" vs "Software-Engineer")
    Args:
        company_slug: Normalized company unique identifier slug.
        title: Job offer title.
        location: Job posting location string.

    Returns:
        A 64-character hexadecimal SHA-256 hash string.
    """
    normalized_title = re.sub(r"[^a-z0-9]", "", title.lower())
    normalized_location = re.sub(r"[^a-z0-9]", "", location.lower())

    seed = f"{company_slug.lower()}:{normalized_title}:{normalized_location}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


class JobPostingCanonical(BaseModel):
    """Canonical model representing a standardized job offer."""

    external_id: str = Field(description="Unique ID returned by the source ATS")
    company_slug: str = Field(description="Unique database slug for the company")
    company_name: str = Field(description="Human-readable company name")
    ats_provider: ATSProvider = Field(description="Originating ATS provider")

    title: str = Field(description="Original job offer title")
    location: str = Field(default="France", description="Physical or remote location")
    apply_url: str = Field(description="Direct URL to apply")
    description_raw: str = Field(description="Raw technical description body")

    contract_type: ContractType = Field(
        default=ContractType.UNKNOWN,
        description="Automatically classified French contract type",
    )
    workplace_type: WorkplaceType | None = Field(
        default=None,
        description="Workplace modality (ON_SITE, HYBRID, REMOTE)",
    )

    duration_months: int | None = Field(
        default=None,
        ge=1,
        le=36,
        description="Internship duration in months",
    )
    published_at: datetime | None = Field(
        default=None,
        description="Original publication timestamp in ATS",
    )
    dedup_hash: str = Field(
        default="",
        description="Deduplication hash (computed automatically if empty)",
    )

    @model_validator(mode="after")
    def populate_computed_fields(self) -> Self:
        """Sanitizes location and autocompletes contract, workplace, duration, and hash."""
        self.location = sanitize_location(self.location)

        if self.contract_type == ContractType.UNKNOWN:
            self.contract_type = classify_contract_type(
                title=self.title,
                description=self.description_raw,
            )

        if self.workplace_type is None:
            self.workplace_type = classify_workplace_type(
                location=self.location,
                description=self.description_raw,
            )

        if self.duration_months is None:
            self.duration_months = extract_duration_months(
                title=self.title,
                description=self.description_raw,
            )

        if not self.dedup_hash:
            self.dedup_hash = compute_dedup_hash(
                company_slug=self.company_slug,
                title=self.title,
                location=self.location,
            )

        return self
