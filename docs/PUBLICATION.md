# Publication integrity

The release manifest records the UTC generation time, payload totals, and SHA-256 digest and byte count for every payload file. The manifest is carried alongside its payload.

From a clean, newly checked out repository, verify the release before installing dependencies or generating files:

```powershell
python -B -m scripts.publication_manifest --verify --strict
```

Regenerate the manifest after editing the payload. The copy command can write a verified release to a new directory.

```powershell
python -m scripts.publication_manifest
python -m scripts.release_copy --destination ../AgentForge-Release
```

Review staged filenames and content before publishing. Keep runtime state, browser data, dependency caches, local environment files, and backup archives outside the release payload. Coordinate intentional release changes with the [verification report](FINAL_VERIFICATION_REPORT.md).
