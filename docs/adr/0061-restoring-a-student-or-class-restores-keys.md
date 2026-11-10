# Restoring a Class accepts its unexpired keys again; enabling a student does not

A Class that is not active, or past its end, refuses the Classroom API Keys of its sittings. That refusal is checked at each use, so once the Class is active with its end still ahead, an unexpired key is accepted again without a new redeem. Disabling a student turns that student's keys off. Enabling the student again does not turn them back on; the student redeems again for a new key.

## Considered Options

- **Require a new redeem after the Class is restored**: rejected. The refusal is the Class's condition, not a burned key.
