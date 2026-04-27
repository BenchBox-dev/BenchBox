"""Shared Azure credential + access-token helper for Spark-on-Azure adapters.

Fabric Spark and Synapse Spark adapters both:
  * lazily create a ``DefaultAzureCredential`` (honoring tenant_id);
  * fetch an access token for a scope-specific audience;
  * refresh the token 5 minutes before expiry;
  * expose ``_get_headers`` for authenticated HTTP requests.

Only the audience URL differs:

  * Fabric:  ``https://api.fabric.microsoft.com/.default``
  * Synapse: ``https://dev.azuresynapse.net/.default``

Consolidating into a stateful helper keeps the adapters free of
credential bookkeeping while preserving the exact refresh/scope
semantics each adapter had before.

Import is lazy: the caller passes the credential class in, so this
module does not import ``azure.identity``. Adapters that already
maintain an optional ``DefaultAzureCredential`` import under a
try/except keep that import as the single point of availability
signalling (``AZURE_IDENTITY_AVAILABLE``), and forward the class here.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root.
"""

from __future__ import annotations

import time
from typing import Any


class AzureTokenProvider:
    """Azure credential + token cache, parameterized by audience scope.

    Designed for use as a per-adapter instance - not a singleton -
    because token scope and tenant_id belong to a specific adapter's
    session and should not cross-contaminate.

    The 5-minute refresh buffer matches what the adapters did before
    consolidation; do not shorten it without thinking about clock skew
    between the GH runner and Azure AD.
    """

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
        """Return a lazily-created credential instance."""
        if self._credential is None:
            kwargs: dict[str, Any] = {}
            if self._tenant_id:
                kwargs["additionally_allowed_tenants"] = ["*"]
            self._credential = self._credential_class(**kwargs)
        return self._credential

    def access_token(self) -> str:
        """Return a valid access token, refreshing before expiry."""
        now = time.time()
        if self._access_token is None or now >= self._token_expires_at - self._REFRESH_BUFFER_SECONDS:
            token = self.credential().get_token(self._scope)
            self._access_token = token.token
            self._token_expires_at = token.expires_on
        return self._access_token

    def auth_headers(self) -> dict[str, str]:
        """Return HTTP headers with Bearer auth and JSON content-type."""
        return {
            "Authorization": f"Bearer {self.access_token()}",
            "Content-Type": "application/json",
        }
