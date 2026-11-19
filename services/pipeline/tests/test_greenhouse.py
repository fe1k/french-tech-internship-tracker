"""Unit tests for Greenhouse ATS connector using HTTP mocks."""

import pytest
import respx
from httpx import AsyncClient, Response

from tracker.connectors.greenhouse import GreenhouseConnector
from tracker.models.enums import ATSProvider, ContractType


@pytest.mark.asyncio
async def test_greenhouse_connector_fetch_jobs_success():
    """Tests streaming and canonical transformation of a successful Greenhouse API response."""
    mock_payload = {
        "jobs": [
            {
                "id": 998877,
                "title": "Software Engineer Intern - Summer 2026",
                "updated_at": "2026-03-15T14:30:00-04:00",
                "location": {"name": "Paris, France"},
                "absolute_url": "https://boards.greenhouse.io/datadog/jobs/998877",
                "content": (
                    "&amp;lt;p&amp;gt;Join our team as a stagiaire in Paris.&amp;lt;/p&amp;gt;"
                ),
            }
        ],
        "meta": {"total": 1},
    }

    with respx.mock:
        respx.get("https://boards-api.greenhouse.io/v1/boards/datadog/jobs?content=true").mock(
            return_value=Response(200, json=mock_payload)
        )

        async with AsyncClient() as client:
            connector = GreenhouseConnector(client)
            assert connector.provider == ATSProvider.GREENHOUSE

            jobs = [
                job
                async for job in connector.fetch_jobs(
                    company_slug="datadog",
                    company_name="Datadog",
                    ats_identifier="datadog",
                )
            ]

            assert len(jobs) == 1
            job = jobs[0]

            assert job.external_id == "998877"
            assert job.company_slug == "datadog"
            assert job.contract_type == ContractType.STAGE
            assert job.location == "Paris, France"
            assert job.description_raw == "<p>Join our team as a stagiaire in Paris.</p>"
            assert job.published_at is not None
            assert len(job.dedup_hash) == 64


@pytest.mark.asyncio
async def test_greenhouse_connector_handles_404_gracefully():
    """Tests that a 404 response terminates the stream cleanly without throwing an exception."""
    with respx.mock:
        respx.get(
            "https://boards-api.greenhouse.io/v1/boards/invalid_company/jobs?content=true"
        ).mock(return_value=Response(404))

        async with AsyncClient() as client:
            connector = GreenhouseConnector(client)
            jobs = [
                job
                async for job in connector.fetch_jobs(
                    company_slug="invalid_company",
                    company_name="Invalid",
                    ats_identifier="invalid_company",
                )
            ]

            assert len(jobs) == 0
