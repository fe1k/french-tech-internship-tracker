"""Unit tests for canonical job posting models, sanitization, and classification."""

from tracker.models.canonical import (
    JobPostingCanonical,
    classify_contract_type,
    classify_workplace_type,
    compute_dedup_hash,
    extract_duration_months,
    sanitize_location,
)
from tracker.models.enums import ATSProvider, ContractType, WorkplaceType


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


def test_classify_contract_type_regression_algolia_senior_false_positive():
    """Regression test: English 'stage' in description must not classify Senior roles as STAGE."""
    title = "Principal Software Engineer, Frontend Experiences"
    description = (
        "<p>Help us scale the next stage of AI search and mentor junior engineers and interns.</p>"
    )
    assert classify_contract_type(title, description) == ContractType.UNKNOWN


def test_classify_contract_type_description_french_stage():
    """Tests that unambiguous French stage phrasing in description classifies as STAGE."""
    title = "Software Engineer - Search Platform"
    description = "<p>Offre de stage de fin d'études (PFE) avec convention de stage de 6 mois.</p>"
    assert classify_contract_type(title, description) == ContractType.STAGE


def test_classify_workplace_type():
    """Tests inference of REMOTE, ON_SITE, and HYBRID modalities."""
    assert classify_workplace_type("France, Remote; Spain, Remote") == WorkplaceType.REMOTE
    assert classify_workplace_type("Paris, France (On-site)") == WorkplaceType.ON_SITE
    assert classify_workplace_type("Paris, France") == WorkplaceType.HYBRID
    assert (
        classify_workplace_type("Paris, France", "<p>This is a 100% remote role in France.</p>")
        == WorkplaceType.REMOTE
    )


def test_extract_duration_months():
    """Tests extraction of single and ranged internship durations."""
    assert extract_duration_months("Stage Développeur Backend (6 mois)") == 6
    assert extract_duration_months("Software Intern", "Duration: 4 à 6 mois") == 6
    assert extract_duration_months("Research Intern", "4-6 months internship in Paris") == 6
    assert extract_duration_months("Software Engineer", "Permanent role") is None


def test_sanitize_location_truncation_and_france_priority():
    """Tests that overly long multi-city strings prioritize France and stay within 150 chars."""
    long_location = (
        "Amsterdam, The Netherlands; Berlin, Germany; Dublin, Ireland; London, United Kingdom; "
        "Madrid, Spain; Milan, Italy; Paris, France; Stockholm, Sweden; Zurich, Switzerland"
    )
    sanitized = sanitize_location(long_location, max_length=150)
    assert len(sanitized) <= 150
    assert "Paris, France" in sanitized


def test_compute_dedup_hash_determinism():
    """Tests that dedup hash is identical regardless of case or punctuation."""
    hash1 = compute_dedup_hash("datadog", "Software Engineer - Intern (Paris)", "Paris, France")
    hash2 = compute_dedup_hash("DATADOG", "Software Engineer Intern Paris", "paris france")
    assert hash1 == hash2


def test_canonical_model_auto_populates_fields():
    """Tests that Pydantic model autocompletes contract, workplace, duration, and hash."""
    job = JobPostingCanonical(
        external_id="gh-12345",
        company_slug="datadog",
        company_name="Datadog",
        ats_provider=ATSProvider.GREENHOUSE,
        title="Software Engineering Intern",
        location="France, Remote",
        apply_url="https://jobs.datadoghq.com/12345",
        description_raw="End of studies internship (6 months) in Paris.",
    )
    assert job.contract_type == ContractType.STAGE
    assert job.workplace_type == WorkplaceType.REMOTE
    assert job.duration_months == 6
    assert len(job.dedup_hash) == 64
