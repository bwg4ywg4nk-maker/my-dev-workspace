# Milestone 2, Phase 1 contract

This foundation is independent of Milestone 1. It captures local files and
validates caller-supplied evidence records; it does not extract or interpret them.
The JSON Schema in `schemas/normalized_evidence.schema.json` describes the wire
shape. `evidence.py` is the executable validator, including semantic constraints
that JSON Schema cannot express. No schema-validation dependency is required.

## Evidence and encoding

A document has exactly `schema_version: 1` and `evidence`, an array of records.
A record has exactly `schema_version`, `evidence_id`, `snapshot_id`, `locator`,
`text`, and `qualifications`. Text is a nonblank, caller-supplied source statement;
qualifications are ordered, verbatim strings. No numeric value, unit conversion,
derivation, confidence estimate or conflict-resolution field is introduced.
Frozen dataclasses use tuple qualifications to avoid mutable model contents.
Validation proves contract consistency, not factual correctness or source support.

Canonical encoding v1 is compact JSON with sorted object keys, UTF-8, no BOM or
trailing newline, and unescaped non-ASCII characters. Strings retain exact Unicode
code points and whitespace; no Unicode or newline normalization occurs. Array
order is significant except that document serialization sorts evidence by ID.
Only JSON null, booleans, strings, integers, arrays and string-keyed objects are
allowed. Floats (including NaN/infinity), tuples in JSON values, surrogate code
points and integers outside ±(2^53−1) are rejected. This is a project-specific
encoding, not a claim of RFC 8785 compliance. Duplicate JSON keys, unknown fields,
unsupported versions, duplicate evidence IDs and stale IDs are rejected on load.

Snapshot ID = `sha256:` followed by the lowercase SHA-256 hex of **raw bytes**.
Evidence ID = `ev1:` followed by SHA-256 hex of
`b"presentation-agent:evidence:v1\x00" + canonical_bytes(identity_payload)`.
The payload contains all record fields except `evidence_id`. Its schema version
is included. Paths, capture times and machine metadata are excluded. Identical
bytes at different paths share a snapshot; edits produce a new snapshot. Evidence
identity changes when its locator, text, qualifications or snapshot changes.
Records with the same ID are duplicates, not competing versions to reconcile.

## Locators (definitions only)

All coordinates are one-based positive integers, inclusive at both ends. Boolean
coordinates and reversed ranges are invalid. Bounds against actual source
content are intentionally not checked until extraction is implemented.

- Text: `kind: "text"`, `line_start`, `line_end`. Future readers use strict UTF-8,
  treating an initial UTF-8 BOM as an encoding marker. CRLF, LF and CR separate
  physical lines; a terminal separator does not introduce an extra empty line.
  Empty files have no lines. No columns or byte-offset interpretation is implied.
- CSV: `kind: "csv"`, `row_start`, `row_end`, `column_start`, `column_end`.
  Rows are logical CSV records, including the header (if present) as row 1;
  columns are positional fields, including empty fields. Multiline quoted fields
  occupy one logical row. Duplicate header names have no effect on coordinates.
  Future parsing uses strict UTF-8 with optional initial BOM, comma delimiter,
  double-quote quoting and doubled embedded quotes, with no whitespace trimming,
  dialect sniffing, escape character, or automatic header detection. Blank logical
  rows count; a terminal record separator does not add a row. Malformed records
  must fail explicitly in Phase 2. These rules do not introduce a parser here.

## Local capture and storage

`SourceStore(repository_root).capture("relative/path.txt")` accepts `.txt` and
`.csv` (case-insensitive extension), returning a frozen `SourceSnapshot` receipt
with repository-relative source path, declared media type, snapshot ID and byte
length. An extension declares the format; capture does not validate encoding or
parse contents. Empty and non-UTF-8 files can be captured as opaque bytes.
Receipts are returned to the caller, not persisted in a catalog in Phase 1.

Raw bytes live in `.runtime/snapshots/<64-hex-sha256>`. The entire `.runtime/`
tree is Git-ignored. It may contain sensitive local source content and is not a
shareable fixture. The API never stores absolute source paths or timestamps.

The repository root supplied by the caller is trusted and resolved once. Inputs
must be relative POSIX paths with no empty, dot or parent components, backslashes,
NULs, or `.runtime`, `.git`, `.venv` top-level components. Every descendant
directory and final file is opened relative to an open parent descriptor with
`O_NOFOLLOW`; symlinks are rejected even when they point inside the repository.
Only regular files are read; nonblocking open avoids hanging on FIFOs. The same
no-follow rules protect runtime directories and snapshot files. OS errors remain
explicit; the API does not conceal missing paths or permission failures.

Capture reads at most 8 MiB by default, in 64 KiB chunks. Callers may lower the
limit but cannot raise it. Size and modification metadata are checked before and
after reading to detect concurrent edits. A private temporary file is flushed,
fsynced, made read-only (0400), then published with an atomic hard link that cannot
overwrite an existing path. Only that operation's temporary file is cleaned up.
Runtime directories are created with mode 0700. Reuse and reads verify SHA-256;
corruption fails without repairing or overwriting the existing object. An
interrupted process can leave an ignored `.capture-*` temporary file.

This is application-level immutability, not an OS security boundary against the
owning user. A same-user hostile process can change permissions or mutate files;
hash verification detects content corruption on later reads. Metadata checks
cannot guarantee a coherent version under every concurrent source write. The
root/ancestor directories must remain trusted; no protection against privileged
directory relocation, filesystem failures, or hard-linked external source aliases
is claimed. The store is local POSIX (tested on macOS), not a Windows backend.

Evidence limits: 100,000 characters per string, 100 qualifications per record,
10,000 records, 32 levels of canonical nesting, 16 MiB encoded documents, and the
interoperable integer bound above. The store has no global disk quota, eviction,
catalog, garbage collection or automatic deletion of snapshots in this phase.

## Deferred work

Phase 2 must implement text/CSV extraction, source-bound locator verification,
and evidence support checks using immutable snapshots, with parsing-specific
resource limits and malformed-input tests. Quantitative normalization,
derivations, conflict handling and a Milestone 1 adapter remain later work that
requires its own approved scope. No Milestone 2 presentation build, LLM, network
retrieval, PDF/DOCX parser or new dependency is included.
