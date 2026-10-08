# A refusal before expiry has its own notice

A Classroom API Key that is past its own expiry still says「API 金鑰已過期，請至 Portal 重新取得邀請碼」. A refusal before that expiry tells the student which cause it was. A key ended by a newer one says 已在其他電腦兌換. A closed Class Session says 課堂已關閉. A disabled student says 學生已被停用. A Class that is not active or past its end says 課程已結束或停用. The router and both MCP services use those same notices, including Course Catalog and the keyed models read. When more than one cause applies, the notice is the first that still blocks a new redeem: disabled student, then the Class, then the closed sitting, then the key ended by a newer one. A redeem refused for one of those causes uses that same notice followed by 「，無法領取」. A redeem refused because the sitting's expiry has passed says 課堂已結束，無法領取. A full sitting still says 此課堂座位已滿，無法領取. It is refused at its expiry with no extra time. The teacher can see that a newer redeem ended an older key, without seeing the key.

The Revocation List does not grow a reason field. The entry kind is the notice. It still carries no nickname, email, or personal name. Only the caller who presented the key is told that key's notice. The list itself stays behind the Revocation List Credential.

## Considered Options

- **One notice, 無效的 API 金鑰, for every cause**: rejected. The student should be able to tell a closed sitting from a disabled student from a key ended by a newer one.
- **Put the notice text or the student's name on the Revocation List**: rejected. The entry kind already selects the notice, and the list is not a place for personal names.
- **Prefer 已在其他電腦兌換 whenever the key was ended by a newer one**: rejected. A disabled student, an ended Class, or a closed sitting still blocks a new redeem, and that notice would send the student to redeem anyway.
- **Keep the English redeem errors `invalid invite` and `expired invite`**: rejected. A closed sitting and a sitting whose expiry has passed are different, and both should say so in the same language as the other notices.
- **Allow the key for a short time after its expiry**: rejected. The same expiry is the cutoff on the router and on both MCP services.
