# Tested deployment profile

The final 2.0.13 build was verified on a Synology Container Manager deployment with:

- `privileged: true`
- `pid: host`
- a normal read/write bind mount for the project data directory
- no `:rshared` dependency on `/volume1`
- host mount namespace operations via `nsenter -t 1 -m`
- Web access through a configurable host port

The exact DSM version, NAS IP address, NAS username, and image filenames are intentionally not stored in this repository.
