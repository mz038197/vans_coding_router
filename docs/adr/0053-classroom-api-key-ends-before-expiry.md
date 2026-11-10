# A Classroom API Key can end before its expiry

A Classroom API Key expires at its Class Session's current end (ADR 0091). It also ends before that end in two cases. Disabling the student ends that student's keys. A Class that is not active, or whose end has passed, ends the keys of its sittings.

## Considered Options

- **Only the sitting's end**: rejected. A disabled student, or a Class that is no longer active, would keep a working key until the sitting ends.
