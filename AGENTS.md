# Agent instructions — doc

- doc adds checks and hints to every coding agent that runs its hooks (Claude Code,
  Codex, Grok, Hermes); it must never loosen an existing guard or allow anything
  another rule forbids.
- The agents differ in payload keys and in the answers they read: a check reads its
  input through `doc.event.read` and answers through `doc.event` helpers, never by
  agent-specific keys or shapes of its own.
- `DOC_RULES` (doc/rules.py) is the owner's explicit setting: it may turn built-in Jev
  rules off and add the owner's own, never touch the exact rules in code. Without it
  every check behaves as before; a broken file or rule is left out, never fatal.
- Hooks fail open on Jev errors (the exact rules in code still apply), never
  break a session, and never print or log secret values or message contents.
- Keep Jev questions literal and narrow (see the TypeSafe jaggedness page); keep
  arithmetic, dates and exact matching in code.
- Before committing, run the offline tests and the live tests through hush, and
  exercise each changed hook through `bin/doc-hook` with a realistic payload.
- Code, docs and commit messages in English.
