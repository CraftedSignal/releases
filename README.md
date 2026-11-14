# CraftedSignal Releases

Official binary releases and changelogs for the [CraftedSignal](https://craftedsignal.com) platform.

## Installation

Download an archive from the [Releases](https://github.com/CraftedSignal/releases/releases) page. Each release contains twelve files:

- Four binary archives: Linux amd64/arm64, macOS arm64, and Windows amd64.
- Four matching binary-archive SBOMs.
- `craftedsignal_VERSION_linux_multiarch.oci.tar`, containing both Linux container platforms and their original image index.
- Two container SBOMs: `craftedsignal_VERSION_linux_amd64.oci.sbom.json` and `craftedsignal_VERSION_linux_arm64.oci.sbom.json`.
- `checksums.txt`, containing SHA256 hashes for all eleven payload files.

Verify each downloaded archive and SBOM against `checksums.txt` before installing. Binary archives include customer installation instructions and high-level changes in `README.md` and `CHANGELOG.md`. The same changes appear in the GitHub release notes; this repository README describes the release process rather than a particular version.

Pull the approved container image with `docker pull ghcr.io/craftedsignal/releases:VERSION` (replace `VERSION` with the release number without its `v` prefix). Docker selects `linux/amd64` or `linux/arm64` automatically. For offline transfers, import the verified OCI archive into your registry:

```sh
skopeo copy --all oci-archive:craftedsignal_VERSION_linux_multiarch.oci.tar docker://YOUR_REGISTRY/craftedsignal:VERSION
```

Images are promoted from the scanned private build without rebuilding. Only immutable version tags are published; there is no `latest` alias that an older approval could move backwards.

## Release approval

A push to platform `main` automatically evaluates semantic versioning. A qualifying release builds the binaries and images, scans both Linux container architectures, and prepares a draft here by copying the verified archives, SBOMs, checksums and release notes. Preparation verifies every GitHub SHA256 digest, the complete checksum manifest and the complete OCI image graph before automatically requesting approval.

The [Approve Public Release workflow](https://github.com/CraftedSignal/releases/actions/workflows/publish-release.yml) summarizes the immutable request and pauses at the `public-release` environment. Only **hazcod** can approve publication. Admin bypass is disabled; self-review remains allowed for the sole maintainer. No one needs to manually start a promotion workflow.

To approve a release:

1. Open the pending workflow and read its validation summary, including the source commit, notes SHA256 and every asset ID/digest.
2. Inspect the prepared draft on the [Releases page](https://github.com/CraftedSignal/releases/releases), including its notes and SBOMs. Drafts are visible only to authorized maintainers.
3. Select **Review deployments** and approve `public-release`, or reject/cancel to leave that version unpublished.

Only the approved job receives Contents and Packages write permissions. It downloads all draft assets, rechecks their hashes, checksum coverage and OCI integrity, and promotes the exact multi-platform index to GHCR. It checks the pushed index digest and anonymous pull access, then compares the exact title, notes, prerelease flag, release ID and asset IDs with the approved manifest immediately before publishing the draft. Detected changes or an incomplete draft stop publication. Private releases can continue while a public approval waits. Stable publication leaves latest-release selection to GitHub’s creation-date and semantic-version ordering so approvals may finish out of order; prereleases never become latest.

GHCR setup is one-time: GitHub creates new container packages private, so the `releases` package must be made public in its package settings. Its linked repository must be `CraftedSignal/releases` and this workflow must have write access. The publisher leaves the draft unpublished with a clear error until anonymous access works. Normal releases require only the approval above; no cloud credentials or manually started promotion are needed.

Retries preserve the same draft and do not overwrite assets or notes. A retry of a completed, matching publication makes no changes. A rejected/canceled run leaves its draft unpublished; re-running preparation requests a fresh approval. If a draft was edited, resolve the mismatch against the private source or prepare a new private version before requesting approval again.

The approval environment is managed in `CraftedSignal/github-config` and restricts deployment to protected branches. The workflow also requires `main` and verifies that the live environment still requires hazcod with admin bypass disabled. No private repository credential is stored here. Administrators can still manage releases directly in GitHub; these controls govern automated publication.

GitHub's draft publish API has no documented atomic compare-and-publish operation. Do not edit a draft during publication: the final identity check occurs immediately before the publish request, and an edit in that short interval can only be detected afterward. Repository writers remain trusted. If workflow files on `main` change while a pinned draft waits, GitHub can reject publication with the restricted token; prepare a fresh private version/draft and approve the new request instead of broadening token permissions.

## Validation

Pull requests run the offline release tests, approval workflow policy checks and actionlint. To run them locally:

```sh
python3 -m unittest discover -s .github/tests -p '*_test.py'
ruby .github/tests/workflow_policy_test.rb
actionlint
```

The asset contract and GitHub API helper are shared verbatim with platform. The tests use synthetic files and a simulated GitHub API, never real publication.

## License

The `LICENSE` included in each downloaded binary archive contains that version's platform terms. Third-party components retain their own licenses and are identified in the SBOMs. See [craftedsignal.com](https://craftedsignal.com) for licensing enquiries.
