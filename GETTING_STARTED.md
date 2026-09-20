# Getting started (no coding needed)

This gets the budget app running on your own computer in about 15 minutes. Most of that is waiting for downloads.

## What you're installing

One program: **Docker Desktop**. It's a free app that runs the budget tracker inside a sealed box on your computer. You install it once and never open it again. The budget app itself is a folder you download from GitHub.

## Step 1: Install Docker Desktop

1. Go to https://www.docker.com/products/docker-desktop/
2. Click the download button for your computer.
   - **Mac:** pick "Apple Silicon" if your Mac is from 2020 or later, otherwise "Intel chip". Not sure? Click the Apple menu (top left) → About This Mac. It says "Chip: Apple M…" or "Processor: Intel…".
   - **Windows:** pick the Windows download.
3. Open the downloaded file and install it like any other app.
4. Open Docker Desktop once. It may ask you to sign in or accept terms. You can skip signing in. Wait until it says "Engine running" or shows a green light at the bottom left. Then you can leave it.

## Step 2: Download the budget app

1. Go to https://github.com/keatz1/budget_tracker
2. Near the top left there's a dropdown that says **main**. Click it and choose **claude/wizardly-carson-j3x0w9**. (Once this branch is merged into main, skip this step.)
3. Click the green **Code** button, then **Download ZIP**.
4. Find the ZIP in your Downloads folder and unzip it (double-click on Mac; right-click → Extract All on Windows).
5. Move the unzipped folder somewhere you'll keep it, like Documents. Rename it to **budget** if you like. Everything the app stores lives inside this folder, so don't delete it later.

## Step 3: Start it

Open the folder.

- **Mac:** right-click **start-mac.command** and choose **Open**. The first time, macOS may say it's from an unidentified developer. Click **Open** anyway (or go to System Settings → Privacy & Security and click "Open Anyway"). A black text window appears. Leave it alone.
- **Windows:** double-click **start-windows.bat**. If Windows shows "protected your PC", click **More info** then **Run anyway**. A black text window appears. Leave it alone.

The first start downloads and builds the app. That takes 2 to 5 minutes. The window will say what it's doing. When it's ready, your web browser opens to **http://localhost:8000** on its own.

After the first time, starting takes about ten seconds.

## Step 4: Set yourself up

The first page asks for your name, email and a password. That makes you the admin. Then:

1. **Accounts** → **Add account**. One for each card or bank account. Pick the matching CSV profile: *Chase credit card*, *Chase checking*, or *Apple Card*.
2. **Import** → pick the account → choose the CSV you downloaded from the bank → **Preview** → **Import**.
3. **Review** shows everything that doesn't have a category yet, grouped by shop. Tap **Category…** on each group and pick one. Leave "make a rule" ticked so the next import sorts itself.
4. **Budgets** → type a monthly amount next to each category → **Save**.
5. **Settings** → **Invite someone** → type Sally's name and email. Copy the link that appears and send it to her. She opens it and sets her own password.

## Using it from your phone

While your computer is on and the app is running, your phone can use it too, as long as both are on the same Wi-Fi.

1. Find your computer's address on the network.
   - **Mac:** System Settings → Wi-Fi → click **Details** next to your network → IP address. It looks like `192.168.1.23`.
   - **Windows:** Settings → Network & Internet → Wi-Fi → your network → look for IPv4 address.
2. On your phone, open the browser and go to `http://192.168.1.23:8000` (your number instead).
3. Tap Share → **Add to Home Screen** (iPhone) or the three dots → **Add to Home screen** (Android). It opens like an app from then on.

When it moves to the Raspberry Pi, only the address changes.

## Stopping and starting

- To stop: double-click **stop-mac.command** or **stop-windows.bat**. Your data stays.
- To start again: the start file.
- If your computer restarts, the app comes back on its own once Docker Desktop is running.

## Where your data is

Inside the folder, in **data/budget.db**. That one file is everything. Copy it somewhere safe now and then, or use **Settings → Back up database now**, which puts a copy in **data/backups**. Nothing leaves your computer.

## If something goes wrong

- **The browser says "can't connect".** Docker Desktop probably isn't running. Open it, wait for the green light, and run the start file again.
- **The start file says Docker isn't installed but you did install it.** Restart your computer once after installing Docker. Then try again.
- **The black window shows red text and stops.** Take a screenshot of it and send it to me. That's enough to figure out what happened.
- **Import says the columns weren't found.** The account has the wrong CSV profile. Go to Accounts → Edit and pick the right one.
- **You forgot your password.** The other person can't reset it for you yet. Send me a note and I'll add a way.
