"""Milestone 2 v1 evidence contract; independent of Milestone 1 and rendering."""
from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Tuple, Union

MAX_TEXT_CHARS = 100_000
MAX_RECORDS = 10_000
MAX_CANONICAL_BYTES = 16 * 1024 * 1024
SNAPSHOT_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")


def canonical_bytes(value):
    """Project encoding v1, not RFC 8785: UTF-8 JSON, no floats or coercion."""
    def check(item, depth=0):
        if depth > 32:
            raise ValueError("Canonical nesting limit exceeded")
        if item is None or type(item) is bool:
            return
        if type(item) is int:
            if abs(item) > 2**53 - 1:
                raise ValueError("Integer exceeds interoperable JSON range")
            return
        if type(item) is str:
            if len(item) > MAX_TEXT_CHARS:
                raise ValueError("Canonical string limit exceeded")
            item.encode("utf-8", errors="strict")
            return
        if type(item) is list:
            if len(item) > MAX_RECORDS:
                raise ValueError("Canonical collection limit exceeded")
            for child in item:
                check(child, depth + 1)
            return
        if type(item) is dict:
            if len(item) > MAX_RECORDS:
                raise ValueError("Canonical collection limit exceeded")
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError("JSON object keys must be strings")
                check(key, depth + 1)
                check(child, depth + 1)
            return
        raise ValueError("Unsupported canonical JSON type")

    check(value)
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False)
    encoded = bytearray()
    for fragment in encoder.iterencode(value):
        chunk = fragment.encode("utf-8")
        if len(encoded) + len(chunk) > MAX_CANONICAL_BYTES:
            raise ValueError("Canonical byte limit exceeded")
        encoded.extend(chunk)
    return bytes(encoded)


def snapshot_identity(data):
    if type(data) is not bytes:
        raise ValueError("Snapshot identity requires bytes")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _snapshot_id(value):
    if type(value) is not str or not SNAPSHOT_PATTERN.fullmatch(value):
        raise ValueError("Invalid snapshot identity")


def _positive(value):
    if type(value) is not int or not 1 <= value <= 2**53 - 1:
        raise ValueError("Locator coordinates must be positive integers")


def _text(value, empty=False):
    if type(value) is not str or (not empty and not value.strip()) or len(value) > MAX_TEXT_CHARS:
        raise ValueError("Invalid or oversized text")
    value.encode("utf-8", errors="strict")


@dataclass(frozen=True)
class TextLocator:
    line_start: int
    line_end: int

    def __post_init__(self):
        _positive(self.line_start)
        _positive(self.line_end)
        if self.line_end < self.line_start:
            raise ValueError("Reversed text range")

    def to_dict(self):
        return dict(kind="text", **asdict(self))


@dataclass(frozen=True)
class CSVLocator:
    row_start: int
    row_end: int
    column_start: int
    column_end: int

    def __post_init__(self):
        for value in asdict(self).values():
            _positive(value)
        if self.row_end < self.row_start or self.column_end < self.column_start:
            raise ValueError("Reversed CSV range")

    def to_dict(self):
        return dict(kind="csv", **asdict(self))


@dataclass(frozen=True)
class EvidenceRecord:
    snapshot_id: str
    locator: Union[TextLocator, CSVLocator]
    text: str
    qualifications: Tuple[str, ...] = ()

    def __post_init__(self):
        _snapshot_id(self.snapshot_id)
        if type(self.locator) not in (TextLocator, CSVLocator):
            raise ValueError("Unsupported locator")
        _text(self.text)
        if type(self.qualifications) is not tuple or len(self.qualifications) > 100:
            raise ValueError("Qualifications must be a tuple with at most 100 items")
        for qualification in self.qualifications:
            _text(qualification)

    def identity_payload(self):
        return dict(schema_version=1, snapshot_id=self.snapshot_id,
                    locator=self.locator.to_dict(), text=self.text,
                    qualifications=list(self.qualifications))

    @property
    def evidence_id(self):
        digest = hashlib.sha256(b"presentation-agent:evidence:v1\x00" +
                                canonical_bytes(self.identity_payload())).hexdigest()
        return "ev1:" + digest

    def to_dict(self):
        return dict(evidence_id=self.evidence_id, **self.identity_payload())

    @classmethod
    def from_dict(cls, value):
        fields = {"schema_version", "evidence_id", "snapshot_id", "locator", "text", "qualifications"}
        if type(value) is not dict or set(value) != fields:
            raise ValueError("Evidence fields must match schema exactly")
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("Unsupported schema version")
        locator = value["locator"]
        if type(locator) is not dict:
            raise ValueError("Invalid locator object")
        kinds = {"text": (TextLocator, {"line_start", "line_end"}),
                 "csv": (CSVLocator, {"row_start", "row_end", "column_start", "column_end"})}
        kind = locator.get("kind")
        if type(kind) is not str or kind not in kinds:
            raise ValueError("Unsupported locator kind")
        model, coordinates = kinds[kind]
        if set(locator) != coordinates | {"kind"}:
            raise ValueError("Invalid locator fields")
        if type(value["qualifications"]) is not list:
            raise ValueError("Qualifications must be a JSON array")
        record = cls(value["snapshot_id"], model(**{k: locator[k] for k in coordinates}),
                     value["text"], tuple(value["qualifications"]))
        if value["evidence_id"] != record.evidence_id:
            raise ValueError("Evidence identity mismatch")
        return record


def encode_records(records):
    """Serialize a unique, ID-sorted collection; no evidence extraction occurs."""
    if type(records) not in (tuple, list) or len(records) > MAX_RECORDS:
        raise ValueError("Invalid evidence collection")
    if any(type(record) is not EvidenceRecord for record in records):
        raise ValueError("Expected EvidenceRecord objects")
    items = [record.to_dict() for record in records]
    identities = [item["evidence_id"] for item in items]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate evidence identity")
    return canonical_bytes(dict(schema_version=1, evidence=sorted(items, key=lambda item: item["evidence_id"])))


def decode_records(data):
    if type(data) is not bytes or len(data) > MAX_CANONICAL_BYTES:
        raise ValueError("Invalid evidence input size or type")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except RecursionError as exc:
        raise ValueError("JSON nesting limit exceeded") from exc
    canonical_bytes(value)
    if type(value) is not dict or set(value) != {"schema_version", "evidence"}:
        raise ValueError("Invalid evidence document")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported schema version")
    if type(value["evidence"]) is not list:
        raise ValueError("Evidence must be an array")
    records = tuple(EvidenceRecord.from_dict(item) for item in value["evidence"])
    encode_records(records)
    return records
