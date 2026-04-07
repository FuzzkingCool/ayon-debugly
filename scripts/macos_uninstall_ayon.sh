#!/usr/bin/env bash
#
# macOS — all-in-one AYON Launcher uninstall + user data cleanup (Ynput).
#
# What it does:
#   1. Asks you to quit AYON if it is still running.
#   2. Deletes AYON*.app from /Applications and ~/Applications (same idea as
#      moving the app to Trash per Apple — this removes the bundle directly).
#   3. Deletes matching data under your ~/Library (prefs, caches, etc.).
#   4. Deletes common Qt / PySide user data (org.qt-project prefs, Qt caches,
#      QtProject folder, etc.). That is SHARED with other Qt apps on this Mac
#      (e.g. Qt Creator) — they may lose local Qt settings until reconfigured.
#
# What it does NOT remove:
#   - Other users on this Mac
#   - Anything under /Library (system-wide) without admin — log will say FAILED
#   - Your AYON server projects / cloud data
#   - ~/.ayon folder (your local AYON settings)
#
# References:
#   https://support.apple.com/en-ca/102610
#   https://docs.ayon.dev/docs/dev_launcher_build_macos/
#
# Usage:
#   chmod +x macos_uninstall_ayon.sh
#   ./macos_uninstall_ayon.sh
#
# If you copied this from Windows, ensure Unix line endings (LF), or bash may
# error with "bad interpreter".
#
set -u

mkdir -p "${HOME}/Desktop" 2>/dev/null || true
LOG="${HOME}/Desktop/ayon-uninstall-$(date +%Y%m%d-%H%M%S).log"

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

rm_path() {
  if [[ ! -e "$1" ]]; then
    log "skip (missing): $1"
    return 0
  fi
  if rm -rf "$1"; then
    log "REMOVED: $1"
  else
    log "FAILED (in use, or need admin — use Finder > Trash or sudo): $1"
  fi
}

unload_launch_agent() {
  local plist="$1"
  local label
  [[ -f "$plist" ]] || return 0
  # Prefer bootout by service label (reliable on Ventura+); fall back to path/unload.
  label=$(/usr/libexec/PlistBuddy -c 'Print :Label' "$plist" 2>/dev/null) || true
  if [[ -n "${label:-}" ]]; then
    launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null || true
  fi
  launchctl bootout "gui/$(id -u)" "$plist" 2>/dev/null \
    || launchctl unload "$plist" 2>/dev/null \
    || true
}

{
  log "=== AYON uninstall + cleanup start ==="
  log "log file: $LOG"

  if pgrep -if ayon >/dev/null 2>&1; then
    log "Quit AYON (menu bar tray -> Exit), then press Enter."
    read -r _
  fi

  shopt -s nullglob

  log "--- Applications (AYON*.app) ---"
  for app in /Applications/AYON*.app; do
    rm_path "$app"
  done
  for app in "${HOME}/Applications/AYON"*.app; do
    rm_path "$app"
  done

  log "--- LaunchAgents (user) ---"
  for plist in \
    "${HOME}/Library/LaunchAgents/"*[Aa]yon* \
    "${HOME}/Library/LaunchAgents/"*[Yy]nput*; do
    unload_launch_agent "$plist"
    rm_path "$plist"
  done

  log "--- Preferences ---"
  for p in \
    "${HOME}/Library/Preferences/"*[Aa]yon* \
    "${HOME}/Library/Preferences/"*[Yy]nput*; do
    rm_path "$p"
  done

  log "--- Qt / PySide (shared — other Qt apps on this Mac may reset) ---"
  for p in "${HOME}/Library/Preferences/org.qt-project."*.plist; do
    rm_path "$p"
  done
  for p in \
    "${HOME}/Library/Application Support/Qt" \
    "${HOME}/Library/Application Support/QtProject" \
    "${HOME}/Library/Application Support/QtAssistant"; do
    rm_path "$p"
  done
  for p in \
    "${HOME}/Library/Caches/Qt"* \
    "${HOME}/Library/Caches/"*QtWebEngine* \
    "${HOME}/Library/Caches/"*[Pp]y[Ss]ide* \
    "${HOME}/Library/Caches/"*[Ss]hiboken*; do
    rm_path "$p"
  done
  for p in "${HOME}/Library/Saved Application State/org.qt-project."*; do
    rm_path "$p"
  done
  for p in \
    "${HOME}/Library/Logs/"*QtWebEngine* \
    "${HOME}/Library/Logs/"*[Pp]y[Ss]ide*; do
    rm_path "$p"
  done

  log "--- Application Support ---"
  for p in \
    "${HOME}/Library/Application Support/"*[Aa]yon* \
    "${HOME}/Library/Application Support/"*[Yy]nput*; do
    rm_path "$p"
  done

  log "--- Caches ---"
  for p in \
    "${HOME}/Library/Caches/"*[Aa]yon* \
    "${HOME}/Library/Caches/"*[Yy]nput*; do
    rm_path "$p"
  done

  log "--- Saved Application State ---"
  for p in \
    "${HOME}/Library/Saved Application State/"*[Aa]yon* \
    "${HOME}/Library/Saved Application State/"*[Yy]nput*; do
    rm_path "$p"
  done

  log "--- Logs ---"
  for p in \
    "${HOME}/Library/Logs/"*[Aa]yon* \
    "${HOME}/Library/Logs/"*[Yy]nput*; do
    rm_path "$p"
  done

  log "=== done ==="
  log "If any line shows FAILED for /Applications, quit AYON, retry, or drag the app to Trash (see Apple support link in script header)."
  log "Optional: Finder > Empty Trash. Reboot before reinstalling AYON."
} 2>&1 | tee -a "$LOG"
