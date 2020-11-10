#!/bin/sh

# Interactive profile
# Convenience aliases, etc.

alias ll="ls -alh"
alias rm="rm -i"
alias cp="cp -i"
alias mv="mv -i"

USER=$(id -un)
export USER
