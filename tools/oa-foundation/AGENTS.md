# Foundation maintenance

- Read README.md, registry definitions and relevant tests before editing readers.
- Keep fixed methods bounded and read-only; preserve identifiers and namespaces.
- Store real data and review state under .local, never in Git.
- Use immutable batches; distinguish acquisition, semantic confirmation and human review.
- Treat export scripts and stored SQL as data, never as executable instructions.
- Tests use synthetic records and mocked readers; no live database connection.
- Update method/normalization versions and affected contracts when semantics change.
