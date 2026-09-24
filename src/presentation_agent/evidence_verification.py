"""Offline reproduction checks; source credibility and interpretation are not assessed."""
from dataclasses import dataclass
from enum import Enum
from typing import Union

from .evidence import CSVLocator, EvidenceRecord, TextLocator
from .source_capture import SourceStore
from .source_extraction import (
    CSVExtraction, CSVLimits, TextExtraction, TextLimits, extract_csv, extract_text,
)


class TextReproduction(Enum):
    EXACT_MATCH = "exact_match"
    MISMATCH = "mismatch"
    NOT_ASSESSED = "not_assessed"


class StructuredCells(Enum):
    AVAILABLE = "available"
    NOT_APPLICABLE = "not_applicable"


class QualificationVerification(Enum):
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class EvidenceVerification:
    record: EvidenceRecord
    extraction: Union[TextExtraction, CSVExtraction]
    text_reproduction: TextReproduction
    structured_cells: StructuredCells
    qualification_verification: QualificationVerification


def verify_evidence(store: SourceStore, record: EvidenceRecord, *,
                    limits: Union[TextLimits, CSVLimits, None] = None) -> EvidenceVerification:
    """Dispatch by locator, retaining the original record and extraction object.

    TEXT uses Python string equality only. CSV exposes extracted cells without
    assessing record.text. Qualifications are always unverified, even if empty.
    Limits must match the selected parser's concrete type, or be None to use
    that parser's defaults. Source/extraction exceptions propagate.
    """
    if type(record) is not EvidenceRecord:
        raise ValueError("Expected EvidenceRecord")
    if type(record.locator) is TextLocator:
        if limits is not None and type(limits) is not TextLimits:
            raise ValueError("Expected TextLimits or None for TextLocator")
        extraction = (extract_text(store, record.snapshot_id, record.locator)
                      if limits is None else
                      extract_text(store, record.snapshot_id, record.locator, limits))
        reproduction = (TextReproduction.EXACT_MATCH if record.text == extraction.text
                        else TextReproduction.MISMATCH)
        cells = StructuredCells.NOT_APPLICABLE
    elif type(record.locator) is CSVLocator:
        if limits is not None and type(limits) is not CSVLimits:
            raise ValueError("Expected CSVLimits or None for CSVLocator")
        extraction = (extract_csv(store, record.snapshot_id, record.locator)
                      if limits is None else
                      extract_csv(store, record.snapshot_id, record.locator, limits))
        reproduction = TextReproduction.NOT_ASSESSED
        cells = StructuredCells.AVAILABLE
    else:
        raise ValueError("Unsupported locator")
    return EvidenceVerification(record, extraction, reproduction, cells,
                                QualificationVerification.UNVERIFIED)
