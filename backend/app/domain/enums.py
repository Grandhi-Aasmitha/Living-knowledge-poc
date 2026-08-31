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


class ConflictStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ConflictResolutionType(StrEnum):
    KEEP_CLAIM = "KEEP_CLAIM"
    BOTH_VALID = "BOTH_VALID"
    CORRECTED = "CORRECTED"
    AUTO_CLEARED = "AUTO_CLEARED"
