# Expired Classroom API Key serves no extension GETs

Ending a Class Session is a hard stop for every student router read, not only chat. An expired Classroom API Key fails `GET /extension/course-catalog` and keyed `GET /extension/chat-language-models` the same way it fails `/v1`. Disabled keys and suspended users keep failing those GETs. The unauthenticated models GET stays public for precheck and teacher candidates.

This amends ADR 0001: the last saved Course Catalog is no longer readable after the sitting ends.

## Considered Options

- **Keep catalog after end, block only `/v1`**: rejected — students would still pull Course Catalog and the keyed models document after the sitting stopped.
- **Treat expired like a missing key and fall back to the public Template**: rejected — a keyed GET with a dead key must fail, not silently become precheck.
