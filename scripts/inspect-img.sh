#!/usr/bin/env bash
set -euo pipefail
IMG="${1:-/volume1/example.img}"
LOOP="$(nsenter -t 1 -m -- losetup --find --show --partscan --read-only "$IMG")"
trap 'nsenter -t 1 -m -- losetup -d "$LOOP" >/dev/null 2>&1 || true' EXIT

echo "=== LOOP ==="
echo "$LOOP"
echo "=== PARTITIONS ==="
for d in /sys/class/block/$(basename "$LOOP")p*; do
  [ -e "$d" ] || continue
  n="$(basename "$d")"
  echo "--- $n ---"
  echo "start=$(cat "$d/start") sectors=$(cat "$d/size")"
  nsenter -t 1 -m -- blkid "/dev/$n" 2>&1 || true
done
