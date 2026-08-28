from enum import StrEnum


class EntityStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ClaimStatus(StrEnum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class SourceType(StrEnum):
    HUMAN = "HUMAN"
    FILE_UPLOAD = "FILE_UPLOAD"
    CONFLUENCE = "CONFLUENCE"
    SYSTEM = "SYSTEM"


class GapPriority(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class GapStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    SKIPPED = "SKIPPED"
