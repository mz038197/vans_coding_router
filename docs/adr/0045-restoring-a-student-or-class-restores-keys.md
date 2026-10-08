# Enabling a student or restoring a Class accepts unexpired keys again

Disabling a student, or a Class that is not active or past its end, refuses that student's or that Class's Classroom API Keys. Enabling the student again, or the Class being active with its end still ahead, accepts an unexpired key again without a new redeem. A key ended because a newer one was issued stays ended. Today, setting the student active does not by itself re-enable the stored key; the student has to redeem. That changes for a signed key.

## Considered Options

- **Require a new redeem after the student or the Class is restored**: rejected. The refusal is the condition, not a burned key.
- **Restore the Class but still require a redeem for the student**: rejected. Both are conditions of the same kind.
