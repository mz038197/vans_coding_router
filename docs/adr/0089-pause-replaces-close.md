# A Class Session pauses at its expiry; pausing early sets the expiry to now

Status: accepted. Supersedes ADR 0054. Amends ADRs 0053 and 0065.

A Class Session has no closed state. Once its expiry has passed, it is paused. Its Classroom API Keys are refused with 課堂已暫停, and a redeem is refused with 課堂已暫停，無法領取. Portal's 暫停 sets the expiry to now after the teacher confirms:「確定要暫停此課堂嗎？暫停後學生的金鑰會停止使用，結束時間會改成現在。之後設定新的結束時間，就能繼續上課，學生不用重新兌換。」 While paused, the same control reads 繼續 and opens the expiry editor. Saving an expiry still ahead resumes the sitting. A key whose own expiry has not passed (ADR 0088) is accepted again without a new redeem.

Refusal notices keep ADR 0065's order, with the paused sitting in place of the closed one: 學生已被停用, then 課程已結束或停用, then 課堂已暫停, then 已在其他電腦兌換. 課堂已關閉 and 課堂已結束，無法領取 are no longer used.

## Considered Options

- **A closed state that keeps the expiry, as ADR 0054 said**: rejected. Closing a sitting and letting it end were two ways to stop it that behaved differently and needed two notices. Teachers already stop a sitting by setting its expiry to now. ADR 0054 gave two reasons: the original expiry is lost, and students redeem again after a restart. Students no longer redeem again (ADR 0088). Losing the original expiry is accepted: resuming asks for a new one.
- **The expired notice for a paused sitting**: rejected. It tells the student to fetch a new invite code, but a redeem is refused while paused, and resuming brings the key back.
