# Fonts used by the landing page

Self-hosted so a visit does not send the visitor's address to a third-party font host. Latin subset only
(Indonesian and English need nothing more). Both families are licensed under the SIL Open Font License 1.1.

| File | Family | Source |
|---|---|---|
| `newsreader-display.woff2`, `newsreader-display-italic.woff2` | Newsreader, optical size fixed at 72 (display cut), weight axis only | Google Fonts, `family=Newsreader:ital,opsz,wght@0,72,400..600;1,72,400..500` |
| `inter-latin.woff2` | Inter, variable weight 400 to 700 | Google Fonts, `family=Inter:wght@400..700` |

The app itself declares `Inter` in `--font-sans` but does not load it. The landing page registers these files
under the names `AIDSS Display` and `AIDSS Sans`, so nothing outside the landing page changes typeface.
