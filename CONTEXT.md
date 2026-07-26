# Session Archive

Agent Dump discovers read-only conversation records from coding assistants and derives portable views without changing the source records.

## Language

**Provider**:
A supported coding assistant whose local records can be discovered and translated into Sessions.
_Avoid_: Agent, when referring to the data source

**Provider Discovery**:
The Provider-owned resolution of its read-only source roots and Session records.
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

**Query**:
A set of criteria that selects Sessions by Provider, Working Directory, message role, keyword, or result limit.
_Avoid_: Search, when referring to the full selection criteria

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
- The Scanner coordinates availability, listing, and locating across Providers,
  preserving Provider order while isolating failures.
- Working Directory is the only filesystem fact used by path Query and Collect
  deny rules.
- Provider Project may be shown when Working Directory is unavailable, but it
  is never treated as a filesystem path.
- Session Source is the read-only origin and the final display fallback. It is
  never inferred to be the Working Directory.
- Provider-owned related sources may participate in cache invalidation without
  becoming public Session fields.
