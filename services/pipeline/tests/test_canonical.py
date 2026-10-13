"""Unit tests for canonical job posting models and contract classification."""

from tracker.models.canonical import (
    JobPostingCanonical,
    classify_contract_type,
    compute_dedup_hash,
)
from tracker.models.enums import (
    ATSProvider,
    ContractType,
    WorkplaceType 
)

def test_classify_contract_type_stage_priority():
    """Tests that STAGE takes precedence over ALTERNANCE when both keywords exist."""
    title = "Software Engineer - Stage / Alternance 2026"
    description = "Nous recherchons un stagiaire ou un alternant pour 6 mois."
    assert classify_contract_type(title, description) == ContractType.STAGE


def test_classify_contract_type_cdd_priority():
    """Tests that CDD takes precedence over ALTERNANCE when STAGE is absent."""
    title = "Backend Developer (CDD / Contrat pro)"
    description = "Contrat a duree determinee de 12 mois."
    assert classify_contract_type(title, description) == ContractType.CDD


def test_classify_contract_type_alternance():
    """Tests classification of pure ALTERNANCE positions."""
    title = "Data Engineer in Alternance / Apprentissage"
    assert classify_contract_type(title) == ContractType.ALTERNANCE


def test_classify_contract_type_unknown():
    """Tests fallback to UNKNOWN for roles without recognized contract patterns."""
    title = "Senior Software Architect"
    assert classify_contract_type(title) == ContractType.UNKNOWN


def test_compute_dedup_hash_determinism():
    """Tests that dedup hash is identical regardless of case or punctuation."""
    hash1 = compute_dedup_hash("datadog", "Software Engineer - Intern (Paris)", "Paris, France")
    hash2 = compute_dedup_hash("DATADOG", "Software Engineer Intern Paris", "paris france")
    assert hash1 == hash2


def test_canonical_model_auto_populates_fields():
    """Tests that Pydantic model autocompletes contract classification and SHA-256 hash."""
    job = JobPostingCanonical(
        external_id="gh-12345",
        company_slug="datadog",
        company_name="Datadog",
        ats_provider=ATSProvider.GREENHOUSE,
        title="Software Engineering Intern",
        apply_url="https://jobs.datadoghq.com/12345",
        description_raw="End of studies internship in Paris.",
    )
    assert job.contract_type == ContractType.STAGE
    assert len(job.dedup_hash) == 64
    assert job.workplace_type == WorkplaceType.HYBRID