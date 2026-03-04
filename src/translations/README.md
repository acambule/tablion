# Translation preparation

This folder is reserved for compiled Qt translation files (`.qm`) for Tablion.

Planned naming convention:

- `tablion_de_DE.qm`
- `tablion_en_US.qm`

The runtime loader in `src/localization.py` already attempts to load these files.
If files are missing, the app falls back gracefully.

To generate translations later, add `.ts` sources and compile them with `lrelease`.
