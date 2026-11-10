# The key check names a key's sitting, Class, and student by the router's integer ids

When the key check accepts a Classroom API Key, the Class Session it names is `class_sessions.id`, the Class is `classes.id`, and the student is `users.id`. The Partner Services key their own records by those integers and do not open `neondb` to interpret them.

## Considered Options

- **New public ids for the sitting, the class, and the student**: rejected. The router already has these integers, and a second set of ids would be another name for the same rows.
