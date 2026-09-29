# Bundled fonts

Subtitle presets and hooks refer to these files by name (`Montserrat-Black`),
so each file name must equal the font's PostScript name. All are licensed
under the SIL Open Font License 1.1; each file carries its copyright and
license notice in its metadata.

| File | Source |
|------|--------|
| `Montserrat-Black.ttf`, `Montserrat-ExtraBold.ttf` | Static TTFs from [JulietaUla/Montserrat](https://github.com/JulietaUla/Montserrat) `fonts/ttf/` at commit `cc8daf2`, the upstream commit Google Fonts pins. License: [OFL-Montserrat.txt](OFL-Montserrat.txt) |
| `Anton-Regular.ttf`, `Bangers-Regular.ttf`, `NotoSerif-Bold.ttf`, `Poppins-Black.ttf`, `Poppins-Medium.ttf` | Google Fonts families |

`NotoColorEmoji.ttf` is not tracked: it is downloaded at render time only when
`CLIPPYME_RUNTIME_FONT_DOWNLOAD=1`.

When adding or replacing a font, download the font file itself, not the web
page that links to it, and run `pytest tests/repository/test_font_assets.py`.
The test rejects files that are not fonts, names that do not match the
PostScript name, and wrong weights for the fonts presets use.
