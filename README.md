<img src="assets/logo.png" alt="keepgram" width="96" align="left" hspace="14" vspace="4">

# keepgram

Keep your Telegram files your own. keepgram logs in as you and does three things:

1. **Folders**: it finds every channel and group you created and puts them in Telegram chat folders
   (`Keepgram 1`, `Keepgram 2`, ...). When a folder is full, it starts the next one.
2. **Secure**: it finds the files in those chats that still depend on someone else (forwards from
   other people's chats, and `t.me/...` links to their posts) and posts each one again as your own
   upload. Whatever happens to the original afterwards, your copy stays.
3. **Upload**: it uploads a folder from your computer or phone, including its sub-folders. Files too
   big for Telegram go up in parts. If you upload the same folder again, keepgram asks whether to
   skip what's already there.

Everything keepgram makes lives on Telegram's servers: folders, copies and uploads. So it shows up
the same in every Telegram app (Android, iPhone, Windows, macOS, Linux, web). keepgram itself is a
small Python program that runs on all of those systems ([Install](#install)).

<br clear="left">

## Why

A forward or a link isn't really yours. A link to a post stops working when the post, the channel
or its owner's account is deleted. A forward survives the original being deleted, but it still
carries the other chat's name and points at the same stored file, so a file Telegram takes down
there can disappear from your chat too. A copy you uploaded yourself has neither tie.

To be safe even from Telegram itself, set `secure.local_copy_dir`: every file keepgram copies is
also kept on your disk.

## Install

You need Python 3.10 or newer. keepgram installs everything else into `.venv` inside its own
folder.

**Linux / macOS**

```bash
git clone https://github.com/tawhidUnhappy/keepgram.git
cd keepgram
./run.sh            # the menus; or ./run.sh <command>
```

**Windows**: download the repo (Code → Download ZIP), unzip it, and double-click `run.bat`. In a
terminal: `run.bat upload "D:\My Photos"`.

**Android**: install [Termux](https://termux.dev) from F-Droid, then:

```bash
pkg install python git
termux-setup-storage            # lets keepgram read /storage/emulated/0/...
git clone https://github.com/tawhidUnhappy/keepgram.git
cd keepgram && ./run.sh
```

Step by step, with logging in, touch keys, phone folder paths and keeping it running with the
screen off: [docs/android-termux.md](docs/android-termux.md).

**iPhone / iPad**: install [a-Shell](https://holzschu.github.io/a-Shell_iOS/), then:

```bash
lg2 clone https://github.com/tawhidUnhappy/keepgram.git
cd keepgram
pip install telethon
python -m keepgram
```

iOS pauses apps in the background, so keep a-Shell open during long uploads. If it stops, run the
same command again and it continues where it left off.

## First run: log in

```bash
./run.sh login
```

keepgram talks to Telegram through an API app of your own:

1. Open <https://my.telegram.org> and log in with your phone number.
2. Go to **API development tools** and create an app (any name).
3. Paste its `api_id` and `api_hash` when keepgram asks. They are saved in `config.json`.

Then type your phone number, the code Telegram sends to your app, and your cloud password if you
have one. You only do this once. The login is stored in `data/keepgram.session`. **That file opens
your account: never share it or upload it anywhere.** To log keepgram out, use Telegram's Settings →
Devices.

## Use it with the menus

```bash
./run.sh            # Windows: double-click run.bat
```

keepgram takes over the terminal while it runs (built on [Textual](https://textual.textualize.io/),
the same menus as [remanga](https://github.com/tawhidUnhappy/remanga)). Every screen has the same
layout: where you are at the top, the list or dialog in the middle, and the keys at the bottom.
You can click those keys too. `q` quits, and `Esc` goes back.

The first item is already highlighted when a list opens, so **Enter** works straight away. The
**arrow keys** move, and a **double click** chooses (a single click only highlights). Questions
that would start something big, like "Copy all 1,059 files?", open on the safe answer (**Not
now**), so a stray Enter never starts a job.

| Menu item | What it does |
|---|---|
| **My channels and groups** | Every chat you created. Choose one to make its files your own, or to upload a folder into it. |
| **Sort them into folders** | Shows the folder plan, and changes your folders only after you say yes. |
| **Make every file my own** | Reads your chats, shows what depends on someone else (file count and size), then copies it after you say yes. |
| **Upload a folder** | Type the folder's path and choose where it goes: a private channel for it, Saved Messages, or one of your chats. If some files are already there, you choose to skip them or upload them again. |
| **Join downloaded parts** | Turns `.001`, `.002`, ... back into the file. |
| **Run the bot** | Runs the bot while that screen stays open. |
| **Settings** | One flat list. Enter changes the highlighted row, and it's saved straight away. |
| **Log in / log out** | Phone number, code and password in dialogs, the first time only. |

Work runs on a task screen with two progress bars:
- one for the file being moved now
- an **All** bar for the whole job, with a line like *"12 of 1059 done · 43.1 GB of 357 GB ·
  3.2 MB/s · about 1 day 6 h left · done around Wed 3:10 AM"*

The time left also shows in the top-right corner. The speed is measured over the last two
minutes, so the estimate follows your connection as it speeds up or slows down. A copied file is
downloaded and then uploaded, so it counts twice its size. On the command line, the same
estimate is on the progress line after `all:`. **Ctrl+C** stops after
the current file, and Ctrl+C again stops straight away. Running it again carries on where it
stopped.

## Or with commands

```bash
./run.sh chats                   # the channels and groups you own
./run.sh folders                 # sort them into Keepgram 1, Keepgram 2, ...
./run.sh secure                  # copy what depends on others as your own
./run.sh secure --chat "My stash" --dry-run
./run.sh all                     # folders, then secure
./run.sh upload ~/Photos         # a folder into a new private channel
./run.sh upload ~/Photos --to me # ... or into Saved Messages, @a_channel, a chat id or title
./run.sh join ~/Downloads/movie.mkv.001
./run.sh bot                     # run the bot (see below)
./run.sh status
./run.sh plugins
```

Every command that changes something shows what it will do first and asks before doing it.
`--dry-run` only shows, and `-y` doesn't ask. Every command can be run again: keepgram remembers
what it has done (in `data/state.db`) and continues from there.

### folders

- Telegram allows 100 chats per folder (200 with Premium) and 10 folders (30 with Premium).
  keepgram learns which apply to you from Telegram, so there's nothing to set.
- A chat stays in the folder it is already in. New chats fill the first folder with room. Chats you
  no longer own are taken out, and a keepgram folder that ends up empty is removed.
- Only folders named `<name> <number>` are touched. Your other folders are left alone. An icon or
  colour you set on a keepgram folder is kept.
- `folders.sorter` picks how chats are split up: `one_series` (all in `Keepgram N`), or `by_type`
  (`Channels N` and `Groups N`). Folder names can be 12 characters at most.

### secure

- It reads each of your chats from oldest to newest. A forward from someone else, or a message with
  a `t.me` link to a post with a file, becomes a job. A forwarded album stays one album.
- Each file is downloaded and uploaded again as the same kind of message: a photo as a photo, a
  video with its size, length and streaming, a file with its name. The caption and its formatting
  are kept, with `↪ kept from <where> · <date>` added below (`secure.source_note`).
- The copy is checked (same file, same size) before anything is recorded. A copy that fails the
  check is never counted as done, and the next run tries it again.
- Copies are sent silently, so members don't get a notification for each one.
- `--replace` (or `secure.replace`) deletes the forward once its copy is posted and checked. For a
  link, the message is only deleted if it contained nothing but the link.
- Forwards from your own chats are skipped (`secure.skip_own_sources`).
- Posts in chats whose owner turned on **Restrict saving content** are not copied. keepgram lists
  them in the report.
- Files bigger than your upload limit are listed and skipped.

### upload

- Every file in the folder and its sub-folders is uploaded, in name order. Each caption is the
  file's path inside the folder, e.g. `Season 1/episode 01.mkv`.
- Files are sent **as files**, byte for byte, so photos and videos aren't recompressed. Set
  `upload.as_files` to `false` to send photos and videos the way the apps do.
- **Big files**: Telegram takes files up to 2000 MB each (4000 MB with Premium). A bigger file goes
  up in parts: `movie.mkv.001`, `movie.mkv.002`, ... The parts are read straight from the original
  file, so nothing extra is written to your disk. A folder can be any size: the limit is per file,
  not per folder.
- **Uploading the same folder again**: by default it goes into the same channel. keepgram finds
  what's already there in two ways:
  - its own record, matched by content, so renamed or moved files still count
  - the chat itself, matched by file name and size, so files uploaded from another device count
    too

  It then asks: **skip** them (the default), upload them **again**, or **cancel**. Set the answer in
  advance with `--duplicates skip` or `--duplicates again`. Two identical files inside the folder
  count as duplicates of each other too.
- If an upload stops halfway (closed window, lost connection), run the same command again. Files
  and parts that are already up are skipped.
- Hidden files (starting with `.`) are skipped (`upload.skip_hidden`). So are empty files, because
  Telegram can't store a 0-byte file.

### join

Download every part, then either:

- run `./run.sh join movie.mkv.001` (or give it a folder to join every set of parts in it), or
- on Windows, use 7-Zip: right-click `movie.mkv.001` → 7-Zip → **Combine files**, or
- on macOS / Linux / Termux, run `cat movie.mkv.0* > movie.mkv`.

The caption of every part ends with the sha256 of the whole file. `join` prints the sha256 of the
file it made, so you can check they match.

## Keep working while you use Telegram

```bash
./run.sh watch          # watches until you close the window (or press Ctrl+C)
./run.sh watch --log    # is it watching in some window, and what it did lately
```

The menus have it too: **Keep working while I use Telegram**.

It runs **in that terminal window and nowhere else**. Close the window, or press Ctrl+C, and it
stops. Nothing keeps running out of sight, so there's nothing to hunt down in a task manager.

While it runs, keepgram follows what you do in Telegram, on any device:

- **Folders:** a chat you create goes into the Keepgram folders, and a new folder starts when one
  is full. A chat you delete or leave is taken out, and a keepgram folder that ends up empty is
  removed.
- **New files:** a file forwarded into one of your chats is copied as your own within about a
  minute of being posted.

It never starts on your **old** files by itself, because that can be hundreds of GB. That's the
**Make every file my own** job, which you start yourself.

**How it stays right:**
- It listens for Telegram's live updates, and also checks every minute with one request for the
  newest message in each of your chats. This catches what Telegram never announces to it, like
  changes made by keepgram's own menus, which use the same login.
- It reads each chat from where it last stopped, so a missed update, a closed window or a night
  offline loses nothing: the next time you start it, it catches up. A failed copy is tried again.
- A copy in progress is claimed in `data/state.db`, so a watcher and the menus never copy the
  same file twice. If a window closes mid-copy, its claim is ignored and the next run copies that
  file. keepgram's own copies are recognised and never copied again.
- Only one window watches at a time. The lock is the operating system's, so it goes with the
  window.
- If the connection drops (Wi-Fi gone, PC asleep), it waits 30 seconds and connects again, in
  the same window. If keepgram is logged out, it stops and says why.
- It uses its own copy of your login (`data/watch.session`), so it and the menus never lock each
  other out.

What it did is in `data/watch.log`.

## Limits learned from Telegram

You don't set keepgram's limits; it asks Telegram every time it connects:

- whether your account has Premium
- the biggest file you can upload (2000 MB, or 4000 MB with Premium, today)
- how many chats a folder holds (100 / 200), and how many folders you may have (10 / 30)
- how long a caption can be (1024 / 4096)

The answer is kept in `data/limits.json` for when there's no connection. If you get Premium, or
Telegram changes a limit, keepgram follows by itself. It never tries to make more folders than
your account allows; it says so instead. `premium` in the settings can still force the limits on
or off.

## The bot: for people who don't want to install anything

`./run.sh bot` runs keepgram as a Telegram bot. Anyone can add it to their channel or group and
keep the files there, with nothing to install.

**Using it** (what you tell people):

1. Open the bot and tap **Add me to a channel** or **Add me to a group**. Telegram asks you to
   confirm the admin rights it needs: post, edit and delete messages in a channel, or delete
   messages in a group.
2. Tap **My chats**, or forward the bot any post from your channel. Only admins of a chat can
   manage the bot there.
3. Tap **Keep all old files now**. The bot reads the whole chat and posts every file that depends
   on someone else again, as the chat's own post. Progress is shown in the private chat.
4. **Auto-keep** is on from the start: new forwards are copied as soon as they're posted.
   **Delete forwards** removes each forward once its copy has been checked.

**What the bot can't do.** Telegram doesn't let bots read anyone's chat list, create chat
folders, or reach files on a computer. So `folders` and `upload` are only in the app. A bot also
can't read chat history the way an account does, so it reads messages by their number instead. It
stops after 2,000 empty numbers in a row past the newest message it knows about. Forwarding it a
recent post tells it the newest number.

**Running the bot** (whoever hosts it):

1. Talk to [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the token.
2. Have `api_id` / `api_hash` in `config.json` (from `login`, or by hand).
3. Run `./run.sh bot`. It asks for the token once, then runs until you stop it. The bot works only
   while this runs, so use a machine that stays on.

Every file the bot copies is downloaded to the host's machine, uploaded again, and deleted from the
disk straight away. So whoever runs the bot pays for the traffic, and could see the files. Users
should only use a bot run by someone they trust, or run their own. `bot.max_jobs` limits how many
chats are copied at once. `bot.allowed_users` (Telegram user ids) makes the bot private. The bot
keeps its own login and records (`data/bot.session`, `data/bot.db`), separate from yours.

## Stopping and resuming safely

You can stop any job at any moment (Ctrl+C, closing the window, a power cut) and run it again.
Nothing is lost, nothing is made twice, and no broken file is left behind:

- **A copy or upload cut off mid-file** leaves nothing in the chat. The pieces go to Telegram
  first, and the message is only posted once every piece is there. Telegram drops the stray
  pieces, and the next run copies that file again from the start.
- **Every piece is checked** for its length on the way down, and Telegram's encryption rejects
  any piece that was altered. A finished copy must be the original's exact size (and pass the MD5
  Telegram requires for small files) before it's recorded. An upload must be the exact size of
  the part it came from.
- **Cut off just after a copy was posted, before it was recorded:** keepgram notes "about to
  post the copy of X" first. The next run sees the note and looks in the chat for that copy
  (same file name, size and caption, posted then). If it's there, it's recorded, not posted
  again. The same goes for a job of several files cut off halfway: only the missing ones are
  copied.
- **Folder uploads** skip what's already in the chat, by keepgram's record and by what's
  actually there.
- **Joining parts** writes to `name.joining` and renames it only when it's complete, so a
  half-joined file never has the real name.
- **keepgram's records** (`data/state.db`) are written in transactions, so a power cut never
  leaves them half-changed. Temporary folders left by an interrupted run are cleared after six
  hours.

Checked for real: keepgram was killed (`kill -9`) 20% into copying a 57 MB file and run again.
The chat ended up with exactly one copy, identical to the original by SHA-256.

## Settings

Copy `config.example.json` to `config.json` (`login` creates it for you). Every key is optional:

| key | default | what it does |
|---|---|---|
| `premium` | `"auto"` | `auto` follows your account; `true` / `false` override it (see [Limits](#limits-learned-from-telegram)) |
| `thumbnails` | `"logo"` | the picture beside files sent as files: `logo`, `own` or `none` (see [File pictures](#file-pictures)) |
| `include_admin_chats` | `false` | also chats where you're an admin, not just ones you created |
| `folders.name` | `"Keepgram"` | folder names are `<name> 1`, `<name> 2`, ... |
| `folders.sorter` | `"one_series"` | `one_series` or `by_type`, or a plug-in's |
| `folders.size` | `0` | chats per folder; 0 = Telegram's limit |
| `secure.finders` | `["forwarded", "post_link"]` | what counts as depending on someone else |
| `secure.skip_own_sources` | `true` | forwards from your own chats aren't copied |
| `secure.replace` | `false` | delete the forward once the copy is safe |
| `secure.source_note` | `true` | add "kept from ..." to the copy's caption |
| `secure.local_copy_dir` | `""` | also keep every copied file in this folder |
| `watch.folders` | `true` | the watcher keeps the folders up to date |
| `watch.keep_new` | `true` | the watcher copies new forwards as they're posted |
| `watch.every_minutes` | `10` | how often the watcher also re-reads your whole chat list |
| `bot.token` | `""` | the bot's token from @BotFather |
| `bot.allowed_users` | `[]` | user ids allowed to use the bot; empty = anyone |
| `bot.max_jobs` | `2` | "keep all" jobs running at once |
| `upload.as_files` | `true` | send everything as files, byte for byte |
| `upload.skip_hidden` | `true` | skip names starting with `.` |
| `upload.part_mb` | `0` | part size for big files; 0 = the limit |

## Plug-ins

Anything that comes in more than one flavour is a plug-in: **finders** (what counts as depending
on someone else) and **sorters** (how chats are split into folders). Put a `.py` file in
`plugins/`, or install a package with a `keepgram.plugins` entry point. See
[plugins/README.md](plugins/README.md) and the example `plugins/_example_finder.py`.

## How it is built

```
keepgram/
  cli.py        the commands
  ui/           the menus (Textual): screens, dialogs, task screen, flows
  bot.py        the bot: private-chat panel, reading by message number, auto-keep
  botstore.py   the bot's chats, switches and managers
  telegram.py   login and connection (Telethon); waits out Telegram's rate limits
  chats.py      the chats you own
  folders.py    planning folders (plain data, testable) and applying them
  secure.py     scanning for finds, copying, checking, replacing
  watch.py      the watcher: runs in its window until that's closed
  limits.py     Telegram's limits for this account, learned on connecting
  upload.py     walking a folder, parts, duplicates, sending
  join.py       parts back into files
  media.py      file kinds, uploads that keep their attributes, FileSlice, progress
  state.py      what has been done (SQLite)
  plugins/      the registry and the built-in finders and sorters
tests/          runs offline: a fake Telegram, and real Telethon requests checked without sending
```

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

When Telegram says to slow down (FLOOD_WAIT), keepgram waits as long as it's told, up to a day,
and then carries on. A big job just takes longer.

**Speed.** Files move in 512 KB pieces, several at once: 16 downloading and 4 uploading. A copy
uploads each piece as soon as it arrives, since Telegram accepts a file's pieces in any order.
So a copy takes about as long as the slower of the two halves, and nothing is written to disk.
On a home connection:
- a 57 MB copy went from 118 s to about 27 s
- a 114 MB folder upload went from about 105 s to 19 s

Copies are compared with the original before anything is recorded; a test copy was identical
to its original, byte for byte. `keepgram/transfer.py` has the details.

**Telegram's upload limit.** Accounts without Premium get about **1 MB/s of sustained upload**.
Telegram allows a burst (about 18 MB), then answers *"a wait of 14 seconds is required in
non-premium accounts"* (`FLOOD_PREMIUM_WAIT`). Downloads are limited far less, which is why the
app can show 7 MB/s while a copy, which also has to upload, runs near 1 MB/s. When told to wait,
keepgram backs off, waits, and speeds up again on its own, with one notice a minute. With Premium
the limit is gone; keepgram notices that by itself (see
[Limits](#limits-learned-from-telegram)). Every keepgram also works on its own copy of the
login, so a second one (the menus plus a command, say) never locks the other out.

## File pictures

Telegram shows a plain grey icon next to a file. keepgram gives every file it sends **as a file**
(copies and uploads) a picture of what kind of file it is, in the same Android 17 style as the
logo:

| kind | files |
|---|---|
| video | mkv, mp4, avi, mov, webm, ... sent as files |
| audio | mp3, flac, m4a, opus, wav, ... sent as files |
| image | jpg, png, heic, raw, ... sent as files |
| archive | zip, rar, 7z, tar, iso, ... |
| document | pdf, docx, txt, epub, xlsx, srt, ... |
| app | apk, exe, msi, deb, ... |
| part | `name.ext.001`, `.002`, ...: a piece of a big file to join |
| other | anything else |

**Photos sent as photos, and videos and songs sent as media, are left alone.** They show in
chats exactly as Telegram always shows them, with their own preview.

The `thumbnails` setting:
- `logo` (default): every file sent as a file gets its kind's picture.
- `own`: a copied file keeps a thumbnail it already has (a frame of a video, say), and gets a
  picture only if it has none.
- `none`: keepgram adds no pictures.

The pictures are `keepgram/thumbs/*.jpg`, and `python assets/make_thumbs.py` redraws them.

## Logo

`assets/` has the logo as an Android adaptive icon: background, foreground and monochrome layers
on a 108-unit canvas. There's also `logo.png`, `avatar.png` (round, for a channel photo) and
`icon-48.png`. `python assets/make_logo.py` rebuilds them all.

## License

MIT. See [LICENSE](LICENSE). keepgram is not made by or affiliated with Telegram.
