# Copyright 2026 Joe Harris / BenchBox Project
# Licensed under the MIT License. See LICENSE file in the project root.

from __future__ import annotations

import time
from typing import Any


class AzureTokenProvider:
    _REFRESH_BUFFER_SECONDS: int = 300

    def __init__(
        self,
        *,
        scope: str,
        credential_class: Any,
        tenant_id: str | None = None,
    ) -> None:
        self._scope = scope
        self._credential_class = credential_class
        self._tenant_id = tenant_id
        self._credential: Any = None
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def credential(self) -> Any:
        if self._credential is None:
            kwargs: dict[str, Any] = {}
            if self._tenant_id:
                kwargs["additionally_allowed_tenants"] = ["*"]
            self._credential = self._credential_class(**kwargs)
        return self._credential

    def access_token(self) -> str:
        now = time.time()
        if self._access_token is None or now >= self._token_expires_at - self._REFRESH_BUFFER_SECONDS:
            token = self.credential().get_token(self._scope)
            self._access_token = token.token
            self._token_expires_at = token.expires_on
        return self._access_token

    def auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token()}",
            "Content-Type": "application/json",
        }
