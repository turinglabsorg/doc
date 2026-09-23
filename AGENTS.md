# Agent instructions — doc

- doc adds checks and hints to Claude Code through hooks; it must never loosen an
  existing guard or allow anything another rule forbids.
- Hooks fail open on Jev errors (the exact rules in code still apply), never
  break a session, and never print or log secret values or message contents.
- Keep Jev questions literal and narrow (see the TypeSafe jaggedness page); keep
  arithmetic, dates and exact matching in code.
- Before committing, run the offline tests and the live tests through hush, and
  exercise each changed hook through `bin/doc-hook` with a realistic payload.
- Code, docs and commit messages in English.
