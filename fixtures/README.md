# Shared fixtures

Files that two implementations have to agree on, byte for byte.

`idea-files/` holds rendered `IDEA.md` files. Both renderers are asserted
against them: `backend/tests/test_golden_files.py` (Python) and
`android/core/src/test/kotlin/…/GoldenFileTest.kt` (Kotlin). They are the only
check that the phone and the server write the *same* file rather than two files
that happen to parse the same — which matters the moment a board is edited on
one and opened on the other, because a whitespace difference is a diff on every
idea and a merge conflict waiting for the next edit.

Regenerate them (after a deliberate format change) with:

```bash
cd backend && python -m tests.regenerate_golden
```

...and expect both suites to fail until the other side is updated to match. That
failure is the point.
