# Claude's thinking travels in client-held envelopes

The router keeps no conversation state, but Claude's thinking must come back unchanged on later turns. On Opus 5.5, Sonnet 5.5, and Fable 5.2, each thinking block's `signature` binds the block to the system prompt, the tool set, every message before it, and the thinking block before it. Copilot does not keep Anthropic signatures. It trims trailing whitespace from assistant text and sends Responses reasoning summaries back empty. So the router cannot rebuild a valid block from what Copilot returns.

The router therefore packs each assistant round's complete Anthropic content blocks (thinking with its signature, text, and tool use) into one envelope. It hands the envelope to a field that Copilot stores and echoes verbatim:

- **Responses**: the `encrypted_content` of a reasoning item whose id starts with `rs_`, placed first in that round's output. Copilot drops reasoning items that have no `encrypted_content`.
- **Chat**: `reasoning_opaque` on the reply. Copilot sends it back as `cot_id` on that assistant message, and it keeps one value per message, so one envelope holds the whole round.

Copilot displays the summary from the reasoning summary events, or from `reasoning_content` on chat, never from the envelope. On the next request, the router decodes each envelope and rebuilds that assistant round byte for byte from it. It ignores Copilot's copy of the text and the plain-text reasoning fields Copilot echoes.

Anthropic accepts a history with thinking removed from the front of the chain, from the end of the chain, or entirely. It does not accept thinking removed from the middle. Copilot does not always send old envelopes back:

- on chat, it drops thinking from earlier user turns;
- on both paths, it drops thinking produced by a different model;
- a conversation that started before this provider existed has no envelopes for those rounds.

So the router walks assistant rounds from the newest back. It keeps thinking for the trailing run of rounds whose envelope decodes and names the same model. At the first round without one, that round and every earlier round go without thinking blocks. Those rounds keep their text and tool calls. A malformed or foreign envelope counts as missing. It never fails the request.

Some breaks the router cannot see, for example Copilot rewriting an earlier turn, the tool list, or the system prompt. For those, every request sends `thinking.block_binding.prefix_mismatch_behavior: "drop_block"` under the `thinking-binding-controls-2026-08-01` beta header. Without it, an account created on or after 2026-08-31 gets a 400 for an invalid block. That block also stays in the history, so every later turn fails too. With it, Anthropic drops that block and all later ones, answers anyway, and lists the drops in `input_transformations`. The router writes each drop and its reason to its log, not to the database.

The envelope is an encoding, not encryption. Anyone holding the conversation can read the summarized thinking inside it, as they can read the summary on screen. Anthropic's signature still rejects any change to a block, and the router decodes only known content block types from it.

## Considered Options

- **A router table keyed by tool-call id or by a hash of the history**: rejected. It needs a schema change, a migration, the Postgres suite, and a retention policy. It must also match a history that Copilot has already altered, and it breaks the router's statelessness for one provider.
- **Drop all thinking on every turn**: rejected. It is valid and simple, but Claude would lose its reasoning between every tool call in an agent loop, the most common student task.
- **All-or-nothing replay: send no thinking when any round lacks an envelope**: rejected. Copilot's chat path never returns envelopes from earlier user turns, so this rule would drop all thinking on almost every chat turn.
- **Send every envelope that comes back, gaps included, and let `drop_block` sort it out**: rejected. Anthropic drops from the first mismatch onward, which loses the newest rounds, the ones that matter most. The trailing-run rule keeps them.
- **Carry only the thinking block in the envelope**: rejected. Copilot's trimmed text would still change the prefix, so the whole round must come from the envelope.

## Consequences

- On the Responses path, thinking survives across later user turns for the same model. On the chat path it survives only within the current task, because that is all Copilot replays. Copilot's `thinkingInHistory` override is an advanced user setting that students are not asked to set.
- Envelopes add to every request. Prompt caching makes the replayed prefix cheap.
- Some behavior still needs checking against real Copilot, and the `input_transformations` log will show what Copilot really does:
  - whether tool-call ids come back unchanged (the envelope holds the originals);
  - whether Copilot keeps history and envelopes across a VS Code reload.
- VansPod's Responses adapter keeps the envelope, because it nests the whole reasoning item in its own `vpr1.` signature. Its Chat adapter keeps only `reasoning_content` and loses the envelope, so Claude gets no thinking through that path. That is a VansPod change, tracked separately.
