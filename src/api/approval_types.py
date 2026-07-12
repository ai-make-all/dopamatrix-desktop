from enum import Enum


class VariantStatus(str, Enum):
    PROCESSING = "PROCESSING"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DELETED = "DELETED"


REVIEW_TARGET_STATUSES = {
    VariantStatus.PENDING,
    VariantStatus.APPROVED,
    VariantStatus.REJECTED,
    VariantStatus.DELETED,
}
