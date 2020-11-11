#!/bin/sh

files=$(git ls-files --full-name --recurse-submodules Signal)

_ifs=$IFS
IFS='
'
#                                                     shellcheck disable=SC2086
set -- $files
IFS=$_ifs

rm -f znc-signal.tar.gz
tar -czvf znc-signal.tar.gz "$@"
