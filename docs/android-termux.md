# keepgram on Android (Termux)

This guide sets keepgram up on an Android phone or tablet, from nothing to your first upload. It
takes about 15 minutes. You don't need a computer.

keepgram runs inside [Termux](https://termux.dev), a free app that gives Android a Linux terminal.
You type a few commands once. After that you start keepgram with one command and use its menus by
tapping.

- [What you need](#what-you-need)
- [1. Install Termux](#1-install-termux)
- [2. Update Termux](#2-update-termux)
- [3. Install Python and Git](#3-install-python-and-git)
- [4. Let Termux see your files](#4-let-termux-see-your-files)
- [5. Download keepgram](#5-download-keepgram)
- [6. Make copies faster (optional)](#6-make-copies-faster-optional)
- [7. Start keepgram](#7-start-keepgram)
- [8. Log in to Telegram](#8-log-in-to-telegram)
- [Using the menus on a phone](#using-the-menus-on-a-phone)
- [Uploading folders from your phone](#uploading-folders-from-your-phone)
- [Carrying on from your computer](#carrying-on-from-your-computer)
- [Keep it running when the screen is off](#keep-it-running-when-the-screen-is-off)
- [Updating keepgram](#updating-keepgram)
- [Removing keepgram](#removing-keepgram)
- [When something goes wrong](#when-something-goes-wrong)

## What you need

- Android 7 or newer
- about 500 MB free (1.5 GB if you also do [step 6](#6-make-copies-faster-optional))
- Wi-Fi for big jobs. Copying a file downloads it and uploads it again, so it uses twice its size
  in data.

## 1. Install Termux

Install Termux from **F-Droid** or from **GitHub**:

- F-Droid: <https://f-droid.org/packages/com.termux/>. Install the F-Droid app first, then search
  for Termux in it.
- GitHub: <https://github.com/termux/termux-app/releases>. Download the `.apk` that ends in
  `universal.apk` (or `arm64-v8a.apk` for most phones) and open it. Android asks you to allow
  installing apps from your browser; allow it.

Prefer these over Google Play, whose Termux is a separate, more limited build. Don't mix sources:
Termux and its add-ons only work together when they come from the same place.

Open Termux. You get a black screen with a `$` prompt. That's where you type the commands below.
Long-press the screen and choose **Paste** to paste a command you copied from this page.

## 2. Update Termux

```bash
pkg update && pkg upgrade
```

When it asks a question (`[Y/n]` or which version of a file to keep), press **Enter** to take the
default. This can take a few minutes the first time.

If it fails with errors about a mirror or a repository, run `termux-change-repo`, choose a mirror
group near you, and run the command again.

## 3. Install Python and Git

```bash
pkg install python git
```

Check it worked:

```bash
python --version
```

It should say `Python 3.10` or newer.

## 4. Let Termux see your files

```bash
termux-setup-storage
```

Android asks whether Termux may access your files. Tap **Allow**. (On some phones it opens a
settings page instead: turn on **Allow access to manage all files** for Termux, then go back.)

Now your phone's storage is at `/storage/emulated/0`, the same place a file manager shows as
"Internal storage". keepgram needs this only to upload folders from your phone. If you skip it, the
rest still works.

## 5. Download keepgram

```bash
cd ~
git clone https://github.com/tawhidUnhappy/keepgram.git
```

This puts keepgram in Termux's own folder (`~/keepgram`). **Keep it there; don't move it to your
phone's storage.** Termux's own folder is private: other apps can't read it, and your Telegram login
will be saved in it. Python also can't build its environment on the phone's shared storage.

## 6. Make copies faster (optional)

keepgram works without this step, but copying and uploading are much faster with it, and the phone
works less hard. It installs Rust, which is used to build `cryptg`, a small speed-up for the
encryption Telegram uses:

```bash
pkg install rust
```

It's about 1 GB. If your phone is short on space, skip it.

## 7. Start keepgram

```bash
cd ~/keepgram
./run.sh
```

The first time, it says `[keepgram] setting up .venv ...` and installs what it needs. That takes 1
to 3 minutes, or longer if you did step 6, because `cryptg` is being built on the phone. It
shows nothing while it works, so let it be. The next starts take a second.

Then the keepgram menu opens.

Did step 6 after keepgram was already set up? Add the speed-up with:

```bash
cd ~/keepgram
.venv/bin/python -m pip install cryptg
```

## 8. Log in to Telegram

keepgram logs in as you, with an API app of your own. Make it first:

1. In your phone's browser, open <https://my.telegram.org> and log in with your phone number. The
   code arrives in your Telegram app.
2. Tap **API development tools**. Fill in an app title and a short name (anything works), choose
   **Desktop** as the platform, and create it.
3. Keep that page open. You'll copy `api_id` (a number) and `api_hash` (a long code) from it.

Back in Termux, choose **Log in / log out** in the keepgram menu (or run `./run.sh login`):

1. Paste your `api_id`, then your `api_hash`. Switch between the browser and Termux with the
   recent-apps button. Long-press in Termux and tap **Paste**.
2. Type your phone number with the country code, like `+447700900123`.
3. Type the code Telegram sends to your Telegram app.
4. If you set a cloud password (two-step verification), type it.

You only do this once. Your login is saved in `~/keepgram/data/keepgram.session`. **That file opens
your account: never share it, and never copy it to your phone's storage or anywhere else.** To log
keepgram out, open Telegram → Settings → Devices and end its session.

## Using the menus on a phone

| To do this | On the phone |
|---|---|
| highlight a menu item | tap it, or use the arrow keys |
| choose it | **double-tap** it, or press **Enter** on the keyboard |
| go back | **Esc**: the `ESC` key on the bar above the keyboard, or **Volume Up + E** |
| quit | `q` |
| stop a running job | **Ctrl+C**: hold **Volume Down** and tap `c` (or `CTRL`, then `c`, on the extra-keys bar). Press it again to stop at once. |
| make the text smaller or bigger | pinch the screen with two fingers |
| show the keyboard again | tap the screen, or swipe the extra-keys bar |

The menus fit a phone held upright, but **turning it sideways** gives the lists and progress bars
more room.

The keyboard can cover the bottom of the screen. Swipe the keyboard away to see the whole menu,
and tap the screen to bring it back.

## Uploading folders from your phone

Choose **Upload a folder** in the menu and type the folder's path. Common ones:

| Folder | Path |
|---|---|
| Camera photos and videos | `/storage/emulated/0/DCIM/Camera` |
| Downloads | `/storage/emulated/0/Download` |
| Pictures | `/storage/emulated/0/Pictures` |
| Movies | `/storage/emulated/0/Movies` |
| Documents | `/storage/emulated/0/Documents` |

Not sure of a path? Look at a folder's location in your file manager: "Internal storage" is
`/storage/emulated/0`. You can also list what's there from Termux:

```bash
ls /storage/emulated/0
```

If your phone has a memory card, `ls /storage` shows its name (like `1A2B-3C4D`); its folders are
under `/storage/1A2B-3C4D/...`.

The same works from the command line:

```bash
./run.sh upload /storage/emulated/0/DCIM/Camera
```

Files bigger than Telegram allows go up in parts, read straight from the file, so an upload takes
no extra space on your phone.

**Keep your copies on the phone too (optional).** Settings → `secure.local_copy_dir` keeps a copy of
every file keepgram makes your own in a folder, for example
`/storage/emulated/0/keepgram-copies`. Make sure your phone has room for them.

## Carrying on from your computer

Started **Make every file my own** on your computer? Log in on the phone with the same account
and choose it again. keepgram looks in your chats for the copies already made and copies only what
is left. Nothing is copied twice. Folder uploads do the same: files already in the chat are
skipped.

Run keepgram on one device at a time: close it on the computer before you start it on the phone.

To delete the forwards that now have their own copy, choose **Delete forwards I have copies of**.
It checks every copy again first, shows how many forwards it will delete, and asks before deleting.

## Keep it running when the screen is off

Android stops apps it thinks are idle. For a job that runs for hours (making old files your own, a
big upload, or **Keep working while I use Telegram**):

1. **Hold a wake lock.** Pull down the notification shade, find Termux's notification, and tap
   **Acquire wakelock**. (Or run `termux-wake-lock` before starting keepgram.) Tap **Release
   wakelock** when you're done; it uses battery.
2. **Turn off battery optimisation for Termux.** Settings → Apps → Termux → Battery → **Unrestricted**
   (the names differ a little between phones). On Xiaomi, Huawei, Samsung and OnePlus phones, also
   look for "Autostart", "Background activity" or "Sleeping apps", and allow Termux there. The site
   <https://dontkillmyapp.com> has steps for each brand.
3. **Plug it in and use Wi-Fi.** A copy job can run for a long time.

**Android 12 and newer** can also stop programs inside Termux that use a lot of processor. If keepgram
stops by itself even with the steps above, turn this off: Settings → Developer options → **Disable
child process restrictions** (Android 14 and newer; to see Developer options, tap Settings → About
phone → Build number seven times). On Android 12 and 13 this needs a computer and
[ADB](https://developer.android.com/tools/adb):

```bash
adb shell "settings put global settings_enable_monitor_phantom_procs false"
```

If Android stops keepgram anyway, nothing is lost: start it again and choose the same job. It
carries on where it stopped and never makes the same copy twice
(see [Stopping and resuming safely](../README.md#stopping-and-resuming-safely)).

## Updating keepgram

```bash
cd ~/keepgram
git pull
./run.sh
```

If an update needs new parts, `./run.sh` installs them by itself on that start.

## Removing keepgram

1. Log keepgram out: Telegram → Settings → Devices → end its session.
2. In Termux:

   ```bash
   rm -rf ~/keepgram
   ```

   This deletes keepgram, your settings and your login on the phone. What keepgram made on
   Telegram (folders, copies, uploads) stays.

To remove Termux as well, uninstall it like any other app.

## When something goes wrong

| What you see | What to do |
|---|---|
| `pkg` fails with mirror or repository errors | Run `termux-change-repo`, pick another mirror, and try again. |
| `Permission denied` when running `./run.sh` | Run `cd ~/keepgram` first. Make sure you didn't clone it into `/storage/emulated/0`; if you did, clone it again in `~` ([step 5](#5-download-keepgram)). |
| `./run.sh: No such file or directory` | You're in the wrong folder. Run `cd ~/keepgram`. |
| `Permission denied` on a folder you upload | Run `termux-setup-storage` again and allow access ([step 4](#4-let-termux-see-your-files)). Folders inside `Android/data` can't be read by any app on newer Android. |
| keepgram stops when the screen turns off | Follow [Keep it running when the screen is off](#keep-it-running-when-the-screen-is-off). Then start it again; it carries on. |
| Copies are very slow | Do [step 6](#6-make-copies-faster-optional). Use Wi-Fi. Telegram also limits upload speed for accounts without Premium; keepgram follows that by itself. |
| `setting up .venv` takes very long | It's building `cryptg` after step 6. On a slow phone that can take 10 minutes or more; let it finish. |
| The menu looks broken or cut off | Turn the phone sideways, or pinch to make the text smaller. |
| The login code never arrives | It's sent to your Telegram app, not by SMS. Check Telegram on this phone or another device. |
