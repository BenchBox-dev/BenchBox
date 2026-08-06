"""Public pseudonym salt resolution for community publish."""

from __future__ import annotations

import pytest

from benchbox.core.results.anonymization import (
    PUBLIC_PSEUDONYM_SALT_ENV,
    AnonymizationConfig,
    MissingPublicPseudonymSaltError,
    require_public_pseudonym_salt,
    resolve_public_pseudonym_salt,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_resolve_prefers_explicit_over_env() -> None:
    assert resolve_public_pseudonym_salt(explicit="  a  ", environ={PUBLIC_PSEUDONYM_SALT_ENV: "b"}) == "a"


def test_resolve_reads_env() -> None:
    assert resolve_public_pseudonym_salt(environ={PUBLIC_PSEUDONYM_SALT_ENV: "deploy-secret"}) == "deploy-secret"


def test_resolve_empty_is_unset() -> None:
    assert resolve_public_pseudonym_salt(explicit="  ") is None
    assert resolve_public_pseudonym_salt(environ={PUBLIC_PSEUDONYM_SALT_ENV: ""}) is None


def test_require_raises_when_missing() -> None:
    with pytest.raises(MissingPublicPseudonymSaltError, match=PUBLIC_PSEUDONYM_SALT_ENV):
        require_public_pseudonym_salt(environ={})


def test_from_public_environ_require_salt() -> None:
    cfg = AnonymizationConfig.from_public_environ(
        environ={PUBLIC_PSEUDONYM_SALT_ENV: "secret"},
        require_salt=True,
    )
    assert cfg.machine_id_salt == "secret"
    with pytest.raises(MissingPublicPseudonymSaltError):
        AnonymizationConfig.from_public_environ(environ={}, require_salt=True)
