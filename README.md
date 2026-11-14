# CraftedSignal

Official downloads for the [CraftedSignal](https://craftedsignal.com) detection engineering platform, available for security teams and managed security service providers (MSSPs).

[Download the latest release](https://github.com/CraftedSignal/releases/releases/latest) · [Browse versions and release notes](https://github.com/CraftedSignal/releases/releases)

## Downloads

Choose the archive for your operating system and processor. Replace `VERSION` in the examples with the release number, such as `1.2.3`.

| Operating system | Processor | Download |
| --- | --- | --- |
| Linux | x86-64 (amd64) | `craftedsignal_VERSION_linux_amd64.tar.gz` |
| Linux | ARM64 | `craftedsignal_VERSION_linux_arm64.tar.gz` |
| macOS | Apple Silicon (ARM64) | `craftedsignal_VERSION_darwin_arm64.tar.gz` |
| Windows | x86-64 (amd64) | `craftedsignal_VERSION_windows_amd64.zip` |

Each binary archive includes the executable, installation instructions in `README.md`, the version's changes in `CHANGELOG.md`, and its `LICENSE`.

Extract the archive and follow the deployment instructions supplied with your subscription. Run `./craftedsignal --help` on Linux or macOS, or `.\craftedsignal.exe --help` on Windows, to view command-line options.

## Verify your download

Download `checksums.txt` and verify the SHA256 hash before extracting a binary archive or importing a container image. On Linux, verify the downloaded files from the same directory:

```sh
sha256sum --check --ignore-missing checksums.txt
```

On macOS:

```sh
shasum -a 256 craftedsignal_VERSION_darwin_arm64.tar.gz
```

On Windows, use PowerShell:

```powershell
Get-FileHash .\craftedsignal_VERSION_windows_amd64.zip -Algorithm SHA256
```

Compare the result with the matching filename in `checksums.txt`. Continue only when the hashes match.

## Container images

Images support both `linux/amd64` and `linux/arm64`. Pull a specific version; Docker selects the correct platform automatically:

```sh
docker pull ghcr.io/craftedsignal/releases:VERSION
```

Use an explicit version tag when deploying. Follow your deployment guide for configuration, persistent storage and license setup.

For offline or private-registry installations, download `craftedsignal_VERSION_linux_multiarch.oci.tar`, verify its checksum, and copy both architectures into your own registry with Skopeo:

```sh
skopeo copy --all --preserve-digests oci-archive:craftedsignal_VERSION_linux_multiarch.oci.tar docker://YOUR_REGISTRY/craftedsignal:VERSION
```

## Software inventories

Each release includes a JSON software bill of materials (SBOM) for every binary archive and each Linux container platform:

- Binary archives: the archive filename followed by `.sbom.json`.
- Container images: `craftedsignal_VERSION_linux_amd64.oci.sbom.json` and `craftedsignal_VERSION_linux_arm64.oci.sbom.json`.

Use these inventories to review included components and their reported licenses. Their SHA256 hashes are included in `checksums.txt`.

## What's new

Read the [release notes](https://github.com/CraftedSignal/releases/releases) for high-level features, fixes, performance improvements and breaking changes. The downloaded `README.md` and `CHANGELOG.md` include the changes for that version.

## Licensing and support

CraftedSignal is commercial software. An applicable CraftedSignal license or subscription is required; a public download does not grant a right to resell, redistribute or embed the product in another commercial offering.

Licensed MSSPs may operate CraftedSignal for client security services and charge for those services. Resale, redistribution, embedding in another commercial product and white-labeling require a separate written agreement. Preserve CraftedSignal branding and identify client-facing access and substantive reports as `Powered by CraftedSignal (https://craftedsignal.com)`. Normal API and SIEM integrations remain permitted within authorized use.

See the [commercial license](LICENSE). Contact [CraftedSignal](https://craftedsignal.com) for MSSP usage, deployment guidance, licensing and support. The license supplied with your version and your commercial agreement govern permitted use. Third-party components retain their own licenses.
