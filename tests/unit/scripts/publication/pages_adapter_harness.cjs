/**
 * Test harness for scripts/publication/pages.cjs.
 *
 * Simulates actions/github-script environment (Octokit, Actions core, context)
 * to test Pages adapter behavior, validation, token masking, and error sanitization.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const pages = require(path.resolve(__dirname, '../../../../scripts/publication/pages.cjs'));

function parseStdin() {
  try {
    const input = fs.readFileSync(0, 'utf-8');
    return input.trim() ? JSON.parse(input) : {};
  } catch (err) {
    console.error('Failed to parse stdin as JSON:', err);
    process.exit(2);
  }
}

async function run() {
  const payload = parseStdin();
  const action = payload.action || 'create';
  const mockConfig = payload.mock || {};
  const effect = payload.effect || {};
  const options = payload.options || {};

  const maskedSecrets = [];
  const recordedRequests = [];

  const mockCore = {
    async getIDToken(audience) {
      if (mockConfig.token_error) {
        throw new Error(mockConfig.token_error);
      }
      return mockConfig.token || 'mock-oidc-jwt-token-xyz123';
    },
    setSecret(secret) {
      maskedSecrets.push(secret);
    },
    info() {},
    warning() {},
    error() {},
  };

  const mockGithub = {
    async request(route, params) {
      recordedRequests.push({ route, params });

      if (route.startsWith('POST /repos/{owner}/{repo}/pages/deployments/{deployment_id}/cancel')) {
        if (mockConfig.cancel_error) {
          const err = new Error(mockConfig.cancel_error.message || 'Cancel failed');
          err.status = mockConfig.cancel_error.status || 500;
          throw err;
        }
        return {
          status: 200,
          data: mockConfig.cancel_response || { id: params.deployment_id, status: 'CANCELED' },
        };
      }

      if (route.startsWith('GET /repos/{owner}/{repo}/pages/deployments/')) {
        if (mockConfig.get_error) {
          const err = new Error(mockConfig.get_error.message || 'Status failed');
          err.status = mockConfig.get_error.status || 404;
          throw err;
        }
        return {
          status: 200,
          data: mockConfig.get_response || {
            id: params.deployment_id || 'mock-deploy-1',
            status: 'SUCCESS',
            page_url: 'https://example.github.io/site/',
          },
        };
      }

      if (route.startsWith('POST /repos/{owner}/{repo}/pages/deployments')) {
        if (mockConfig.post_error) {
          const err = new Error(mockConfig.post_error.message || 'POST failed');
          err.status = mockConfig.post_error.status || 422;
          throw err;
        }
        return {
          status: 201,
          data: mockConfig.post_response || {
            id: 'mock-deploy-123',
            status_url: 'https://api.github.com/repos/BenchBox-dev/BenchBox/pages/deployments/mock-deploy-123',
            page_url: 'https://benchbox.dev/',
            pages_build_version: params.pages_build_version,
            created_at: new Date().toISOString(),
          },
        };
      }

      throw new Error(`Unhandled mock route: ${route}`);
    },
  };

  const mockContext = {
    repo: {
      owner: options.owner || effect.owner || 'BenchBox-dev',
      repo: options.repo || effect.repo || 'BenchBox',
    },
  };

  try {
    let result;
    if (action === 'create') {
      result = await pages.createDeployment({
        github: mockGithub,
        core: mockCore,
        context: mockContext,
        effect,
        options,
      });
    } else if (action === 'status') {
      result = await pages.getDeploymentStatus({
        github: mockGithub,
        context: mockContext,
        options,
      });
    } else if (action === 'cancel') {
      result = await pages.cancelDeployment({
        github: mockGithub,
        context: mockContext,
        options,
      });
    } else if (action === 'validate') {
      result = pages.validateCreateInputs(effect);
    } else if (action === 'classify') {
      result = { status: payload.status, classification: pages.classifyDeploymentStatus(payload.status) };
    } else {
      throw new Error(`Unknown action: ${action}`);
    }

    process.stdout.write(
      JSON.stringify({
        success: true,
        result,
        masked_secrets: maskedSecrets,
        recorded_requests: recordedRequests,
      })
    );
  } catch (err) {
    process.stdout.write(
      JSON.stringify({
        success: false,
        error: {
          name: err.name,
          message: err.message,
          code: err.code || null,
          stage: err.stage || null,
          status: err.status || null,
          cause_message: err.cause?.message || null,
        },
        masked_secrets: maskedSecrets,
        recorded_requests: recordedRequests,
      })
    );
  }
}

run();
