# The key check answers a Display Name

Status: accepted. Amends ADR 0077 (which rejected returning the Classroom Nickname).

club-booking-board projects who booked which room, and students open a shared read-only page to see whether their own booking landed. Integer ids alone mean nothing on that screen. An accepted key now also returns `display_name`, taken from the holder's user name: the Classroom Nickname for a nickname student, the Google name for a Google student, and the holder's name for a Personal API Key.

A Partner Service may store the Display Name beside the integer id and refresh it on each key check. It decides who someone is by the id alone, never by the name. The answer still carries no email, no Google subject, and no key id.

## Considered Options

- **A teacher-only class roster read**: rejected. A second call and credential rule, while a service needs the name exactly when the student acts.
- **Let the student type a display name at the Partner Service**: rejected. It is a second, unchecked name for the same student.
- **Ids only, as before**: rejected. The projected board and the shared page would show numbers no one recognizes.

## Consequences

- A Google student's Display Name is usually a real name, and it now reaches Partner Services and pages they show. Teachers who want only nicknames on screen ask students to use Nickname Redeem.
