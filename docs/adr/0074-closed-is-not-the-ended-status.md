# A closed Class Session is not the ended status

The existing ended status means the sitting's expiry is now. Process start rewrites a future expiry to now for every ended sitting. Closing must not use that status. A closed sitting keeps its expiry, and a restart does not end it. Ended remains the sitting whose expiry has passed.

## Considered Options

- **Reuse ended for 關閉課堂**: rejected. The next process start would expire the sitting and its keys.
