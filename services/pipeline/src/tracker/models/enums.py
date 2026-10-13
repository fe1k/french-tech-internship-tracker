"""Domain enumeration models synchronized with PostgreSQL ENUMs."""

from enum import StrEnum


class ATSProvider(StrEnum):
    """Supported Applicant Tracking System (ATS) providers."""

    GREENHOUSE = "GREENHOUSE"
    LEVER = "LEVER"
    SMARTRECRUITERS = "SMARTRECRUITERS"
    ASHBY = "ASHBY"
    AMAZON = "AMAZON"
    WTTJ = "WTTJ"
    MANUAL = "MANUAL"


class ContractType(StrEnum):
    """French legal labor framework contract types."""

    STAGE = "STAGE"
    CDD = "CDD"
    ALTERNANCE = "ALTERNANCE"
    UNKNOWN = "UNKNOWN"


class WorkplaceType(StrEnum):
    """Workplace modality definitions."""

    ON_SITE = "ON_SITE"
    HYBRID = "HYBRID"
    REMOTE = "REMOTE"


class OfferStatus(StrEnum):
    """Job offer lifecycle status in the platform."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    UNCONFIRMED = "UNCONFIRMED"
