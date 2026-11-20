# Security

## Reporting a problem

Please report security problems **privately** through
[GitHub's security advisories](https://github.com/gavndev/codetta/security/advisories/new),
not in a public issue. You'll get a reply as soon as possible, and fixes are released as a new version.

Only the latest release gets security fixes while Codetta is in beta.

## How Codetta protects you

- Every page and API call requires signing in, except the sign-in screen and a health check.
- A fresh install can only be set up from your home network, Tailscale or the server itself.
- Passwords are hashed with scrypt; sessions are random tokens stored only as hashes; repeated wrong passwords are locked out.
- Changes must come from Codetta's own page (cross-site requests are refused), request sizes are capped, and every response carries a strict Content Security Policy.
- Album art from your files is only ever shown as an image, so a malicious file can't run code in your browser.
- The container runs as your user, with a read-only system filesystem and no extra privileges.
- Codetta only touches files inside the music folder. Symlinks *you* put there (e.g. to music on another disk) are followed; nothing in Codetta can create links, upload new files or delete tracks.
- Requests are bounded: at most 1,000 files and 100,000 characters per tag value per request, and a file listed twice is only edited once.

See also [Remote access and HTTPS](docs/configuration.md#remote-access-and-https).
