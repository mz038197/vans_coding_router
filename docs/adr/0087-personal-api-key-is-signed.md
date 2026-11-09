# A Personal API Key is signed too, and names only its holder

Status: accepted. Supersedes the part of ADR 0050 that keeps a Personal API Key unsigned. Amends ADRs 0077 and 0078.

The router signs a Personal API Key with the same private key, publishes the public key in the same JWKS, and refuses the key through the same Revocation List as a Classroom API Key. Its `kind` is `personal`. It names only its holder, the `user_id`, and its own `api_key_id`. It has no expiry. Admin standing and the Classes the holder may manage are not written on it, because they change when a teacher gets a new Class or a user becomes an admin. A Partner Service that needs them, such as road-test's management pages, asks the Key Check with the key and keeps the answer for 60 seconds as before. vans-mcp-server and pokemon-world-mcp need only the holder.

A holder has one live Personal API Key, and issuing a newer one ends the older one. The Revocation List therefore keeps at most one entry per holder: the lowest `api_key_id` still accepted, or none while the holder is disabled. Enabling the holder again sets the entry back to the current key.

Personal API Keys already issued are legacy keys. The Key Check answers them until a date the operator sets. Before that date, Portal asks each holder of a legacy Personal API Key to issue a new one, and hex-island's `ROUTER_KEY` is replaced.

## Considered Options

- **Keep the Personal API Key unsigned (ADR 0050)**: rejected. Every Partner Service would keep asking the router about every teacher call.
- **A hidden permanent Class for each teacher, with the teacher's key as its Classroom API Key**: rejected. The Class would show up in admin lists, rosters, seat limits, and usage reports, and every Class Session rule would need an exception for it. It still could not say whether the holder is a teacher or an admin.
- **Write admin standing and the Classes on the key**: rejected. A teacher would have to issue a new key, and replace it everywhere it is used, each time a Class is added.
- **An expiry, such as one year**: rejected. A teacher who forgets to renew would find hex-island or a demo broken. One list entry per holder keeps the list small without an expiry.
- **One list entry per replaced key**: rejected. The list would grow with every new key a teacher issues.
