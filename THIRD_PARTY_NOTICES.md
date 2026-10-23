# Third-party notices

The root MIT license covers this project's code and original documentation.
It does not replace licenses of bundled fonts, dependencies or user materials.

## Source Han Serif

`assets/fonts/SourceHanSerifSC-*.otf` are unmodified Source Han Serif 2.003 fonts
from Adobe. Copyright 2017–2022 Adobe, reserved font name “Source”. They use
SIL Open Font License 1.1. The complete upstream notice is preserved in
[`assets/fonts/LICENSE.txt`](assets/fonts/LICENSE.txt).

Upstream: https://github.com/adobe-fonts/source-han-serif

## Verovio

Music engraving is powered by Verovio, developed by the Verovio contributors
and RISM Digital Center. It is installed separately through the Python lock
and licensed under LGPLv3. This repository does not vendor or modify its
library source or binary.

- https://www.verovio.org/
- https://github.com/rism-digital/verovio
- https://book.verovio.org/introduction/licensing.html

Generated score SVGs may contain music-font glyphs including Leipzig. These
font resources retain their upstream OFL terms; consult the corresponding
notices when distributing embedded glyphs:
https://github.com/rism-digital/verovio/blob/develop/fonts/README.md

## Runtime dependencies

Python dependencies retain their upstream licenses and are installed from
PyPI, not redistributed as a bundled runtime. Node.js, FFmpeg and Chromium
are external programs. An FFmpeg build's license depends on its enabled
components, including libx265.

## Music and project data

No original score PDF, third-party transcription, recording, finished video
or work-specific reference dataset is distributed here. Users supply their
own materials; the project MIT license does not grant rights to them.
Tests use small synthetic examples.
