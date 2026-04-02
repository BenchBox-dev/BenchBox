"""Redshift credentials setup and validation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import contextlib
import os
import socket
import time
from typing import Any, Optional, Union

from rich.console import Console
from rich.prompt import Confirm, IntPrompt

from benchbox.platforms.credentials.helpers import prompt_secure_field, prompt_with_default
from benchbox.security.credentials import CredentialManager, CredentialStatus
from benchbox.utils.printing import QuietConsoleProxy


def setup_redshift_credentials(cred_manager: CredentialManager, console: Union[Console, QuietConsoleProxy]) -> None:
    """Interactive setup for Redshift credentials.

    Args:
        cred_manager: Credential manager instance
        console: Rich console for output
    """
    console.print("\n📋 [bold]You'll need:[/bold]")
    console.print("  • Redshift cluster endpoint")
    console.print("  • Username and password")
    console.print("  • Database name (default: dev)\n")

    console.print(
        "[dim]Need help? Visit: https://docs.aws.amazon.com/redshift/latest/mgmt/connecting-to-cluster.html[/dim]\n"
    )

    # Load existing credentials to use as defaults
    existing_creds = cred_manager.get_platform_credentials("redshift")

    # Only offer auto-detection if no existing credentials
    if existing_creds:
        console.print("ℹ️  [cyan]Existing credentials found - updating configuration[/cyan]\n")
        auto_config = None
    else:
        # Try auto-detection from environment variables
        auto_config = None
        try_auto = Confirm.ask("🔍 Attempt auto-detection from environment variables?", default=True)

        if try_auto:
            console.print("\n[dim]Checking environment variables...[/dim]")
            auto_config = _auto_detect_redshift(console)

    # Get credentials (use auto-detected or prompt)
    if auto_config:
        host = auto_config.get("host")
        port = auto_config.get("port")
        database = auto_config.get("database")
        username = auto_config.get("username")
        password = auto_config.get("password")
        schema = auto_config.get("schema")
        s3_bucket = auto_config.get("s3_bucket")
        iam_role = auto_config.get("iam_role")
        aws_access_key_id = auto_config.get("aws_access_key_id")
        aws_secret_access_key = auto_config.get("aws_secret_access_key")
        aws_region = auto_config.get("aws_region")

        console.print(f"\n✅ Found cluster endpoint: [cyan]{host}[/cyan]")
        console.print(f"✅ Found port: [cyan]{port}[/cyan]")
        console.print(f"✅ Found database: [cyan]{database}[/cyan]")
        console.print(f"✅ Found username: [cyan]{username}[/cyan]")
        if schema:
            console.print(f"✅ Found schema: [cyan]{schema}[/cyan]")
        if s3_bucket:
            console.print(f"✅ Found S3 bucket: [cyan]{s3_bucket}[/cyan]")
        if iam_role:
            console.print(f"✅ Found IAM role: [cyan]{iam_role}[/cyan]")
    else:
        console.print("\n[bold]Redshift Cluster Configuration:[/bold]")

        # Use existing credentials as defaults if available
        current_host = existing_creds.get("host") if existing_creds else None
        current_port = existing_creds.get("port") if existing_creds else None
        current_database = existing_creds.get("database") if existing_creds else None
        current_username = existing_creds.get("username") if existing_creds else None
        current_password = existing_creds.get("password") if existing_creds else None
        current_schema = existing_creds.get("schema") if existing_creds else None
        current_s3_bucket = existing_creds.get("s3_bucket") if existing_creds else None
        current_iam_role = existing_creds.get("iam_role") if existing_creds else None
        current_aws_access_key_id = existing_creds.get("aws_access_key_id") if existing_creds else None
        current_aws_secret_access_key = existing_creds.get("aws_secret_access_key") if existing_creds else None
        current_aws_region = existing_creds.get("aws_region") if existing_creds else None

        host = prompt_with_default(
            "Cluster endpoint (e.g., my-cluster.abc123.us-east-1.redshift.amazonaws.com)",
            current_value=current_host,
        )

        if not host:
            console.print("[red]❌ Cluster endpoint is required[/red]")
            return

        # IntPrompt doesn't have a good way to show current value, so handle separately
        if current_port:
            port_prompt = f"Port (current: {current_port})"
            port = IntPrompt.ask(port_prompt, default=current_port)
        else:
            port = IntPrompt.ask("Port", default=5439)

        database = prompt_with_default("Database name", current_value=current_database, default_if_none="dev")

        if not database:
            console.print("[red]❌ Database name is required[/red]")
            return

        username = prompt_with_default("Username", current_value=current_username)

        if not username:
            console.print("[red]❌ Username is required[/red]")
            return

        password = prompt_secure_field("Password", current_value=current_password, console=console)

        if not password:
            console.print("[red]❌ Password is required[/red]")
            return

        # Optional settings
        console.print("\n[bold]Optional Settings:[/bold]")
        schema = prompt_with_default("Schema name", current_value=current_schema, default_if_none="public")

        # S3 staging configuration (optional but recommended)
        console.print("\n[bold]S3 Staging Configuration (Recommended):[/bold]")
        console.print("[dim]Configuring S3 staging enables efficient data loading via COPY commands.[/dim]")
        console.print("[dim]Without S3, data loading will be slower using direct INSERT statements.[/dim]\n")

        configure_s3 = Confirm.ask("Configure S3 staging for efficient data loading?", default=True)

        if configure_s3:
            s3_bucket = prompt_with_default(
                "S3 bucket name (e.g., my-benchbox-data)", current_value=current_s3_bucket, default_if_none=""
            )

            if s3_bucket:
                console.print("\n[bold]S3 Authentication Method:[/bold]")
                console.print("1. IAM Role ARN (recommended for EC2/ECS)")
                console.print("2. AWS Access Keys\n")

                # Default to method 1 if IAM role exists, method 2 if access keys exist
                default_method = 1 if current_iam_role else (2 if current_aws_access_key_id else 1)
                auth_method = IntPrompt.ask("Choose authentication method [1-2]", default=default_method)

                if auth_method == 1:
                    iam_role = prompt_with_default(
                        "IAM Role ARN (e.g., arn:aws:iam::123456789012:role/RedshiftS3AccessRole)",
                        current_value=current_iam_role,
                        default_if_none="",
                    )
                    aws_access_key_id = None
                    aws_secret_access_key = None
                else:
                    iam_role = None
                    aws_access_key_id = prompt_with_default(
                        "AWS Access Key ID", current_value=current_aws_access_key_id, default_if_none=""
                    )
                    aws_secret_access_key = prompt_secure_field(
                        "AWS Secret Access Key", current_value=current_aws_secret_access_key, console=console
                    )

                aws_region = prompt_with_default(
                    "AWS Region", current_value=current_aws_region, default_if_none="us-east-1"
                )
            else:
                s3_bucket = None
                iam_role = None
                aws_access_key_id = None
                aws_secret_access_key = None
                aws_region = None
        else:
            s3_bucket = None
            iam_role = None
            aws_access_key_id = None
            aws_secret_access_key = None
            aws_region = None

    # Build credentials
    credentials = {
        "host": host,
        "port": port,
        "database": database,
        "username": username,
        "password": password,
    }

    if schema:
        credentials["schema"] = schema
    if s3_bucket:
        credentials["s3_bucket"] = s3_bucket
    if iam_role:
        credentials["iam_role"] = iam_role
    if aws_access_key_id:
        credentials["aws_access_key_id"] = aws_access_key_id
    if aws_secret_access_key:
        credentials["aws_secret_access_key"] = aws_secret_access_key
    if aws_region:
        credentials["aws_region"] = aws_region

    # Validate credentials
    console.print("\n🧪 [bold]Validating credentials...[/bold]")

    # Save temporarily for validation
    cred_manager.set_platform_credentials("redshift", credentials, CredentialStatus.NOT_VALIDATED)

    success, error = validate_redshift_credentials(cred_manager, console)

    if success:
        cred_manager.update_validation_status("redshift", CredentialStatus.VALID)
        cred_manager.save_credentials()

        console.print("\n[green]✅ Redshift credentials validated and saved![/green]")
        console.print(f"   Location: [cyan]{cred_manager.credentials_path}[/cyan]")
        console.print("   Status: [green]Ready to use[/green]\n")

        if s3_bucket:
            console.print("[green]✅ S3 staging configured for efficient data loading[/green]\n")
        else:
            console.print(
                "[yellow]⚠️  No S3 staging configured - data loading will use direct INSERT (slower)[/yellow]\n"
            )

        # Prompt for default output location (optional)
        _prompt_default_output_location(cred_manager, console, credentials, s3_bucket)

        console.print("[bold]Try it:[/bold]")
        console.print("  benchbox run --platform redshift --benchmark tpch --scale 0.01")
    else:
        cred_manager.update_validation_status("redshift", CredentialStatus.INVALID, error)
        cred_manager.save_credentials()

        console.print("\n[red]❌ Validation failed[/red]")
        if error:
            console.print(f"   Error: {error}")
        console.print("\n[yellow]Credentials saved but marked as invalid.[/yellow]")
        console.print("Fix the issues and run: benchbox setup --platform redshift --validate-only")


def _prompt_default_output_location(
    cred_manager: CredentialManager,
    console: Union[Console, QuietConsoleProxy],
    credentials: dict,
    s3_bucket: Optional[str],
) -> None:
    """Prompt for default cloud output location for Redshift."""
    from benchbox.platforms.credentials.shared import prompt_default_output_location

    prompt_default_output_location(
        cred_manager=cred_manager,
        console=console,
        credentials=credentials,
        platform_name="Redshift",
        path_scheme="s3://",
        storage_label="S3 Staging Location",
        permission_note="the cluster IAM role has s3:PutObject permission",
        bucket=s3_bucket,
    )


_REDSHIFT_ADAPTER_CREDENTIAL_KEYS = (
    "host",
    "port",
    "database",
    "username",
    "password",
    "schema",
    "s3_bucket",
    "s3_prefix",
    "staging_root",
    "iam_role",
    "aws_access_key_id",
    "aws_secret_access_key",
    "aws_region",
    "cluster_identifier",
    "admin_database",
    "connect_timeout",
    "statement_timeout",
    "sslmode",
    "ssl_enabled",
    "ssl_insecure",
    "sslrootcert",
    "wlm_query_slot_count",
    "wlm_query_queue_name",
    "wlm_config",
    "compupdate",
    "auto_vacuum",
    "auto_analyze",
)


def _build_redshift_adapter(creds: dict[str, Any]) -> Any:
    """Build a Redshift adapter from saved credentials."""
    from benchbox.platforms.redshift import RedshiftAdapter

    adapter_kwargs = {key: creds[key] for key in _REDSHIFT_ADAPTER_CREDENTIAL_KEYS if key in creds}
    return RedshiftAdapter(**adapter_kwargs)


def _probe_redshift_connection(adapter: Any, *, database: str, connect_timeout: int) -> None:
    """Open a direct validation connection and run smoke queries."""
    connection = None
    cursor = None

    try:
        connection = adapter._create_direct_connection(database=database, connect_timeout=connect_timeout)
        cursor = connection.cursor()

        cursor.execute("SELECT 1")
        cursor.fetchall()

        cursor.execute("SELECT version()")
        cursor.fetchall()

        cursor.execute("SELECT current_database()")
        cursor.fetchall()
    finally:
        if cursor:
            with contextlib.suppress(Exception):
                cursor.close()
        if connection:
            with contextlib.suppress(Exception):
                connection.close()


def _is_timeout_error(error_msg: str) -> bool:
    """Return True when the driver reported a timeout-style failure."""
    error_lower = error_msg.lower()
    return "timeout" in error_lower or "timed out" in error_lower


def _is_retryable_error(error_msg: str) -> bool:
    """Return True for transient errors worth retrying (timeout, connection refused)."""
    error_lower = error_msg.lower()
    return _is_timeout_error(error_msg) or "could not connect" in error_lower or "connection refused" in error_lower


def _format_redshift_validation_error(error_msg: str, database: str) -> str:
    """Map driver errors to user-facing Redshift setup guidance."""
    error_lower = error_msg.lower()

    if _is_timeout_error(error_msg):
        return "Connection timeout. Check VPC/security group settings and network connectivity."
    if "could not connect" in error_lower or "connection refused" in error_lower:
        return "Connection refused. Check cluster endpoint, VPC/security group settings, and network connectivity."
    if "password authentication failed" in error_lower or "authentication" in error_lower:
        return "Authentication failed. Check your username and password."
    if "cluster" in error_lower and "not found" in error_lower:
        return "Cluster endpoint is invalid or cluster does not exist."
    if "database" in error_lower and "does not exist" in error_lower:
        return f"Database '{database}' not found. It will be created during benchmark setup."
    if "server refuses ssl" in error_lower:
        return "SSL negotiation failed. Check that the endpoint is a Redshift endpoint that accepts TLS on port 5439."

    return f"Connection failed: {error_msg}"


def validate_redshift_credentials(
    cred_manager: CredentialManager, console: Optional[Union[Console, QuietConsoleProxy]] = None
) -> tuple[bool, Optional[str]]:
    """Validate Redshift credentials by testing connection with diagnostics.

    Args:
        cred_manager: Credential manager instance
        console: Optional console for detailed output

    Returns:
        Tuple of (success, error_message)
    """
    creds = cred_manager.get_platform_credentials("redshift")

    if not creds:
        return False, "No credentials found"

    required_fields = ["host", "username", "password"]
    missing = [field for field in required_fields if not creds.get(field)]

    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"

    host = creds["host"]
    port = creds.get("port", 5439)
    database = creds.get("database", "dev")
    aws_access_key_id = creds.get("aws_access_key_id")
    aws_secret_access_key = creds.get("aws_secret_access_key")
    aws_region = creds.get("aws_region", "us-east-1")

    try:
        adapter = _build_redshift_adapter(creds)
    except ImportError as e:
        return False, str(e)

    # Step 1: Test TCP connectivity first (quick check)
    if console:
        console.print("\n[dim]Testing network connectivity...[/dim]")

    tcp_reachable, tcp_error = _test_tcp_connectivity(host, port, timeout=10)

    if not tcp_reachable:
        # TCP connection failed - run diagnostics
        if console:
            console.print(f"[yellow]⚠️  Network connectivity issue: {tcp_error}[/yellow]")

            # Run AWS diagnostics
            diagnostics = _diagnose_redshift_connectivity(
                host, port, aws_access_key_id, aws_secret_access_key, aws_region
            )

            # Show diagnostic output
            _format_diagnostic_output(console, host, port, aws_region, diagnostics)

            # Show remediation steps
            _format_remediation_steps(console, host, port, aws_region, diagnostics, tcp_reachable)

        return False, "Connection timeout. Check VPC/security group settings and network connectivity."

    # Step 2: Attempt database connection with retries
    if console:
        console.print("[dim]Network connectivity OK. Testing database connection...[/dim]")

    max_retries = 3
    retry_delays = [0, 2, 5]  # seconds between retries

    last_error = None

    for attempt in range(max_retries):
        try:
            if attempt > 0:
                if console:
                    console.print(f"[dim]Retry attempt {attempt + 1}/{max_retries}...[/dim]")
                time.sleep(retry_delays[attempt])

            # Attempt connection with progressive timeout
            timeout = 10 + (attempt * 10)  # 10s, 20s, 30s

            _probe_redshift_connection(adapter, database=database, connect_timeout=timeout)
            return True, None

        except Exception as e:
            last_error = e

            # Only retry transient errors (timeout, connection refused) with attempts remaining
            if attempt < max_retries - 1 and _is_retryable_error(str(e)):
                continue

            break

    # All retries exhausted
    error_msg = str(last_error)

    # Run diagnostics for detailed error
    if console:
        diagnostics = _diagnose_redshift_connectivity(host, port, aws_access_key_id, aws_secret_access_key, aws_region)
        _format_diagnostic_output(console, host, port, aws_region, diagnostics)
        _format_remediation_steps(console, host, port, aws_region, diagnostics, tcp_reachable)

    return False, _format_redshift_validation_error(error_msg, database)


def _auto_detect_redshift(console: Union[Console, QuietConsoleProxy]) -> Optional[dict]:
    """Attempt to auto-detect Redshift configuration from environment variables.

    Args:
        console: Rich console for output

    Returns:
        Dictionary with detected config or None
    """
    env_vars = {
        "host": os.getenv("REDSHIFT_HOST"),
        "port": os.getenv("REDSHIFT_PORT"),
        "database": os.getenv("REDSHIFT_DATABASE"),
        "username": os.getenv("REDSHIFT_USERNAME"),
        "password": os.getenv("REDSHIFT_PASSWORD"),
        "schema": os.getenv("REDSHIFT_SCHEMA"),
        # S3 staging (optional)
        "s3_bucket": os.getenv("REDSHIFT_S3_BUCKET"),
        "iam_role": os.getenv("REDSHIFT_IAM_ROLE"),
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "aws_region": os.getenv("AWS_DEFAULT_REGION"),
    }

    # Check if we have the required fields
    required = ["host", "username", "password", "database"]
    found_required = all(env_vars.get(field) for field in required)

    if not found_required:
        missing = [f"REDSHIFT_{field.upper()}" for field in required if not env_vars.get(field)]
        console.print(f"  ⚠️  Missing environment variables: {', '.join(missing)}")
        return None

    # Convert port to int if present
    if env_vars.get("port"):
        try:
            env_vars["port"] = int(env_vars["port"])
        except ValueError:
            env_vars["port"] = 5439
    else:
        env_vars["port"] = 5439

    console.print("  ✓ Found all required environment variables")

    # Check for S3 staging configuration
    if env_vars.get("s3_bucket"):
        console.print("  ✓ Found S3 staging configuration")

    return env_vars


def _test_tcp_connectivity(host: str, port: int, timeout: int = 5) -> tuple[bool, Optional[str]]:
    """Test raw TCP connectivity to Redshift endpoint.

    Args:
        host: Redshift host endpoint
        port: Port to connect to (default 5439)
        timeout: Connection timeout in seconds

    Returns:
        Tuple of (success, error_message)
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            return True, None
        else:
            return False, f"Cannot establish TCP connection (error code: {result})"

    except socket.gaierror as e:
        return False, f"DNS resolution failed: {e}"
    except TimeoutError:
        return False, "TCP connection timeout - host unreachable or port blocked"
    except Exception as e:
        return False, f"Network error: {e}"


def _get_public_ip() -> Optional[str]:
    """Get the current public IP address for display in error messages.

    Returns:
        Public IP address or None if unavailable
    """
    try:
        import urllib.request

        # Use multiple services for redundancy
        services = [
            "https://api.ipify.org",
            "https://checkip.amazonaws.com",
            "https://icanhazip.com",
        ]

        for service in services:
            try:
                with urllib.request.urlopen(service, timeout=3) as response:
                    ip = response.read().decode("utf-8").strip()
                    if ip:
                        return ip
            except Exception:
                continue

        return None
    except Exception:
        return None


def _diagnose_redshift_connectivity(
    host: str, port: int, aws_access_key_id: Optional[str], aws_secret_access_key: Optional[str], aws_region: str
) -> dict:
    """Run AWS API diagnostics on Redshift Serverless workgroup.

    Args:
        host: Redshift endpoint hostname
        port: Port number
        aws_access_key_id: AWS access key (optional)
        aws_secret_access_key: AWS secret key (optional)
        aws_region: AWS region

    Returns:
        Dictionary with diagnostic results
    """
    diagnostics = {
        "workgroup_name": None,
        "publicly_accessible": None,
        "vpc_id": None,
        "subnet_ids": [],
        "security_group_ids": [],
        "error": None,
    }

    try:
        # Extract workgroup name from endpoint
        # Format: workgroup-name.account-id.region.redshift-serverless.amazonaws.com
        if ".redshift-serverless.amazonaws.com" in host:
            workgroup_name = host.split(".")[0]
            diagnostics["workgroup_name"] = workgroup_name
        elif ".redshift.amazonaws.com" in host:
            # Provisioned cluster
            cluster_id = host.split(".")[0]
            diagnostics["cluster_id"] = cluster_id
            diagnostics["is_serverless"] = False
        else:
            diagnostics["error"] = "Unknown endpoint format"
            return diagnostics

        # Try to use boto3 to get workgroup details
        try:
            import boto3
        except ImportError:
            diagnostics["error"] = "boto3 not available for diagnostics"
            return diagnostics

        # Create client with provided credentials or use default chain
        client_kwargs = {"region_name": aws_region}
        if aws_access_key_id and aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = aws_access_key_id
            client_kwargs["aws_secret_access_key"] = aws_secret_access_key

        try:
            if diagnostics.get("is_serverless") is False:
                # Provisioned cluster
                redshift_client = boto3.client("redshift", **client_kwargs)
                response = redshift_client.describe_clusters(ClusterIdentifier=diagnostics["cluster_id"])
                cluster = response["Clusters"][0]

                diagnostics["publicly_accessible"] = cluster.get("PubliclyAccessible", False)
                diagnostics["vpc_id"] = cluster.get("VpcId")
                diagnostics["subnet_ids"] = [sg["SubnetIdentifier"] for sg in cluster.get("ClusterSubnetGroupName", [])]
                diagnostics["security_group_ids"] = [
                    sg["VpcSecurityGroupId"] for sg in cluster.get("VpcSecurityGroups", [])
                ]

            else:
                # Serverless workgroup
                redshift_serverless_client = boto3.client("redshift-serverless", **client_kwargs)
                response = redshift_serverless_client.get_workgroup(workgroupName=workgroup_name)
                workgroup = response["workgroup"]

                diagnostics["publicly_accessible"] = workgroup.get("publiclyAccessible", False)

                # Get VPC configuration from endpoint
                if "endpoint" in workgroup:
                    endpoint = workgroup["endpoint"]
                    diagnostics["vpc_id"] = endpoint.get("vpcEndpoint", {}).get("vpcId")

                # Get security group IDs
                if "securityGroupIds" in workgroup:
                    diagnostics["security_group_ids"] = workgroup["securityGroupIds"]

                # Get subnet IDs
                if "subnetIds" in workgroup:
                    diagnostics["subnet_ids"] = workgroup["subnetIds"]

        except Exception as e:
            # AWS API call failed - could be permissions, wrong region, etc.
            diagnostics["error"] = f"AWS API error: {str(e)}"

    except Exception as e:
        diagnostics["error"] = f"Diagnostic error: {str(e)}"

    return diagnostics


def _format_diagnostic_output(
    console: Union[Console, QuietConsoleProxy], host: str, port: int, aws_region: str, diagnostics: dict
) -> None:
    """Format and display diagnostic information.

    Args:
        console: Console for output
        host: Redshift endpoint
        port: Port number
        aws_region: AWS region
        diagnostics: Diagnostic results from _diagnose_redshift_connectivity
    """
    console.print("\n[bold cyan]🔍 Connection Diagnostics[/bold cyan]\n")

    # Show what we detected
    if diagnostics.get("workgroup_name"):
        console.print(f"  • Workgroup: [cyan]{diagnostics['workgroup_name']}[/cyan] ({aws_region})")
    elif diagnostics.get("cluster_id"):
        console.print(f"  • Cluster: [cyan]{diagnostics['cluster_id']}[/cyan] ({aws_region})")
    else:
        console.print(f"  • Endpoint: [cyan]{host}:{port}[/cyan]")

    # Show publicly accessible status
    if diagnostics.get("publicly_accessible") is not None:
        if diagnostics["publicly_accessible"]:
            console.print("  • Publicly Accessible: [green]✓ Yes[/green]")
        else:
            console.print("  • Publicly Accessible: [red]✗ No[/red]")

    # Show user's IP if available
    user_ip = _get_public_ip()
    if user_ip:
        console.print(f"  • Your Public IP: [cyan]{user_ip}[/cyan]")

    # Show VPC info if available
    if diagnostics.get("vpc_id"):
        console.print(f"  • VPC: {diagnostics['vpc_id']}")
    if diagnostics.get("security_group_ids"):
        console.print(f"  • Security Groups: {', '.join(diagnostics['security_group_ids'])}")

    # Show error if AWS API failed
    if diagnostics.get("error"):
        console.print(f"\n[dim]Note: {diagnostics['error']}[/dim]")


def _format_remediation_steps(
    console: Union[Console, QuietConsoleProxy],
    host: str,
    port: int,
    aws_region: str,
    diagnostics: dict,
    tcp_reachable: bool,
) -> None:
    """Format and display remediation steps for connection issues.

    Args:
        console: Console for output
        host: Redshift endpoint
        port: Port number
        aws_region: AWS region
        diagnostics: Diagnostic results
        tcp_reachable: Whether TCP connection was successful
    """
    console.print("\n[bold yellow]📋 Troubleshooting Steps[/bold yellow]\n")

    workgroup_name = diagnostics.get("workgroup_name")
    cluster_id = diagnostics.get("cluster_id")
    publicly_accessible = diagnostics.get("publicly_accessible")
    user_ip = _get_public_ip()

    # Step 1: Make publicly accessible if needed
    if publicly_accessible is False:
        console.print("[bold]1. Enable public access to your Redshift workgroup/cluster[/bold]")

        if workgroup_name:
            # Serverless workgroup
            console_url = f"https://console.aws.amazon.com/redshiftv2/home?region={aws_region}#serverless-workgroup-configuration?workgroup={workgroup_name}"
            console.print(f"   → Open AWS Console: [link={console_url}]{console_url}[/link]")
            console.print("   → Click 'Actions' → 'Edit'")
            console.print("   → Under 'Network and security', enable 'Turn on Publicly accessible'")
            console.print("   → Click 'Save changes'\n")
        elif cluster_id:
            # Provisioned cluster
            console_url = f"https://console.aws.amazon.com/redshiftv2/home?region={aws_region}#cluster-details?cluster={cluster_id}"
            console.print(f"   → Open AWS Console: [link={console_url}]{console_url}[/link]")
            console.print("   → Click 'Actions' → 'Modify publicly accessible setting'")
            console.print("   → Enable 'Publicly accessible'")
            console.print("   → Click 'Confirm'\n")
        else:
            console.print("   → Log into AWS Console")
            console.print(f"   → Navigate to Redshift service in region: {aws_region}")
            console.print("   → Find your workgroup/cluster and enable 'Publicly accessible'\n")

        step_num = 2
    else:
        step_num = 1

    # Step 2: Update security group
    console.print(f"[bold]{step_num}. Configure security group to allow inbound connections[/bold]")

    if diagnostics.get("security_group_ids"):
        sg_ids = diagnostics["security_group_ids"]
        for sg_id in sg_ids:
            sg_url = f"https://console.aws.amazon.com/vpc/home?region={aws_region}#SecurityGroup:groupId={sg_id}"
            console.print(f"   → Open Security Group: [link={sg_url}]{sg_id}[/link]")
    else:
        console.print(f"   → Navigate to VPC → Security Groups in AWS Console ({aws_region})")
        console.print("   → Find the security group attached to your Redshift workgroup/cluster")

    console.print("   → Click 'Inbound rules' → 'Edit inbound rules' → 'Add rule'")
    console.print("   → Type: Redshift (or Custom TCP)")
    console.print(f"   → Port: {port}")

    if user_ip:
        console.print(f"   → Source: Custom → {user_ip}/32  [dim](your current IP)[/dim]")
    else:
        console.print("   → Source: Custom → <your-ip>/32  [dim](find your IP at https://whatismyip.com)[/dim]")

    console.print("   → Description: BenchBox access")
    console.print("   → Click 'Save rules'\n")

    step_num += 1

    # Step 3: Verify VPC has internet gateway
    if publicly_accessible is False or diagnostics.get("vpc_id"):
        console.print(f"[bold]{step_num}. Verify VPC has an Internet Gateway attached[/bold]")
        if diagnostics.get("vpc_id"):
            vpc_url = f"https://console.aws.amazon.com/vpc/home?region={aws_region}#vpcs:VpcId={diagnostics['vpc_id']}"
            console.print(f"   → Open VPC: [link={vpc_url}]{diagnostics['vpc_id']}[/link]")
        else:
            console.print(f"   → Navigate to VPC service in AWS Console ({aws_region})")
        console.print("   → Check that an Internet Gateway is attached to the VPC")
        console.print("   → Verify route table has route to 0.0.0.0/0 via Internet Gateway\n")

        step_num += 1

    # Step 4: Test connection
    console.print(f"[bold]{step_num}. Test the connection[/bold]")
    console.print("   → After making the above changes, run:")
    console.print("   [cyan]benchbox setup --platform redshift --validate-only[/cyan]\n")

    # Additional resources
    console.print("[bold]📚 Additional Resources[/bold]")
    console.print("   → AWS Docs: https://docs.aws.amazon.com/redshift/latest/mgmt/managing-cluster-cross-vpc.html")
    console.print("   → Network troubleshooting: https://repost.aws/knowledge-center/redshift-cluster-private-public")


__all__ = ["setup_redshift_credentials", "validate_redshift_credentials"]
