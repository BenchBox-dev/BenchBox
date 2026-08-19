# Hosted credential operations

This runbook covers database-scoped Turso credentials for BenchBox's todo tracker.
Keep bearer tokens out of the repository, command arguments, logs, tracker
evidence, and configuration files.

## Mint a bounded token

Choose the shortest practical lifetime.

```sh
# Developer or headless writer: 90 days.
export TODO_DB_AUTH_TOKEN="$(turso db tokens create benchbox-todo --expiration 90d)"

# Scheduled audit/export: server-enforced read-only, 180 days.
export TODO_DB_RO_AUTH_TOKEN="$(turso db tokens create benchbox-todo --read-only --expiration 180d)"
```

Inject the result with an OS keychain, password manager, process supervisor, or
CI secret store. Point `TODO_DB_CREDENTIAL_COMMAND` at that store so sessions
retrieve it without an interactive step; see Provision once below. Do not save it
in `.todo-db/config.json` or a wrapper-managed cache. Record the database, capability,
issue date, expiry date, owner, and replacement reminder in the external secret
inventory—never the token value in tracker evidence.

Do not use group-scoped tokens with this runbook. If an operator deliberately
uses one, the owner must document group-level invalidation and every database
that shares its blast radius.

## Provision once

Do this one time per machine and capability. Afterwards no shell, agent session,
or CI worker needs an interactive step until the token is rotated.

1. Mint the bounded token as shown above and pipe it straight into your secret
   store, never into a file or the shell history.

   ```sh
   security add-generic-password -U -a "$USER" -s benchbox-todo-rw \
     -w "$(turso db tokens create benchbox-todo --expiration 90d)"
   ```

   1Password, `pass`, `gopass`, and a CI secret store are equally valid; the
   store only has to print one token on standard output.

2. Point todo-db at the store. Put this in the shell profile or process
   supervisor that starts your sessions, so every later shell and agent
   inherits it:

   ```sh
   export TODO_DB_CREDENTIAL_COMMAND="security find-generic-password -w -s benchbox-todo-rw"
   ```

   For a read-only consumer, store a `--read-only` token under its own service
   name (e.g. `benchbox-todo-ro`) and point the variable at that entry instead.

3. Confirm it resolves without any injected credential:

   ```sh
   env -u TODO_DB_AUTH_TOKEN -u TODO_DB_RO_AUTH_TOKEN \
     _project/scripts/todo doctor --json
   ```

   The `database` check must report `"source": "TODO_DB_CREDENTIAL_COMMAND"`.

The command is never run through a shell, so it must be a plain program and its
arguments. Put any pipeline or conditional logic in a small script and name that
script instead. Arguments are passed through unchanged; todo-db appends
nothing. When a provider must serve both capabilities from one entry-point, have
that script read `TODO_DB_CREDENTIAL_CAPABILITY`, which todo-db sets to
`read-only` or `read-write` in the command's environment:

```sh
#!/bin/sh
# Exit 0 with no output means "absent", which is the only condition that lets a
# read-only request fall back to read-write. A missing entry makes `security`
# exit 44, and a non-zero exit is an error that stops resolution, so the absent
# case has to be handled deliberately.
case "$TODO_DB_CREDENTIAL_CAPABILITY" in
  read-only)
    security find-generic-password -w -s benchbox-todo-ro 2>/dev/null || exit 0
    ;;
  *)
    exec security find-generic-password -w -s benchbox-todo-rw
    ;;
esac
```

If your store holds one entry serving both capabilities, point the variable
straight at it and skip the script. `doctor` will then report
`capability: requested:read-write` even for a read-only operation, because the
capability records what todo-db asked for, not what the token can do.

## Validate

Run a read-only preflight before a batch:

```sh
TODO_DB_RO_AUTH_TOKEN=... _project/scripts/todo doctor --json
```

A mutation worker validates its read-write credential explicitly:

```sh
TODO_DB_AUTH_TOKEN=... _project/scripts/todo doctor --rw --json
```

Read-only mode is server-enforced only when the supplied token was created with
`--read-only`. Never place `TODO_DB_AUTH_TOKEN` in the scheduled audit job.

## Rotate: routine replacement

For a provider-backed credential this is the only recurring interactive step,
at most once per lifetime maximum for that capability: mint the replacement,
overwrite the store entry in place (`security add-generic-password -U` updates
rather than duplicates), start a fresh process, and re-run the validation check.
`TODO_DB_CREDENTIAL_COMMAND` still names the same entry, so no session,
wrapper, or CI job needs an update.

For directly injected credentials:

1. The named owner mints a bounded replacement before the current expiry.
2. Update one external consumer or secret store.
3. Run `doctor` and the consumer's normal read or mutation smoke check.
4. Update the remaining consumers.
5. Confirm the old token is no longer injected and let it expire naturally.

Do not run database-wide invalidation for routine replacement: it revokes other
healthy credentials in the same database scope.

## Expired or rejected credential

Stop database-dependent work. Mint a bounded replacement outside todo-db,
update the external injector, start a fresh process so it receives the new
environment, and run `doctor` again. A child process cannot repair its parent
shell's environment.

Do not retry a rejected read-only token with a read-write credential. That can
hide an incorrect permission or an accidental write path.

## Suspected compromise

1. Identify whether the token is database- or group-scoped.
2. For a database-scoped token, immediately run:

   ```sh
   turso db tokens invalidate benchbox-todo --yes
   ```

3. Assume every database-scoped token is invalid, including read-only tokens.
4. Mint new bounded read-write and read-only credentials as required.
5. Redistribute them through the external secret stores and restart consumers.
6. Run `doctor`, audit verification, and the relevant smoke checks.
7. Record the incident without recording any bearer value.

A group-scoped token requires `turso group tokens invalidate` and a separate
inventory-driven response. Database invalidation alone may not cover it.

## Scheduled audit ownership

The repository/workflow owner maintains `TODO_DB_PROD_RO_TOKEN`, its issue and
expiry dates, and a replacement reminder. The workflow environment must contain
`TODO_DB_RO_AUTH_TOKEN` and must not contain `TODO_DB_AUTH_TOKEN`. CI never
mints credentials and never receives Turso account credentials.
