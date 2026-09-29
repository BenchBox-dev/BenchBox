# Release artifact contract

The release workflow publishes the exact wheel and sdist that the merge-queue
CI run built and tested. It never rebuilds them.

## Producer (ci.yml, `merge_group` runs)

The CI run for a merge-queue commit uploads one artifact:

- Artifact name: `dist-<sha>`, where `<sha>` is the full 40-character
  `head_sha` of the run. The queue fast-forwards `develop` to that commit, so
  the tag commit equals this SHA.
- Contents, at the artifact root: one wheel (`*.whl`), one sdist (`*.tar.gz`),
  and `SHA256SUMS` in `sha256sum` format (`<hex>  <filename>`, one line per
  wheel and sdist, no paths).

## Consumer (release-v2.yml)

1. Find the successful `merge_group` run of `ci.yml` whose `head_sha` is the
   tag commit.
2. Download `dist-<sha>` from that run.
3. Run `sha256sum --check SHA256SUMS`; any mismatch, missing file, or extra
   distribution file fails the release.
4. Attest, test, and publish only those files.
