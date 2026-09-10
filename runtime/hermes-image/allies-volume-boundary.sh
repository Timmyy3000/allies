#!/bin/sh
set -eu

volume_root=/opt/data
if [ -L "$volume_root" ] || [ ! -d "$volume_root" ]; then
    echo "Allies volume root is unsafe" >&2
    exit 1
fi
chown 0:0 "$volume_root"
chmod 1777 "$volume_root"
