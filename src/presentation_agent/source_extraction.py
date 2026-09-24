"""Deterministic snapshot extraction, independent of evidence support checks.

All character limits count decoded Unicode code points (Python str length),
not UTF-8 bytes or graphemes. Limits apply to unselected content as well.
"""
from dataclasses import dataclass, fields
from typing import Tuple

from .evidence import CSVLocator, TextLocator
from .source_capture import SourceStore


@dataclass(frozen=True)
class TextLimits:
    max_lines: int = 100_000
    max_line_codepoints: int = 100_000

    def __post_init__(self):
        _validate_limits(self)


@dataclass(frozen=True)
class CSVLimits:
    max_rows: int = 100_000
    max_fields_per_row: int = 1_000
    max_total_fields: int = 1_000_000
    max_field_codepoints: int = 100_000
    max_selected_cells: int = 10_000
    max_selected_codepoints: int = 1_000_000

    def __post_init__(self):
        _validate_limits(self)


def _validate_limits(limits):
    # Dataclass defaults are the fixed ceilings; bool is deliberately rejected.
    for field in fields(limits):
        value = getattr(limits, field.name)
        if type(value) is not int or not 1 <= value <= field.default:
            raise ValueError(f"{field.name} must be an integer from 1 to {field.default}")


@dataclass(frozen=True)
class TextExtraction:
    snapshot_id: str
    locator: TextLocator
    text: str


@dataclass(frozen=True)
class CSVExtraction:
    snapshot_id: str
    locator: CSVLocator
    rows: Tuple[Tuple[str, ...], ...]


def _decode(data):
    # utf-8-sig removes exactly one initial BOM, preserving subsequent U+FEFF.
    return data.decode("utf-8-sig", errors="strict")


def _separator_size(text, index):
    if text[index] == "\r":
        return 2 if text[index:index + 2] == "\r\n" else 1
    return 1 if text[index] == "\n" else 0


def extract_text(store: SourceStore, snapshot_id: str, locator: TextLocator,
                 limits: TextLimits = TextLimits()) -> TextExtraction:
    """Select one-based inclusive physical lines, preserving internal separators."""
    if type(locator) is not TextLocator or type(limits) is not TextLimits:
        raise ValueError("Expected TextLocator and TextLimits")
    text = _decode(store.read(snapshot_id))
    index = 0
    count = 0
    selected_start = selected_end = None
    while index < len(text):
        count += 1
        if count > limits.max_lines:
            raise ValueError("Physical text line limit exceeded")
        start = index
        while index < len(text) and text[index] not in "\r\n":
            index += 1
            if index - start > limits.max_line_codepoints:
                raise ValueError("Text line code point limit exceeded")
        if count == locator.line_start:
            selected_start = start
        if count == locator.line_end:
            selected_end = index
        if index < len(text):
            index += _separator_size(text, index)
    if selected_start is None or selected_end is None:
        raise ValueError("Text locator exceeds physical line bounds")
    return TextExtraction(snapshot_id, locator, text[selected_start:selected_end])


def _csv_rows(text, limits):
    """Explicit START/BARE/QUOTED/CLOSED state machine; blank rows have no fields.

    Counters are enforced before appending fields/characters or yielding rows.
    CRLF is one record separator outside quotes and two code points inside them.
    Only one bounded row is retained at a time.
    """
    state = "START"
    row = []
    field = []
    row_count = total_fields = 0
    index = 0

    def append_character(character):
        if len(field) >= limits.max_field_codepoints:
            raise ValueError("CSV field code point limit exceeded")
        field.append(character)

    def finish_field():
        nonlocal total_fields
        if len(row) >= limits.max_fields_per_row:
            raise ValueError("CSV fields per row limit exceeded")
        if total_fields >= limits.max_total_fields:
            raise ValueError("CSV total fields limit exceeded")
        total_fields += 1
        row.append("".join(field))
        field.clear()

    while index < len(text):
        if row_count >= limits.max_rows:
            raise ValueError("CSV logical row limit exceeded")
        character = text[index]
        if state == "QUOTED":
            if character == '"':
                state = "CLOSED"
            else:
                append_character(character)
            index += 1
            continue
        if state == "CLOSED" and character == '"':
            append_character('"')
            state = "QUOTED"
        elif character == ',':
            finish_field()
            state = "START"
        elif character in "\r\n":
            if state != "START" or row:
                finish_field()
            row_count += 1
            yield tuple(row)
            row.clear()
            state = "START"
            index += _separator_size(text, index)
            continue
        elif state == "CLOSED":
            raise ValueError("Invalid character after closing CSV quote")
        elif character == '"':
            if state != "START":
                raise ValueError("CSV quote may open only at field start")
            state = "QUOTED"
        else:
            append_character(character)
            state = "BARE"
        index += 1
    if state == "QUOTED":
        raise ValueError("Unterminated quoted CSV field")
    if state != "START" or row:
        finish_field()
        yield tuple(row)


def extract_csv(store: SourceStore, snapshot_id: str, locator: CSVLocator,
                limits: CSVLimits = CSVLimits()) -> CSVExtraction:
    """Select an exact rectangle after validating the entire snapshot.

    Ragged rows are valid, but missing selected columns fail without padding.
    A blank row has zero fields and cannot participate in a nonempty rectangle.
    """
    if type(locator) is not CSVLocator or type(limits) is not CSVLimits:
        raise ValueError("Expected CSVLocator and CSVLimits")
    cells = ((locator.row_end - locator.row_start + 1) *
             (locator.column_end - locator.column_start + 1))
    if cells > limits.max_selected_cells:
        raise ValueError("Selected CSV cell limit exceeded")
    text = _decode(store.read(snapshot_id))
    selected = []
    selected_codepoints = row_count = 0
    missing_columns = False
    for row_count, row in enumerate(_csv_rows(text, limits), 1):
        if locator.row_start <= row_count <= locator.row_end:
            if len(row) < locator.column_end:
                missing_columns = True
                continue
            values = row[locator.column_start - 1:locator.column_end]
            selected_codepoints += sum(map(len, values))
            if selected_codepoints > limits.max_selected_codepoints:
                raise ValueError("Selected CSV code point limit exceeded")
            selected.append(values)
    if row_count < locator.row_end or missing_columns:
        raise ValueError("CSV locator exceeds row or column bounds")
    return CSVExtraction(snapshot_id, locator, tuple(selected))
