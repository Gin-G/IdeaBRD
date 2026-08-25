# IdeaBRD for Android

The board, read and written straight from git.

The app is the same SvelteKit front end the website runs, packaged with
Capacitor and loaded from the APK, plus two native plugins for the things a web
page cannot do for itself: talk to git, and hold a token somewhere the operating
system protects. There is no server involved once it is set up — the board *is*
a clone of your board repo, sitting in the app's own storage.

```
┌──────────────── the app ────────────────┐
│  SvelteKit board (assets/public)        │
│         │  window.Capacitor bridge      │
│  ┌──────┴───────┐   ┌────────────────┐  │
│  │ BoardPlugin  │   │  AuthPlugin    │  │
│  │  JGit        │   │  device flow   │  │
│  │  :core       │   │  Keystore      │  │
│  └──────┬───────┘   └────────┬───────┘  │
└─────────┼────────────────────┼──────────┘
     git over HTTPS      github.com
```

## Layout

| Path    | What                                                                  |
|---------|-----------------------------------------------------------------------|
| `core/` | Plain Kotlin: the IDEA.md format, fractional ranks, slugs, the merge  |
| `app/`  | The Capacitor shell, `BoardPlugin` (JGit) and `AuthPlugin` (sign-in)  |

`core` is where the interesting code is, and it deliberately has no Android in
it: it is a port of `backend/app/ideafile.py`, `rank.py`, `boardrepo.py` and
`ideamerge.py`, so it can be tested on any machine with a JVM. `settings.gradle.kts`
only includes `:app` when an Android SDK is present, so this works anywhere:

```bash
cd android && ./gradlew :core:test
```

### The port is held to the original, byte for byte

Two implementations write IDEA.md now. If they merely *agree on meaning*, the
first time a board is edited on a phone every file gets rewritten and the next
edit is a merge conflict. So `GoldenFileTest` asserts the Kotlin renderer
against fixtures in `fixtures/idea-files/` that the Python renderer also
asserts against. Change the format and both suites fail until both sides match —
which is the point. Regenerate with `cd backend && python -m tests.regenerate_golden`.

## Building it

```bash
cd frontend && npm ci && npm run build && npx cap copy android
cd ../android && ./gradlew :app:assembleDebug
```

`cap copy` puts the built SPA into `app/src/main/assets/public`; both that and
the generated `capacitor.config.json` are build output and are gitignored.
Building `:app` needs an Android SDK with `platforms;android-35` — point
`ANDROID_HOME` at it, or write `sdk.dir=…` into `android/local.properties`.

CI does all of this: `.github/workflows/android-build.yaml` on every change, and
`android-release.yaml` on a `v*` tag, which signs the build and attaches an APK
to a GitHub Release.

## Signing in

An app distributed to people cannot keep a client secret — whatever is in the
APK is in everybody's APK — so the web app's redirect flow is not available
here. It uses GitHub's **device flow** instead: the app shows a short code, you
type it at `github.com/login/device` on whatever device is convenient, and the
app polls until you have.

The token comes back to the device and is stored by `TokenStore`, encrypted
under a key in the Android Keystore, hardware-backed where the device has it.
It never crosses back over the bridge: the board page can ask whether it is
signed in and as whom, and that is all it needs.

Builds need a GitHub OAuth app client id (public by design). Pass it at build
time as `IDEABRD_GITHUB_CLIENT_ID`, or paste one into the app on first run.

## Signing a release

`./scripts/make-signing-key.sh` creates a keystore and prints the four secrets
the release workflow wants (`ANDROID_KEYSTORE_BASE64`, `…_PASSWORD`,
`ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`). Without them the workflow still
produces an installable APK, signed with a key generated for that run — fine for
trying it out, but Android refuses to install a build over one signed with a
different key, so every update means uninstalling first.

Keep the keystore. Losing it means the app can never be updated again, only
republished under a new name.

## Two kinds of repository

The board repo holds every tile. But an idea that has a repository of its own is
recorded there as a **reference** — rank, colour and a link, nothing else —
because its notes and to-dos are tracked in that repository under its own
history, and a second copy could only ever drift from it.

So the app reads that repository too. Opening such a tile offers *Fetch this
idea*, which clones it once; after that it reads and writes that repo's own
`IDEA.md` and works offline like everything else. Fetching is always something
the person asks for, never a side effect of opening a tile — an idea repo can be
large and a phone is often on a metered connection.

A to-do ending in `(#12)` is owned by that issue, exactly as on the server: its
title and whether it is closed come from GitHub rather than from the file, and
ticking the box here closes the issue. Between fetches the last known state is
served from a cache kept outside the checkout, so a board still opens on a
train. Promoting a to-do to an issue and importing a repo's open issues both
work here too, and a held idea can be given a repository — a new one the app
creates, or one you already have. Linking a repo that has no `IDEA.md` means
writing one into it, so that takes a second, explicit yes; nothing is committed
before it.

## Syncing

Every edit is a commit. `sync` is fetch, merge, push, in that order — for the
board repo and for every idea repo this device holds a checkout of.

The merge is the part worth understanding. Git's own three-way merge on an
IDEA.md is close to useless: both sides re-render the whole file, so any real
edit conflicts on nearly every line. `BoardPlugin` intercepts conflicts in an
`IDEA.md`, reads all three versions out of the object database and merges them
by *meaning* — the same `mergeIdeaFiles` the server uses, with the same rules
about who wins. Two people editing different parts of an idea never see a
conflict; neither loses their edit.

A conflict in anything that is not an `IDEA.md` is left exactly as git left it
and reported. This knows how to merge ideas; pretending to know how to merge the
rest of somebody's repository would be worse than saying so.

## What is not here yet

- **Logos.** The app finds an `idea_logo.*` beside an idea but does not display
  or replace it.
- **Live repo data.** Stars, forks and open pull requests are API reads the
  server does; the device shows the repository and its issues, not its
  statistics.
- **Collaboration.** Collaborators, invitations and roles are server features
  that assume an account system. On a git-only board, sharing an idea means
  giving it a repository of its own and adding people there — the API calls that
  have no meaning here say so rather than failing obscurely.
- **On-device verification.** CI compiles and packages the app, and `:core` is
  well covered, but JGit's behaviour on a real device — storage permissions,
  large clones, background time limits — has not been exercised on hardware.
