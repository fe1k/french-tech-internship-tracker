"""Canonical job posting domain model and classification utilities."""

import hashlib
import re
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator

from tracker.models.enums import ATSProvider, ContractType, WorkplaceType


def classify_contract_type(title: str, description: str = "") -> ContractType:
    """Classifies contract type based on French labor regulations.

    Priority order for classification is as follows:
    1. STAGE (Internship/Training contract)
    2. CDD (Fixed-term contract)
    3. ALTERNANCE (Apprenticeship/Professionalization contracts)
    4. UNKNOWN (Fallback when no patterns match)

    Args:
        title: The job position title.
        description: The raw job description body text.

    Returns:
        The matched ContractType enum value.
    """
    text_to_scan = f"{title} {description}".lower()

    # 1. Evaluate STAGE
    stage_patterns = [
        r"\bstage\b",
        r"\bstagiaire\b",
        r"\binternship\b",
        r"\bintern\b",
        r"\bgratification\b",
        r"\bpfe\b",  # Projet de Fin d'Études
        r"end[- ]of[- ]studies",
    ]
    if any(re.search(pattern, text_to_scan) for pattern in stage_patterns):
        return ContractType.STAGE

    # 2. Evaluate CDD
    cdd_patterns = [
        r"\bcdd\b",
        r"fixed[- ]term",
        r"contrat à durée déterminée",
        r"contrat a duree determinee",
    ]
    if any(re.search(pattern, text_to_scan) for pattern in cdd_patterns):
        return ContractType.CDD

    # 3. Evaluate ALTERNANCE
    alternance_patterns = [
        r"\balternance\b",
        r"\bapprentissage\b",
        r"contrat de pro",
        r"professionnalisation",
        r"rythme d'alternance",
    ]
    if any(re.search(pattern, text_to_scan) for pattern in alternance_patterns):
        return ContractType.ALTERNANCE

    # 4. Default fallback
    return ContractType.UNKNOWN


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
    workplace_type: WorkplaceType = Field(
        default=WorkplaceType.HYBRID,
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
        """Autocompletes contract classification and deduplication hash if missing."""
        if self.contract_type == ContractType.UNKNOWN:
            self.contract_type = classify_contract_type(
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
