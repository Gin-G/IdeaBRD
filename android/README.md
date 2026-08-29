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

There are two ways in, and they end in the same place: a GitHub token held by
`TokenStore`, encrypted under a key in the Android Keystore, hardware-backed
where the device has it. The token never crosses back over the bridge — the
board page can ask whether it is signed in and as whom, and that is all it
needs. Git and the REST API both take it as-is, so nothing downstream cares
which route produced it.

**An access token you made yourself.** Paste a personal access token into the
app. A classic token needs the `repo` scope (add `read:org` to create the board
repo under an organisation); the app checks for `repo` up front rather than
letting a clone fail later with a git error that explains nothing. A
fine-grained token works too, but doesn't declare its scopes, so it is taken on
trust — give it Contents and Issues read/write on the repositories concerned.

This route registers nothing anywhere. It is the answer when you don't want an
OAuth app in the picture at all: no client id, no consent screen, and no third
account involved in somebody else's sign-in.

**The device flow.** The app shows a short code, you type it at
`github.com/login/device` on whatever device is convenient, and the app polls
until you have. This is what an app distributed to people has instead of the
web app's redirect flow, which needs a client secret — and whatever is in the
APK is in everybody's APK.

The device flow needs a registered client id, which is public by design and can
be compiled in with `IDEABRD_GITHUB_CLIENT_ID` or pasted into the app. Either

- an **OAuth app** (Settings → Developer settings → OAuth Apps → New OAuth App)
  with **Enable Device Flow** ticked. Its client id looks like `Ov23li…`, or
  `Iv1.…` if it is old. This is what the code expects: the scopes it asks for
  (`repo read:user user:email read:org`) are OAuth scopes.
- or a **GitHub App**, whose client id looks like `Iv23li…`. Device flow works,
  but GitHub Apps ignore scopes — access comes from the app's declared
  permissions and from being installed on each account or repository — so the
  `owners`/`createRepoForIdea` paths would need rethinking before this is a
  real option.

Whichever it is, some account owns it, and its name appears on the consent
screen every person sees. Registering it under an organisation rather than a
personal account is the difference between "authorise IdeaBRD, owned by *a
person*" and "owned by *the org*". Nothing about owning it grants access to the
owner's account: each person's token is minted for them and stays on their
device.

## Signing a release

`./scripts/make-signing-key.sh` creates a keystore and prints the four secrets
the release workflow wants (`ANDROID_KEYSTORE_BASE64`, `…_PASSWORD`,
`ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`). Without them the workflow still
produces an installable APK, signed with a key generated for that run — fine for
trying it out, but Android refuses to install a build over one signed with a
different key, so every update means uninstalling first.

Those four secrets are set on this repository, so releases from v0.2.0 on share
one signing identity and update in place. v0.1.0 predates the key and was signed
with a throwaway one, so it has to be uninstalled rather than upgraded.

Keep the keystore. It lives outside the repository — `.gitignore` covers `*.jks`
— and losing it means the app can never be updated again, only republished under
a new name.

## Running it without a phone

An emulator is enough to catch the things that only break once the web app is
inside a WebView, and it needs no hardware:

```sh
sdkmanager "emulator" "system-images;android-34;google_apis;x86_64"
avdmanager create avd -n ideabrd -k "system-images;android-34;google_apis;x86_64" -d pixel_6
emulator -avd ideabrd -no-window -no-audio -gpu swiftshader_indirect &
adb wait-for-device
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n net.nickknows.ideabrd/.MainActivity
adb exec-out screencap -p > screen.png
```

`adb logcat | grep Capacitor` is where the web layer's console output goes —
`Capacitor/Console` lines are `console.log` and uncaught errors from the page,
and they are the difference between "the app shows a blank screen" and knowing
which request 404'd. A debug build also enables WebView debugging, so
`chrome://inspect` reaches it.

What this does not cover is JGit against a real repository over a real network:
clone size, storage, and the background time limits a phone actually enforces.

## The launcher icon

`python3 scripts/make-launcher-icons.py` renders every mipmap from
`frontend/static/IdeaBRD-logo.png`, the same file the web app serves, so the two
can't drift. It writes an adaptive icon: the logo sized to 72dp on a 108dp
canvas over a flat `#0f172a`, which lands just inside whatever mask the launcher
draws — a circle on Pixel, a squircle elsewhere. The legacy `ic_launcher.png`
and `ic_launcher_round.png` are pre-masked for anything that doesn't read the
adaptive one. Change the logo, re-run the script, commit what it writes.

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
