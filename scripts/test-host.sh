#!/bin/sh
set -eu
printf '%s\n' '=== host namespace test ==='
nsenter -t 1 -m -- sh -c 'id; echo HOST-MOUNT-NS; findmnt /volume1 || true; command -v mount; command -v losetup; command -v lsblk; command -v blkid'
printf '%s\n' '=== bind path test ==='
ls -ld /volume1/docker/virtual-drive /volume1/docker/virtual-drive/images /volume1/docker/virtual-drive/mounts
