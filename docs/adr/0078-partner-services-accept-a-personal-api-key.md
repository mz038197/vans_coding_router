# Partner Services accept a Personal API Key through the key check

Status: accepted. Amends ADR 0050. Amended by ADR 0087.

A Partner Service accepts a Personal API Key by asking the key check (ADR 0077). The key stays an opaque secret that only the router verifies, as ADR 0050 requires. Teacher or admin standing comes only from a Personal API Key. A Classroom API Key always answers as a student of its Class, even when its holder is a teacher or an admin.

## Considered Options

- **Keep ADR 0050's refusal of Personal API Keys on the MCP services**: rejected. Both MCP services accept them today, and a teacher demonstrating vans-mcp-server or pokemon-world-mcp in class would lose those tools.
- **Answer with every role the holder has, whatever the key**: rejected. An admin who redeems a Classroom API Key to test the student path would be treated as an admin and could not see the student view.
