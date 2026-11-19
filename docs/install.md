[← Back to the README](../README.md)

# Installing Codetta

You need a server with [Docker](https://docs.docker.com/engine/install/) and
Docker Compose, and your music in a folder on that server.

Codetta is light enough for starter hardware like a Raspberry Pi 4 and scales
to big libraries:

| | Typical |
|---|---|
| Download (image) | about 100 MB, for Intel/AMD and ARM |
| Memory | about 70 MB for a typical library; about 130 MB at 100,000 tracks (plus short-lived helpers while it first reads a big library) |
| Search index | about 2 KB per track (10 MB for 5,000 tracks) |
| When idle | no CPU and no disk activity, so your drives can sleep |

## 1. Back up your library

If you don't have a backup of your music yet, make one now. Codetta is
careful, but a backup protects you from the one thing no software can:
editing the wrong album.

## 2. Find the user that owns your music

Codetta runs as a normal user (never root), so the files it edits keep their
owner and your other apps can still read them:

```sh
ls -ln /path/to/your/music | head -3   # 3rd and 4th columns: user and group ID
```

On most single-user servers that's `1000` and `1000`.

## 3. Get Codetta

Make a folder for Codetta and download its compose file:

```sh
mkdir codetta && cd codetta
curl -fsSLO https://raw.githubusercontent.com/gavndev/codetta/main/docker-compose.yml
```

## 4. Point it at your music

Create `docker-compose.override.yml` next to `docker-compose.yml`, with your
own path and IDs:

```yaml
services:
  codetta:
    environment:
      PUID: "1000"   # from step 2
      PGID: "1000"
    volumes:
      - /path/to/your/music:/music
```

Keeping your settings in this separate file means updates never overwrite them.

## 5. Start it

```sh
docker compose up -d
```

Docker downloads the ready-made image (`ghcr.io/gavndev/codetta`), which
works on Intel/AMD and ARM servers. On a big library, the search index takes a
few minutes to build in the background; everything else works straight away.

## 6. Create your account

Open `http://<your-server>:8111` and choose a username and password (at least
8 characters). Do this right away. For safety, the setup screen only works
from your home network, Tailscale or the server itself.

## 7. Try it on one album first

Pick an album you know well, make a small change, and check it in your music
app after its next library scan. Happy? Then it's ready for the rest of your
library.

## Updating

Your version is shown on the sign-in screen and in the account menu (the
person icon). When a new release is out, a dot appears on that icon, and the
account menu shows what's new and the commands to run:

```sh
cd codetta
docker compose pull
docker compose up -d
```

To stay on a specific version, change `latest` in `docker-compose.yml` to a
version number such as `0.1.0`. Codetta never updates itself. That would mean giving it control of Docker,
and with it the rest of your server. Your account, presets and activity log
live in `./codetta-config` and are kept across updates.

## Signing in

- Each browser stays signed in for 30 days.
- The person icon in the top bar lets you set a profile picture, change your
  password or sign out. Changing the password signs out your other devices.
- After 5 wrong passwords, that device has to wait before trying again
  (30 seconds, doubling each time, up to 15 minutes).

### Resetting your password

Forgot your password? Reset it from the server:

```sh
docker exec -it codetta codetta-admin set-password
```

You'll be asked for a new password, and every device is signed out. To sign
out every device without changing the password, use `codetta-admin sign-out-all`.

## Removing Codetta

```sh
cd codetta
docker compose down
docker image rm ghcr.io/gavndev/codetta
```

Your music is never deleted. Remove the `codetta-config` folder too if you
don't want to keep your account, presets and activity log.
