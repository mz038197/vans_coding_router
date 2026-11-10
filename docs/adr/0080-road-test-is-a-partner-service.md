# road-test is a Partner Service

Status: accepted. Amended by ADR 0082.

road-test accepts a Classroom API Key from a student and a Personal API Key from a teacher, through its own key check client (ADR 0082). A student acts in the Class the key names. A teacher manages road-test for a Class that teacher owns. An admin manages every Class. road-test keys its records by the router's integer ids and does not open this router's database. Its group codes and its shared teacher password go away.

road-test's own rules for groups live in road-test's ADRs.

## Considered Options

- **A login handoff from Portal to road-test**: rejected. A student who used Nickname Redeem has no Portal login. That student's only identity is the Classroom API Key.
- **Keep the group codes and the teacher password**: rejected. A shared password does not say which teacher acted, and a group code does not say which student submitted.
