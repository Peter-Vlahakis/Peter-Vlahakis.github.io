# Font provenance

Both families are self-hosted and licensed under the SIL Open Font License 1.1.
The license texts shipped with the packages are kept beside the fonts.
Downloaded 2026-10-09 from Fontsource (served by jsDelivr from the npm packages).

| File | Family | Source URL |
|---|---|---|
| `inter-latin-wght-normal.woff2` | Inter, variable weight 100-900, Latin subset | https://cdn.jsdelivr.net/npm/@fontsource-variable/inter@5.3.0/files/inter-latin-wght-normal.woff2 |
| `inter-greek-wght-normal.woff2` | Inter, variable weight 100-900, Greek subset | https://cdn.jsdelivr.net/npm/@fontsource-variable/inter@5.3.0/files/inter-greek-wght-normal.woff2 |
| `ibm-plex-mono-latin-400-normal.woff2` | IBM Plex Mono 400, Latin subset | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-mono@5.3.0/files/ibm-plex-mono-latin-400-normal.woff2 |
| `ibm-plex-mono-latin-500-normal.woff2` | IBM Plex Mono 500, Latin subset | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-mono@5.3.0/files/ibm-plex-mono-latin-500-normal.woff2 |
| `LICENSE-inter.txt` | Inter license (OFL-1.1) | https://cdn.jsdelivr.net/npm/@fontsource-variable/inter@5.3.0/LICENSE |
| `LICENSE-ibm-plex-mono.txt` | IBM Plex Mono license (OFL-1.1) | https://cdn.jsdelivr.net/npm/@fontsource/ibm-plex-mono@5.3.0/LICENSE |

Upstream projects: Inter by The Inter Project Authors (https://github.com/rsms/inter);
IBM Plex by IBM Corp. (https://github.com/IBM/plex).

Notes:

- The Greek subset is needed because the copy contains "ΘX". The browser fetches it only on pages that show Greek text.
- IBM Plex Mono has no Greek subset. Keep Greek characters out of mono-styled text (labels, spec keys, chips).
- The `@font-face` rules and the `unicode-range` values copied from the Fontsource CSS are in `css/tokens.css`.
