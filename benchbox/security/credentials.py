# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import os
import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml


class CredentialStatus(Enum):
    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"
    NOT_VALIDATED = "not_validated"
    MISSING = "missing"


class CredentialManager:
    def __init__(self, credentials_path: Optional[Path] = None):
        self.credentials_path = credentials_path or self._get_default_credentials_path()
        self.credentials = self._load_credentials()

    def _get_default_credentials_path(self) -> Path:
        return Path.home() / ".benchbox" / "credentials.yaml"

    def _load_credentials(self) -> dict[str, Any]:
        if not self.credentials_path.exists():
            return {}

        try:
            with open(self.credentials_path, encoding="utf-8") as f:
                raw_data = yaml.safe_load(f) or {}

            return self._substitute_env_vars(raw_data)

        except Exception as e:
            raise ValueError(f"Failed to load credentials from {self.credentials_path}: {e}") from e

    def _substitute_env_vars(self, data: Any) -> Any:
        if isinstance(data, dict):
            return {key: self._substitute_env_vars(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._substitute_env_vars(item) for item in data]
        elif isinstance(data, str):
            pattern = r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)"

            def replace_var(match):
                var_name = match.group(1) or match.group(2)
                return os.getenv(var_name, match.group(0))

            return re.sub(pattern, replace_var, data)
        else:
            return data

    def save_credentials(self) -> None:
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True)

        data_to_save = dict(self.credentials)
        data_to_save["_metadata"] = {
            "version": "1.0",
            "last_updated": datetime.now().isoformat(),
        }

        with open(self.credentials_path, "w", encoding="utf-8") as f:
            yaml.dump(data_to_save, f, default_flow_style=False, sort_keys=False)

        try:
            self.credentials_path.chmod(0o600)
        except Exception:
            pass

    def get_platform_credentials(self, platform: str) -> Optional[dict[str, Any]]:
        return self.credentials.get(platform.lower())

    def set_platform_credentials(
        self,
        platform: str,
        credentials: dict[str, Any],
        status: CredentialStatus = CredentialStatus.NOT_VALIDATED,
    ) -> None:
        platform_key = platform.lower()

        cred_data = dict(credentials)
        cred_data["last_updated"] = datetime.now().isoformat()
        cred_data["status"] = status.value

        self.credentials[platform_key] = cred_data

    def update_validation_status(
        self, platform: str, status: CredentialStatus, error_message: Optional[str] = None
    ) -> None:
        platform_key = platform.lower()

        if platform_key not in self.credentials:
            return

        self.credentials[platform_key]["status"] = status.value
        self.credentials[platform_key]["last_validated"] = datetime.now().isoformat()

        if error_message:
            self.credentials[platform_key]["error_message"] = error_message
        elif "error_message" in self.credentials[platform_key]:
            del self.credentials[platform_key]["error_message"]

    def get_credential_status(self, platform: str) -> CredentialStatus:
        creds = self.get_platform_credentials(platform)

        if not creds:
            return CredentialStatus.MISSING

        status_str = creds.get("status", "not_validated")
        try:
            return CredentialStatus(status_str)
        except ValueError:
            return CredentialStatus.NOT_VALIDATED

    def has_credentials(self, platform: str) -> bool:
        return platform.lower() in self.credentials

    def remove_platform_credentials(self, platform: str) -> bool:
        platform_key = platform.lower()

        if platform_key in self.credentials:
            del self.credentials[platform_key]
            return True

        return False

    def list_platforms(self) -> dict[str, CredentialStatus]:
        platforms = {}

        for platform in self.credentials:
            if platform.startswith("_"):
                continue

            platforms[platform] = self.get_credential_status(platform)

        return platforms

    def get_display_credentials(self, platform: str) -> dict[str, Any]:
        creds = self.get_platform_credentials(platform)

        if not creds:
            return {}

        sensitive_fields = [
            "password",
            "token",
            "access_token",
            "secret",
            "api_key",
            "private_key",
        ]

        display_creds = {}
        for key, value in creds.items():
            if key in sensitive_fields or any(field in key.lower() for field in sensitive_fields):
                if value:
                    if len(str(value)) > 12:
                        display_creds[key] = f"{str(value)[:4]}...{str(value)[-4:]}"
                    else:
                        display_creds[key] = "****"
                else:
                    display_creds[key] = "(not set)"
            else:
                display_creds[key] = value

        return display_creds


__all__ = ["CredentialManager", "CredentialStatus"]
