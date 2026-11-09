# Closing a Class Session leaves its expiry in place

Portal's 關閉課堂 closes a Class Session without changing `expires_at`, and the screen keeps showing that expiry. While the sitting is closed, its Classroom API Keys are refused and a new redeem is refused. 重新開啟 clears the close. It does not ask for a new expiry, and a key whose own expiry has not passed is accepted again without a new redeem. When `expires_at` passes, the sitting has ended. That is not a close. Holding it again means a new expiry, and students redeem again for a key that carries it.

Today the same control sets `expires_at` to now and calls itself 結束課堂. Reopening asks for a future expiry. That control is replaced by the close above. Editing the expiry stays a separate action.

## Considered Options

- **Keep ending the sitting by setting `expires_at` to now**: rejected. Reopening would have to invent a new lifetime, and the original expiry would be gone, so a pause would look like the sitting had ended.
- **A second control beside that end button**: rejected. Teachers would have two ways to stop a sitting that is still inside its expiry.
