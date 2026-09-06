/**
 * Minimal GitHub Pages Deployment Adapter (Slice A feasibility adapter).
 *
 * Runs inside actions/github-script or standalone Node test harness.
 * Interacts with the GitHub Pages REST API:
 * - create: POST /repos/{owner}/{repo}/pages/deployments
 * - status: GET /repos/{owner}/{repo}/pages/deployments/{id}
 * - cancel: POST /repos/{owner}/{repo}/pages/deployments/{id}/cancel
 *
 * Enforces strict input validation, OIDC masking, allowlisted response fields,
 * and secret redaction on error boundaries.
 */

'use strict';

const SHA_HEX_REGEX = /^[0-9a-f]{40}$/i;

class AdapterError extends Error {
  constructor(message, { code = 'ERR_ADAPTER', stage = 'pre_send', status = null, cause = null } = {}) {
    super(message);
    this.name = 'AdapterError';
    this.code = code;
    this.stage = stage;
    this.status = status;
    if (cause) {
      this.cause = cause;
    }
  }
}

function redactText(text, secret) {
  if (!text || typeof text !== 'string' || !secret || typeof secret !== 'string') {
    return text;
  }
  return text.split(secret).join('[REDACTED]');
}

function validateCreateInputs(inputs) {
  if (!inputs || typeof inputs !== 'object') {
    throw new AdapterError('Inputs must be a non-null object', {
      code: 'ERR_VALIDATION',
      stage: 'pre_send',
    });
  }

  const { owner, repo, artifact_id, pages_build_version } = inputs;

  if (!owner || typeof owner !== 'string' || owner.trim() === '') {
    throw new AdapterError('owner must be a non-empty string', {
      code: 'ERR_VALIDATION',
      stage: 'pre_send',
    });
  }

  if (!repo || typeof repo !== 'string' || repo.trim() === '') {
    throw new AdapterError('repo must be a non-empty string', {
      code: 'ERR_VALIDATION',
      stage: 'pre_send',
    });
  }

  const artifactIdIsValid =
    (typeof artifact_id === 'number' && Number.isSafeInteger(artifact_id)) ||
    (typeof artifact_id === 'string' && /^\d+$/.test(artifact_id));
  const numericArtifactId = artifactIdIsValid ? Number(artifact_id) : Number.NaN;
  if (!Number.isSafeInteger(numericArtifactId) || numericArtifactId <= 0) {
    throw new AdapterError(`artifact_id must be a positive integer, got: ${artifact_id}`, {
      code: 'ERR_VALIDATION',
      stage: 'pre_send',
    });
  }

  if (
    !pages_build_version ||
    typeof pages_build_version !== 'string' ||
    !SHA_HEX_REGEX.test(pages_build_version)
  ) {
    throw new AdapterError(
      `pages_build_version must be a 40-character hexadecimal commit SHA, got: ${pages_build_version}`,
      {
        code: 'ERR_VALIDATION',
        stage: 'pre_send',
      }
    );
  }

  return {
    owner: owner.trim(),
    repo: repo.trim(),
    artifact_id: numericArtifactId,
    pages_build_version: pages_build_version.toLowerCase().trim(),
  };
}

async function acquireOidcToken(core, audience) {
  if (!core || typeof core.getIDToken !== 'function') {
    throw new AdapterError('Actions core runtime does not support getIDToken()', {
      code: 'ERR_OIDC_UNSUPPORTED',
      stage: 'pre_send',
    });
  }

  let token;
  try {
    token = await (audience ? core.getIDToken(audience) : core.getIDToken());
  } catch (err) {
    throw new AdapterError(`Failed to acquire OIDC token: ${err.message}`, {
      code: 'ERR_OIDC_DENIAL',
      stage: 'pre_send',
      cause: err,
    });
  }

  if (!token || typeof token !== 'string' || token.trim() === '') {
    throw new AdapterError('OIDC token acquisition returned empty token', {
      code: 'ERR_OIDC_EMPTY',
      stage: 'pre_send',
    });
  }

  if (typeof core.setSecret === 'function') {
    core.setSecret(token);
  }

  return token;
}

function sanitizeCreateResponse(data, defaultBuildVersion) {
  if (!data || typeof data !== 'object') {
    return {
      id: null,
      status_url: null,
      page_url: null,
      pages_build_version: null,
      created_at: null,
    };
  }

  return {
    id: data.id != null ? String(data.id) : null,
    status_url: data.status_url ? String(data.status_url) : null,
    page_url: data.page_url ? String(data.page_url) : null,
    pages_build_version: data.pages_build_version
      ? String(data.pages_build_version)
      : null,
    created_at: data.created_at ? String(data.created_at) : null,
  };
}

function sanitizeStatusResponse(data) {
  if (!data || typeof data !== 'object') {
    return {
      id: null,
      status: 'UNKNOWN',
      page_url: null,
    };
  }

  return {
    id: data.id != null ? String(data.id) : null,
    status: data.status ? String(data.status).toUpperCase() : 'UNKNOWN',
    page_url: data.page_url ? String(data.page_url) : null,
    created_at: data.created_at ? String(data.created_at) : null,
    updated_at: data.updated_at ? String(data.updated_at) : null,
  };
}

async function createDeployment({ github, core, context, effect, options = {} }) {
  const mergedInputs = {
    owner: effect?.owner !== undefined ? effect.owner : (options.owner || context?.repo?.owner),
    repo: effect?.repo !== undefined ? effect.repo : (options.repo || context?.repo?.repo),
    artifact_id: effect?.artifact_id !== undefined ? effect.artifact_id : options.artifact_id,
    pages_build_version:
      effect?.pages_build_version !== undefined
        ? effect.pages_build_version
        : options.pages_build_version,
  };

  const validated = validateCreateInputs(mergedInputs);
  const token = await acquireOidcToken(core, options.audience);

  let response;
  try {
    response = await github.request('POST /repos/{owner}/{repo}/pages/deployments', {
      owner: validated.owner,
      repo: validated.repo,
      artifact_id: validated.artifact_id,
      pages_build_version: validated.pages_build_version,
      oidc_token: token,
      headers: {
        accept: 'application/vnd.github+json',
      },
    });
  } catch (err) {
    const rawMsg = err.message || 'Unknown provider error';
    const cleanMsg = redactText(rawMsg, token);
    throw new AdapterError(`Pages deployment create request failed: ${cleanMsg}`, {
      code: 'ERR_PROVIDER_POST',
      stage: 'post_send',
      status: err.status || null,
    });
  }

  return sanitizeCreateResponse(response.data, validated.pages_build_version);
}

async function getDeploymentStatus({ github, context, options = {} }) {
  const owner = options.owner || context?.repo?.owner;
  const repo = options.repo || context?.repo?.repo;
  const deploymentId = options.deployment_id || options.id;

  if (!owner || !repo) {
    throw new AdapterError('owner and repo are required for status query', {
      code: 'ERR_VALIDATION',
      stage: 'pre_send',
    });
  }

  if (!deploymentId) {
    throw new AdapterError('deployment_id is required for status query', {
      code: 'ERR_VALIDATION',
      stage: 'pre_send',
    });
  }

  try {
    const response = await github.request('GET /repos/{owner}/{repo}/pages/deployments/{deployment_id}', {
      owner,
      repo,
      deployment_id: deploymentId,
      headers: {
        accept: 'application/vnd.github+json',
      },
    });
    return sanitizeStatusResponse(response.data);
  } catch (err) {
    throw new AdapterError(`Pages deployment status query failed: ${err.message}`, {
      code: 'ERR_PROVIDER_GET',
      stage: 'post_send',
      status: err.status || null,
      cause: err,
    });
  }
}

async function cancelDeployment({ github, context, options = {} }) {
  const owner = options.owner || context?.repo?.owner;
  const repo = options.repo || context?.repo?.repo;
  const deploymentId = options.deployment_id || options.id;

  if (!owner || !repo || !deploymentId) {
    throw new AdapterError('owner, repo, and deployment_id are required for cancellation', {
      code: 'ERR_VALIDATION',
      stage: 'pre_send',
    });
  }

  try {
    const response = await github.request(
      'POST /repos/{owner}/{repo}/pages/deployments/{deployment_id}/cancel',
      {
        owner,
        repo,
        deployment_id: deploymentId,
        headers: {
          accept: 'application/vnd.github+json',
        },
      }
    );
    return sanitizeStatusResponse(response.data);
  } catch (err) {
    throw new AdapterError(`Pages deployment cancel request failed: ${err.message}`, {
      code: 'ERR_PROVIDER_CANCEL',
      stage: 'post_send',
      status: err.status || null,
      cause: err,
    });
  }
}

module.exports = {
  AdapterError,
  createDeployment,
  getDeploymentStatus,
  cancelDeployment,
  validateCreateInputs,
  acquireOidcToken,
  sanitizeCreateResponse,
  sanitizeStatusResponse,
  redactText,
};
