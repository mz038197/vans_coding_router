# Shared verification lives in vans-auth

Signature checks, public-key fetch, Revocation List refresh, and the 600-second copy bound live in one Python package, `vans-auth`, in its own repository. vans-mcp-server and pokemon-world-mcp install it. The router does not. It signs keys, publishes the public keys, and builds the Revocation List itself. The router keeps the example responses for the public keys and the Revocation List. A format change updates those examples and bumps the package version together.

## Considered Options

- **Copy the checks into each MCP service**: rejected. The two copies of the validity rules are the problem this removes.
- **Ship the package inside the router repository**: rejected. An MCP release would then follow a router release.
- **Have the router install the package too**: rejected. The router is the source of the keys and the list, not a reader of the list.
