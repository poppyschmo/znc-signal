#!/bin/sh
#
# This file is part of ZNC-Signal. See NOTICE for details.
# License: Apache 2.0 <http://www.apache.org/licenses/LICENSE-2.0>

actual=$JAVA_HOME/lib/amd64/libunix-java.so
[ -f "$actual" ] || exit 2
# https://stackoverflow.com/questions/9551588
jsrc='
public class JLP {
  public static void main(String args[]) {
    System.out.println(System.getProperty( "java.library.path" ));
  }
}
'
cd /tmp || exit 3

printf %s "$jsrc" > JLP.java
javac JLP.java
paths=$(java JLP)

IFS=':'
for p in $paths; do
    prospect=$p/libunix-java.so
    wanted=""
    if [ ! -d "$p" ]; then
        continue
    elif [ -h "$prospect" ]; then
        if [ "$(readlink -f "$prospect")" != "$actual" ]; then
            echo "Bad link: '$prospect' -> '$(readlink -f "$prospect")'"
            rm -f "$prospect"
            wanted=1
        fi
    elif [ ! -e "$prospect" ]; then
        wanted=1
    elif [ "$(realpath "$prospect")" != "$actual" ]; then
        echo "Duplicate encountered: '$prospect'"
        exit 4
    fi
    #
    if [ "$wanted" ] && ! ln -sv "$actual" "$p"; then
        exit 1
    fi
done >&2

rm JLP.*
