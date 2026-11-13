# CraftedSignal Releases

Official binary releases and changelogs for the [CraftedSignal](https://craftedsignal.com) platform.

## Installation

Download a binary archive from the [Releases](https://github.com/CraftedSignal/releases/releases) page. Each release includes Linux amd64/arm64, macOS arm64 and Windows amd64 archives, an SBOM for each archive, and `checksums.txt` containing their SHA256 hashes.

Verify a downloaded archive and its SBOM against `checksums.txt` before installing. Container images are distributed separately through CraftedSignal's Artifact Registry; this repository does not publish a public GHCR image.

## Release approval

A successful private platform release automatically prepares a draft here, copying its existing binary archives, SBOMs, checksums and release notes without rebuilding them. Preparation verifies every GitHub SHA256 digest and the complete checksum manifest before automatically requesting approval.

The [Approve Public Release workflow](https://github.com/CraftedSignal/releases/actions/workflows/publish-release.yml) summarizes the immutable request and pauses at the `public-release` environment. Only **hazcod** can approve publication. Admin bypass is disabled; self-review remains allowed for the sole maintainer. No one needs to manually start a promotion workflow.

To approve a release:

1. Open the pending workflow and read its validation summary, including the source commit, notes SHA256 and every asset ID/digest.
2. Inspect the prepared draft on the [Releases page](https://github.com/CraftedSignal/releases/releases), including its notes and SBOMs. Drafts are visible only to authorized maintainers.
3. Select **Review deployments** and approve `public-release`, or reject/cancel to leave that version unpublished.

Only the approved job receives a Contents write token. It downloads all draft assets, rechecks their hashes and checksum coverage, and compares the exact title, notes, prerelease flag, release ID and asset IDs with the approved manifest immediately before publication. Detected changes or an incomplete draft stop publication. Private releases can continue while a public approval waits. Stable publication leaves latest-release selection to GitHub’s creation-date and semantic-version ordering so approvals may finish out of order; prereleases never become latest.

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

CraftedSignal is commercial software. See [craftedsignal.com](https://craftedsignal.com) for licensing details.
