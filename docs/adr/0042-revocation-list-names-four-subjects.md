# A Revocation List entry names one of four subjects

An entry names one Classroom API Key, one student, one Class Session, or one Class. The key names the student, the sitting, and the Class, plus its own identity, its expiry, and the router as issuer. It does not carry a nickname, an email, or a personal name. Opening a sitting removes the sitting's entry. Enabling a student, or a Class being active with its end still ahead, removes that entry. A key ended because a newer one was issued stays named until its own expiry; after that, expiry rejects it and the entry need not stay.

## Considered Options

- **Only key identities, expanded when a sitting or a student is refused**: rejected. Opening a sitting would mean rewriting every key on the list.
- **An allow-list of live keys**: rejected. The list would grow with every live key instead of with the refusals.
