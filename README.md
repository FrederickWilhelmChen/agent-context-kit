# Agent Context Kit

Pick up a conversation from another coding agent. Search a phrase you remember, find the original message, and read the turns around it. Works with local Claude Code, Codex and DeepSeek Harness histories, including DeepSeek super agent sessions.

## Install from this repository

Requires macOS or Linux, Python 3.10+, and Python's SQLite built with FTS5 and the trigram tokenizer. From a clone or extracted source archive:

```sh
pipx install .
agent-context-skill codex
agent-context sync
```

Use `agent-context-skill claude` or `agent-context-skill deepseek` to install the same skill for those clients. Start a new chat and ask “Use shared-context to find our earlier discussion about parser retries.” The CLI must be on the agent's PATH. The installer refuses to replace a different existing skill. Remove the installed SKILL.md before reinstalling an updated copy.

## Search and follow the evidence

```sh
agent-context search 'parser retry'
agent-context list --project example --provider deepseek
agent-context read SOURCE_ID --start-line 12 --limit 5
agent-context memory --query 'style'
```

Search matches literal substrings, including Chinese and code identifiers. Results carry the source ID and original line number. Use `--raw` to inspect tool records at the source. Look at `next_offset` to page through list/search/memory results.

## Storage

The CLI builds a local SQLite text index in `~/.agent-context-kit/`. It links to original session files and existing client memory directories. Shared Markdown notes live in `memory/shared/`. A normal query refreshes changed sources. Compressed files are reindexed individually when they change. Plain JSONL supports append-only updates. Use `agent-context --no-sync status` to inspect the last snapshot.

Treat the index like the original transcripts. It contains message text, and passages you ask a hosted agent to read can enter that model's context. Deleted sources disappear from normal search after sync, but their indexed rows can remain on disk. Back up shared notes separately. To uninstall, remove the skill installed for each client, then run `pipx uninstall agent-context-kit`.
