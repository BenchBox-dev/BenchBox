(cli-auth)=
# `auth` - Hosted Submission Credentials

```{tags} reference, cli, results
```

Manage the token used by `benchbox submit --service`.

Tokens are stored in the operating system keyring through the Python
`keyring` package. They are not written to BenchBox config files. For
automation, `BENCHBOX_SUBMIT_TOKEN` takes precedence over the keyring.

## Basic Syntax

```bash
benchbox auth COMMAND [OPTIONS]
```

## Commands

| Command | Description |
|---------|-------------|
| `login` | Store a hosted results token in the OS keyring |
| `status` | Show whether a token is available for a service URL |
| `refresh` | Replace the stored keyring token |
| `logout` | Remove the stored keyring token |

## Examples

```bash
# Prompt for a token and store it securely
benchbox auth login

# Store a token for a staging service
benchbox auth login --service https://staging.benchbox.dev/v1

# Check whether BenchBox can submit to the default service
benchbox auth status

# Replace a stored token
benchbox auth refresh

# Remove a stored token
benchbox auth logout
```

## Environment Tokens

For CI or ephemeral environments:

```bash
export BENCHBOX_SUBMIT_TOKEN=...
benchbox submit --last --service
```

Environment tokens are never saved by BenchBox. If an environment token is
active, `benchbox auth refresh` asks you to update or unset that environment
variable instead of hiding a replacement keyring token behind it.

## Related

- [submit](submit.md) - Upload or package benchmark results
- [results](results.md#results) - Show hosted submission history
