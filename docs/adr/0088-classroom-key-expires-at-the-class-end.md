# A Classroom API Key expires at its Class's end; the sitting's expiry refuses it through the Revocation List

Status: accepted. Supersedes ADR 0052. Amends ADR 0053.

The expiry written on a Classroom API Key is its Class's end as of issuance. When the Class has no end, it is one year after issuance. The Class Session's own expiry is not written on the key. While a sitting has not started, or is paused (ADR 0089), the Revocation List carries an entry for it, and every Partner Service refuses its keys. A teacher who extends a sitting changes nothing on the keys, so students do not redeem again. A key past its own expiry still says「API 金鑰已過期，請至 Portal 重新取得邀請碼」.

The expiry on the key lets the router drop a sitting's entry from the list once every key that could name that sitting has passed its own expiry.

## Considered Options

- **The sitting's expiry at issuance, as ADR 0052 said**: rejected. A teacher who extends a sitting by thirty minutes would have the whole class redeem again. ADR 0052 chose it because a Partner Service could not learn the sitting's current expiry, but the Revocation List already tells it whether a sitting is paused.
- **No expiry on the key, only the list**: rejected. A sitting's entry could then never be dropped, and the list would only grow.
