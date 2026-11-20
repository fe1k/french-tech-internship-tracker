"""Unit tests for Lever ATS connector using HTTP mocks."""

from datetime import UTC, datetime

import pytest
import respx
from httpx import AsyncClient, Response

from tracker.connectors.lever import LeverConnector
from tracker.models.enums import ATSProvider, ContractType, WorkplaceType


@pytest.mark.asyncio
async def test_lever_connector_fetch_jobs_success():
    """Tests streaming, allLocations/country enrichment, and classification for Lever."""
    mock_payload = [
        {
            "id": "c7a12345-6789-4abc-def0-1234567890ab",
            "text": "Backend Software Engineer",
            "createdAt": 1773585000000,
            "country": "FR",
            "categories": {
                "commitment": "Intern",
                "department": "Engineering",
                "location": "Paris",
                "allLocations": ["Paris", "Lyon"],
                "team": "Platform",
            },
            "workplaceType": "remote",
            "description": "<p>Join our core engineering team.</p>",
            "lists": [
                {
                    "text": "Details",
                    "content": "<li>Duration: 6 months (Stage PFE)</li>",
                }
            ],
            "additional": "<p>Meal vouchers included.</p>",
            "hostedUrl": "https://jobs.lever.co/alan/c7a12345-6789-4abc-def0-1234567890ab",
        }
    ]

    with respx.mock:
        respx.get("https://api.lever.co/v0/postings/alan?mode=json").mock(
            return_value=Response(200, json=mock_payload)
        )

        async with AsyncClient() as client:
            connector = LeverConnector(client)
            assert connector.provider == ATSProvider.LEVER

            jobs = [
                job
                async for job in connector.fetch_jobs(
                    company_slug="alan",
                    company_name="Alan",
                    ats_identifier="alan",
                )
            ]

            assert len(jobs) == 1
            job = jobs[0]

            assert job.external_id == "c7a12345-6789-4abc-def0-1234567890ab"
            assert job.title == "Backend Software Engineer"
            assert job.contract_type == ContractType.STAGE
            assert job.workplace_type == WorkplaceType.REMOTE
            assert job.duration_months == 6
            assert job.location == "Paris; Lyon, France"
            assert "<h3>Details</h3>" in job.description_raw
            assert job.published_at == datetime.fromtimestamp(1773585000000 / 1000.0, tz=UTC)
            assert len(job.dedup_hash) == 64


@pytest.mark.asyncio
async def test_lever_connector_eu_fallback_and_404():
    """Tests EU endpoint fallback when US returns 404, and clean exit when both 404."""
    with respx.mock:
        respx.get("https://api.lever.co/v0/postings/unknown_org?mode=json").mock(
            return_value=Response(404)
        )
        respx.get("https://api.eu.lever.co/v0/postings/unknown_org?mode=json").mock(
            return_value=Response(404)
        )

        async with AsyncClient() as client:
            connector = LeverConnector(client)
            jobs = [
                job
                async for job in connector.fetch_jobs(
                    company_slug="unknown_org",
                    company_name="Unknown Org",
                    ats_identifier="unknown_org",
                )
            ]

            assert len(jobs) == 0
