(cli-setup)=
# `setup` - Cloud Credentials

```{tags} reference, cli, cloud, credentials
```

Interactive setup and management for cloud platform credentials.

## Basic Syntax

```bash
benchbox setup --platform <name> [OPTIONS]
```

## Supported Platforms

| Platform | Required Credentials |
|----------|---------------------|
| `databricks` | `server_hostname`, `http_path`, `access_token` |
| `snowflake` | `account`, `user`, `password`, `warehouse` |
| `bigquery` | `project_id`, `credentials_file` |
| `redshift` | `host`, `port`, `database`, `user`, `password` |
| `athena` | `s3_staging_dir`, `region` |

## Options

- `--platform [databricks|snowflake|bigquery|redshift|athena]`: Platform to configure (required unless using `--list-platforms` or `--status` alone). Case-insensitive.
- `--validate-only`: Validate existing credentials without modifying them
- `--list-platforms`: List all platforms with their configuration status
- `--status`: Show credential status for all configured platforms
- `--remove`: Remove stored credentials for the specified platform
- `--diagnose`: Run connectivity diagnostics (Redshift only)

## Usage Examples

```bash
benchbox setup --platform databricks

benchbox setup --list-platforms

benchbox setup --status

benchbox setup --platform snowflake --validate-only

benchbox setup --platform redshift --diagnose

benchbox setup --platform databricks --remove
```

## Notes

- Credentials are stored securely via the `CredentialManager`. The `--status` command shows when credentials were last updated and validated.
- Platform dependencies are checked before setup. If required packages are missing, the command provides installation instructions.
- The `--diagnose` flag is currently only supported for Redshift, where it tests TCP connectivity and checks AWS API-level cluster accessibility.

## Related

- [run](run.md) - Run benchmarks on cloud platforms
- [configuration](configuration.md) - General configuration and environment variables
