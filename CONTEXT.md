# Session Archive

Agent Dump discovers read-only conversation records from coding assistants and derives portable views without changing the source records.

## Language

**Provider**:
A supported coding assistant whose local records can be discovered and translated into Sessions.
_Avoid_: Agent, when referring to the data source

**Provider Discovery**:
The Provider-owned operation that resolves its read-only source roots and returns
explicit availability plus a requested window of Session records in one pass.
_Avoid_: Availability probe, when referring to the complete lookup process

**Session**:
One Provider-owned recorded conversation, including its identity, time range, source, and transcript-derived facts.
_Avoid_: Thread, Chat

**Session URI**:
A Provider-qualified reference that identifies one Session independently of its storage layout.
_Avoid_: Session path

**Working Directory**:
The filesystem directory in which a Session's work was performed.
_Avoid_: Project, source directory

**Provider Project**:
A Provider-owned grouping of Sessions; it may be a storage label rather than a filesystem directory.
_Avoid_: Working Directory

**Session Source**:
The read-only file, directory, or database record from which a Session is derived.
_Avoid_: Working Directory

**Model**:
The Provider-reported model identifier associated with a Session when known.

**Message Count Fact**:
The number of messages known for a Session together with its Count Completeness.
_Avoid_: Total Messages, when any selected Session has an unknown count

**Count Completeness**:
A closed state describing whether a Message Count Fact is `exact` or `unknown`.
_Avoid_: Partial, until a Provider can produce a real partial-count state

**Lightweight Head**:
A Session metadata view projected from bounded Provider Discovery facts without reading the full transcript.
_Avoid_: Summary, transcript preview

**Query**:
A set of criteria that selects Sessions by Provider, Working Directory, message role, keyword, or result limit.
_Avoid_: Search, when referring to the full selection criteria

**Query Keyword**:
One case-insensitive literal phrase used by `-query` and `agents://`; whitespace is normalized before matching.
_Avoid_: Search Terms

**Search Terms**:
The distinct whitespace-delimited literals supplied to `--search`; every term must occur, but terms may occur in different Searchable Corpus fields.
_Avoid_: Query Keyword

**Searchable Corpus**:
A Session title plus the logical text exposed by its normalized transcript: message text, reasoning, and tool state.
_Avoid_: Serialized Provider Source

**Export**:
A portable representation derived from a Session in a requested format.
_Avoid_: Session Source

**Collect Report**:
A derived summary that combines selected Sessions over a time range.
_Avoid_: Export

## Fact boundaries

- A Provider maps its storage schema into stable Session facts. Shared workflows
  do not interpret Provider-private metadata keys.
- A Provider read entry point performs its own Provider Discovery; callers do
  not establish hidden state by probing availability first.
- `discover_sessions()` is the explicit Provider Discovery operation;
  `is_available()` and `get_sessions()` remain stable compatibility entry points.
- The Scanner coordinates availability, listing, and locating across Providers,
  preserving Provider order while isolating failures.
- Working Directory is the only filesystem fact used by path Query and Collect
  deny rules.
- Provider Project may be shown when Working Directory is unavailable, but it
  is never treated as a filesystem path.
- Session Source is the read-only origin and the final display fallback. It is
  never inferred to be the Working Directory.
- Query and Search match logical Searchable Corpus fields. JSON escaping,
  Provider-private metadata, and other serialized Source details are not user
  search semantics.
- Provider-owned related sources may participate in cache invalidation without
  becoming public Session fields.
- Full Session payloads are derived request data, not durable facts. Reuse reads
  retain only a bounded working set; bulk projections lease payloads only until
  their smaller Search or Collect output has been derived.
- List, Lightweight Head, and statistics project the same Message Count Fact;
  they do not interpret Provider metadata independently.
- List and Lightweight Head project the same Model fact; they do not interpret
  Provider metadata independently.
- An unknown Message Count Fact remains visible as unknown. Shared workflows do
  not turn the sum of known counts into an apparently complete total.
