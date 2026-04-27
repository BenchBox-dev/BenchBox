"""BigQuery credentials setup and validation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import os
from pathlib import Path
from typing import Optional, Union

from rich.console import Console
from rich.prompt import Confirm

from benchbox.platforms.credentials.helpers import prompt_with_default
from benchbox.security.credentials import CredentialManager, CredentialStatus
from benchbox.utils.printing import QuietConsoleProxy


def _print_bigquery_auto_config(console, auto_config: dict) -> None:
    console.print(f"\n✅ Found credentials file: [cyan]{auto_config.get('credentials_path')}[/cyan]")
    console.print(f"✅ Found project: [cyan]{auto_config.get('project_id')}[/cyan]")
    console.print(f"✅ Found dataset: [cyan]{auto_config.get('dataset_id')}[/cyan]")
    console.print(f"✅ Found location: [cyan]{auto_config.get('location')}[/cyan]")
    if auto_config.get("storage_bucket"):
        console.print(f"✅ Found Cloud Storage bucket: [cyan]{auto_config['storage_bucket']}[/cyan]")


def _validate_service_account_file(console, credentials_path: str) -> bool:
    """Validate that credentials_path exists and is a service-account JSON; print red error on failure."""
    credentials_path_obj = Path(credentials_path)
    if not credentials_path_obj.exists():
        console.print(f"[red]❌ File not found: {credentials_path}[/red]")
        return False
    if not credentials_path_obj.is_file():
        console.print(f"[red]❌ Not a file: {credentials_path}[/red]")
        return False
    try:
        with open(credentials_path, encoding="utf-8") as f:
            json_content = json.load(f)
            if "type" not in json_content or json_content.get("type") != "service_account":
                console.print("[red]❌ File does not appear to be a valid service account JSON key[/red]")
                console.print("[dim]Expected: 'type': 'service_account'[/dim]")
                return False
    except json.JSONDecodeError as e:
        console.print(f"[red]❌ Invalid JSON file: {e}[/red]")
        return False
    except Exception as e:
        console.print(f"[red]❌ Error reading file: {e}[/red]")
        return False
    console.print("[green]✓[/green] Validated service account JSON file")
    return True


def _prompt_bigquery_full(console, existing_creds: Optional[dict]) -> Optional[dict]:
    """Full interactive prompt path; returns config dict or None on required-field failure."""
    existing = existing_creds or {}
    console.print("\n[bold]BigQuery Configuration:[/bold]")

    project_id = prompt_with_default(
        "Project ID (e.g., my-gcp-project-123456)", current_value=existing.get("project_id")
    )
    if not project_id:
        console.print("[red]❌ Project ID is required[/red]")
        return None

    credentials_path = prompt_with_default(
        "Path to service account JSON key file", current_value=existing.get("credentials_path")
    )
    if not credentials_path:
        console.print("[red]❌ Service account JSON key file path is required[/red]")
        return None

    credentials_path = os.path.expanduser(credentials_path)
    if not _validate_service_account_file(console, credentials_path):
        return None

    dataset_id = prompt_with_default(
        "Dataset name", current_value=existing.get("dataset_id"), default_if_none="benchbox"
    )
    if not dataset_id:
        console.print("[red]❌ Dataset name is required[/red]")
        return None

    location = prompt_with_default("Data location", current_value=existing.get("location"), default_if_none="US")
    if not location:
        console.print("[red]❌ Location is required[/red]")
        return None

    console.print("\n[bold]Cloud Storage Configuration (Recommended):[/bold]")
    console.print("[dim]Configuring Cloud Storage enables efficient data loading.[/dim]")
    console.print("[dim]Without Cloud Storage, data loading will be slower using direct streaming.[/dim]\n")

    storage_bucket: Optional[str] = None
    if Confirm.ask("Configure Cloud Storage bucket for efficient data loading?", default=True):
        storage_bucket = (
            prompt_with_default(
                "Cloud Storage bucket name (e.g., my-benchbox-data)",
                current_value=existing.get("storage_bucket"),
                default_if_none="",
            )
            or None
        )

    return {
        "project_id": project_id,
        "credentials_path": credentials_path,
        "dataset_id": dataset_id,
        "location": location,
        "storage_bucket": storage_bucket,
    }


def _finalize_bigquery_credentials(cred_manager: CredentialManager, console, config: dict) -> None:
    """Assemble, save, validate, and print next steps for BigQuery credentials."""
    credentials = {
        "project_id": config["project_id"],
        "credentials_path": config["credentials_path"],
        "dataset_id": config["dataset_id"],
        "location": config["location"],
    }
    storage_bucket = config.get("storage_bucket")
    if storage_bucket:
        credentials["storage_bucket"] = storage_bucket

    console.print("\n🧪 [bold]Validating credentials...[/bold]")
    cred_manager.set_platform_credentials("bigquery", credentials, CredentialStatus.NOT_VALIDATED)

    success, error = validate_bigquery_credentials(cred_manager)
    if success:
        cred_manager.update_validation_status("bigquery", CredentialStatus.VALID)
        cred_manager.save_credentials()
        console.print("\n[green]✅ BigQuery credentials validated and saved![/green]")
        console.print(f"   Location: [cyan]{cred_manager.credentials_path}[/cyan]")
        console.print("   Status: [green]Ready to use[/green]\n")
        if storage_bucket:
            console.print("[green]✅ Cloud Storage staging configured for efficient data loading[/green]\n")
        else:
            console.print(
                "[yellow]⚠️  No Cloud Storage staging configured - data loading will use direct streaming (slower)[/yellow]\n"
            )
        _prompt_default_output_location(cred_manager, console, credentials, storage_bucket)
        console.print("[bold]Try it:[/bold]")
        console.print("  benchbox run --platform bigquery --benchmark tpch --scale 0.01")
    else:
        cred_manager.update_validation_status("bigquery", CredentialStatus.INVALID, error)
        cred_manager.save_credentials()
        console.print("\n[red]❌ Validation failed[/red]")
        if error:
            console.print(f"   Error: {error}")
        console.print("\n[yellow]Credentials saved but marked as invalid.[/yellow]")
        console.print("Fix the issues and run: benchbox setup --platform bigquery --validate-only")


def setup_bigquery_credentials(cred_manager: CredentialManager, console: Union[Console, QuietConsoleProxy]) -> None:
    """Interactive setup for BigQuery credentials.

    Args:
        cred_manager: Credential manager instance
        console: Rich console for output
    """
    console.print("\n📋 [bold]You'll need:[/bold]")
    console.print("  • Google Cloud project ID")
    console.print("  • Service account JSON key file")
    console.print("  • Dataset name (will be created if it doesn't exist)")
    console.print("  • Data location (e.g., US, EU, us-central1)\n")
    console.print("[dim]Need help? Visit: https://cloud.google.com/iam/docs/service-accounts-create[/dim]\n")

    existing_creds = cred_manager.get_platform_credentials("bigquery")
    if existing_creds:
        console.print("ℹ️  [cyan]Existing credentials found - updating configuration[/cyan]\n")
        auto_config = None
    else:
        auto_config = None
        if Confirm.ask("🔍 Attempt auto-detection from environment variables?", default=True):
            console.print("\n[dim]Checking environment variables...[/dim]")
            auto_config = _auto_detect_bigquery(console)

    if auto_config:
        _print_bigquery_auto_config(console, auto_config)
        config = auto_config
    else:
        config = _prompt_bigquery_full(console, existing_creds)
        if config is None:
            return

    _finalize_bigquery_credentials(cred_manager, console, config)


def _prompt_default_output_location(
    cred_manager: CredentialManager,
    console: Union[Console, QuietConsoleProxy],
    credentials: dict,
    storage_bucket: Optional[str],
) -> None:
    """Prompt for default cloud output location for BigQuery."""
    from benchbox.platforms.credentials.shared import prompt_default_output_location

    prompt_default_output_location(
        cred_manager=cred_manager,
        console=console,
        credentials=credentials,
        platform_name="BigQuery",
        path_scheme="gs://",
        storage_label="Google Cloud Storage",
        permission_note="the service account has storage.objects.create permission",
        bucket=storage_bucket,
    )


def _validate_bigquery_credentials_file(credentials_path: str) -> Optional[str]:
    """Return None if file exists and is a valid service-account JSON, else error message."""
    if not os.path.exists(credentials_path):
        return f"Credentials file not found: {credentials_path}"
    if not os.path.isfile(credentials_path):
        return f"Credentials path is not a file: {credentials_path}"
    try:
        with open(credentials_path, encoding="utf-8") as f:
            json_content = json.load(f)
            if "type" not in json_content or json_content.get("type") != "service_account":
                return "Credentials file is not a valid service account JSON key"
    except json.JSONDecodeError:
        return "Credentials file is not valid JSON"
    except Exception as e:
        return f"Error reading credentials file: {e}"
    return None


def _test_bigquery_storage_access(credentials_path: str, project_id: str, storage_bucket: str) -> Optional[str]:
    """Verify Cloud Storage bucket access; returns None on success or an error message."""
    try:
        from google.cloud import storage

        storage_client = storage.Client.from_service_account_json(credentials_path, project=project_id)
        bucket = storage_client.bucket(storage_bucket)
        bucket.reload()
    except ImportError:
        return "Cloud Storage client library not installed. Run: pip install google-cloud-storage"
    except Exception as e:
        error_msg = str(e)
        if "not found" in error_msg.lower() or "404" in error_msg:
            return f"Cloud Storage bucket '{storage_bucket}' not found"
        if "forbidden" in error_msg.lower() or "403" in error_msg:
            return (
                f"No access to Cloud Storage bucket '{storage_bucket}'. Service account needs Storage Object Admin role"
            )
        return f"Cloud Storage access failed: {error_msg}"
    return None


def _classify_bigquery_connection_error(error_msg: str, project_id: Optional[str]) -> str:
    """Map raw BigQuery connection exception messages to user-friendly strings."""
    lower = error_msg.lower()
    if "could not find default credentials" in lower:
        return "Could not load credentials. Check that the service account JSON file is valid."
    if "permission denied" in lower or "forbidden" in lower:
        return "Permission denied. Service account needs BigQuery Data Editor and BigQuery Job User roles."
    if "not found" in lower and "project" in lower:
        return f"Project '{project_id}' not found or not accessible."
    if "invalid" in lower and ("credentials" in lower or "key" in lower):
        return "Invalid service account credentials. Check that the JSON key file is correct."
    return f"Connection failed: {error_msg}"


def validate_bigquery_credentials(cred_manager: CredentialManager) -> tuple[bool, Optional[str]]:
    """Validate BigQuery credentials by testing connection.

    Args:
        cred_manager: Credential manager instance

    Returns:
        Tuple of (success, error_message)
    """
    creds = cred_manager.get_platform_credentials("bigquery")
    if not creds:
        return False, "No credentials found"

    missing = [field for field in ("project_id", "credentials_path") if not creds.get(field)]
    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"

    credentials_path = os.path.expanduser(creds.get("credentials_path"))
    file_error = _validate_bigquery_credentials_file(credentials_path)
    if file_error:
        return False, file_error

    try:
        from google.cloud import bigquery
    except ImportError:
        return False, "BigQuery client library not installed. Run: pip install google-cloud-bigquery"

    try:
        client = bigquery.Client.from_service_account_json(credentials_path, project=creds["project_id"])

        client.query("SELECT 1 as test").result()

        project_job = client.query("SELECT @@project_id as project")
        results = list(project_job.result())
        if not results or not results[0].project:
            return False, "Could not verify project access"

        try:
            list(client.list_datasets(max_results=1))
        except Exception:
            # Not fatal - user may lack list permission but can still use datasets
            pass

        storage_bucket = creds.get("storage_bucket")
        if storage_bucket:
            storage_error = _test_bigquery_storage_access(credentials_path, creds["project_id"], storage_bucket)
            if storage_error:
                return False, storage_error

        return True, None

    except Exception as e:
        return False, _classify_bigquery_connection_error(str(e), creds.get("project_id"))


def _auto_detect_bigquery(console: Union[Console, QuietConsoleProxy]) -> Optional[dict]:
    """Attempt to auto-detect BigQuery configuration from environment variables.

    Args:
        console: Rich console for output

    Returns:
        Dictionary with detected config or None
    """
    env_vars = {
        "credentials_path": os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
        "project_id": os.getenv("BIGQUERY_PROJECT"),
        "dataset_id": os.getenv("BIGQUERY_DATASET"),
        "location": os.getenv("BIGQUERY_LOCATION"),
        "storage_bucket": os.getenv("BIGQUERY_STORAGE_BUCKET"),
    }

    # Check if we have the required fields
    required = ["credentials_path", "project_id"]
    found_required = all(env_vars.get(field) for field in required)

    if not found_required:
        missing = []
        if not env_vars.get("credentials_path"):
            missing.append("GOOGLE_APPLICATION_CREDENTIALS")
        if not env_vars.get("project_id"):
            missing.append("BIGQUERY_PROJECT")
        console.print(f"  ⚠️  Missing environment variables: {', '.join(missing)}")
        return None

    # Validate credentials file exists
    credentials_path = os.path.expanduser(env_vars["credentials_path"])
    if not os.path.exists(credentials_path):
        console.print(f"  ⚠️  Credentials file not found: {credentials_path}")
        return None

    # Set defaults for optional fields
    if not env_vars.get("dataset_id"):
        env_vars["dataset_id"] = "benchbox"
    if not env_vars.get("location"):
        env_vars["location"] = "US"

    console.print("  ✓ Found all required environment variables")

    # Check for Cloud Storage configuration
    if env_vars.get("storage_bucket"):
        console.print("  ✓ Found Cloud Storage staging configuration")

    return env_vars


__all__ = ["setup_bigquery_credentials", "validate_bigquery_credentials"]
