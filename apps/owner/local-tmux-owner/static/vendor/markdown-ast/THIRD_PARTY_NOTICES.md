# Faryo AST Markdown engine notices

The minified browser bundle in this directory is reproducibly built from
`tools/markdown-engine` and its committed `package-lock.json`.

It includes KaTeX, the unified/micromark/mdast GFM and math parsing packages,
and Shiki with a JavaScript regex engine and locally split language grammars.
Exact bundled package versions and complete license texts are in
`THIRD_PARTY_LICENSES.txt`; `highlight/manifest.json` lists every generated
highlighter entry and lazy chunk shipped in a release.

The `mathCompatibility` and `cjkFriendlyStrong` extensions are adapted from
DeepSeek Harness commit
`47f943859bef60e4160492346772ded9b24f765a`, Copyright (c) 2026 DeepSeek,
under the MIT License. No DeepSeek branding or product assets are included.
