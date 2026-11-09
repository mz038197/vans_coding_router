# A Classroom API Key can end before its expiry

A Classroom API Key keeps the expiry written at issuance. It also ends before that expiry in four cases. Issuing a third live key for that student in that Class Session ends the oldest. Disabling the student ends that student's keys. A Class that is not active, or whose end has passed, ends the keys of its sittings. A teacher may close the Class Session: its keys are refused, and opening it again accepts a key whose own expiry has not passed, without a new redeem. Closing does not change a key's expiry. Changing the sitting's `expires_at` does not by itself end a key already issued.

## Considered Options

- **Only the third key and disabling the student**: rejected. After the teacher closes the sitting, or the Class is no longer active, a service that only sees the key's expiry would keep accepting it.
- **Closing the sitting ends the keys permanently**: rejected. Opening the sitting restores a key that has not reached its own expiry, and the student does not redeem again.
