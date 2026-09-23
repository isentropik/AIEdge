# AIEdge development preview — 2026-09-22

Initial independent fork based on AI-on-the-edge-device 16.1.0 (`a1ccda2`).

Includes polar analog recognition and accounting work, RGBW lighting controls, diagnostics, managed app/SD bundles, optional archival, and an initial UI refresh. The new bootstrap adds network selection, setup mDNS and a pinned HTTPS GitHub download.

This prerelease targets development hardware. The model/geometry is meter-specific. Broad accuracy, sustained performance, complete mobile rendering and automatic rollback are not established. The initial PC-server loader reached Wi-Fi but failed to download; the GitHub replacement requires separate device validation.

Use matched installer files, application package and checksums. Do not use the upstream web installer or flash a ZIP as a binary. Read [installation](docs/INSTALLATION.md), [recovery](docs/RECOVERY.md) and [status](docs/STATUS.md).
