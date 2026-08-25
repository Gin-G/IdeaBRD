#!/usr/bin/env bash
# Create the signing key the release workflow uses, and print the four secrets
# to set on the repository.
#
# Why this matters: without a stable key every release is signed differently,
# and Android refuses to install one build over another — anyone updating has
# to uninstall first and loses whatever the app was holding. The key itself is
# the identity of the app, so keep the .jks somewhere you will still have it in
# five years. Losing it means the app can never be updated again, only replaced
# under a new name.
#
#   ./android/scripts/make-signing-key.sh [keystore-path]
#
# It never uploads anything. Copy the values it prints into
# Settings → Secrets and variables → Actions.
set -euo pipefail

keystore="${1:-ideabrd-release.jks}"
alias="ideabrd"

if [ -e "$keystore" ]; then
  echo "Refusing to overwrite $keystore — that file may be the only copy of a key." >&2
  exit 1
fi

read -rsp "Password for the new keystore: " password
echo
read -rsp "Confirm: " confirm
echo
[ "$password" = "$confirm" ] || { echo "Passwords differ." >&2; exit 1; }
[ ${#password} -ge 6 ] || { echo "keytool wants at least six characters." >&2; exit 1; }

keytool -genkeypair -v \
  -keystore "$keystore" \
  -alias "$alias" \
  -keyalg RSA -keysize 4096 -validity 10000 \
  -storepass "$password" -keypass "$password" \
  -dname "CN=IdeaBRD, O=IdeaBRD, C=GB"

cat <<EOF

Done: $keystore

Set these four repository secrets (Settings → Secrets and variables → Actions):

  ANDROID_KEYSTORE_BASE64   $(base64 -w0 "$keystore" | cut -c1-24)…  (full value below)
  ANDROID_KEYSTORE_PASSWORD the password you just chose
  ANDROID_KEY_ALIAS         $alias
  ANDROID_KEY_PASSWORD      the same password

The full base64 of the keystore:

$(base64 -w0 "$keystore")

Back up $keystore somewhere durable and keep it out of the repository —
.gitignore already covers *.jks.
EOF
