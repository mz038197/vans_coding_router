# A refusal before expiry has its own notice

A Classroom API Key that is past its own expiry still says「API 金鑰已過期，請至 Portal 重新取得邀請碼」. A refusal before that expiry tells the student which cause it was. A key ended by a newer one says 已在其他電腦兌換. A closed Class Session says 課堂已關閉. A disabled student says 學生已被停用. A Class that is not active or past its end says 課程已結束或停用. The router and both MCP services use those same notices, including Course Catalog and the keyed models read.

The Revocation List does not grow a reason field. The entry kind is the notice. It still carries no nickname, email, or personal name. Only the caller who presented the key is told that key's notice. The list itself stays behind the Revocation List Credential.

## Considered Options

- **One notice, 無效的 API 金鑰, for every cause**: rejected. The student should be able to tell a closed sitting from a disabled student from a key ended by a newer one.
- **Put the notice text or the student's name on the Revocation List**: rejected. The entry kind already selects the notice, and the list is not a place for personal names.
