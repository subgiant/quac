# Copyright (c) 2012-2013 Los Alamos National Security, LLC, and others.

# Set up environment for tests.

# test scripts in this checkout, not in $PATH
export PATH=$(cd $(dirname $0)/../bin && pwd):$PATH

# Same for Python modules; the oddness is so we don't have a trailing colon if
# $PYTHONPATH is unset.
export PYTHONPATH=$(cd $(dirname $0)/../lib && pwd)${PYTHONPATH:+:}$PYTHONPATH

# Make a private directory for tests to work in. If tests need to share state,
# they can set it up manually.
mkdir $DATADIR/$TESTNAME
export DATADIR=$DATADIR/$TESTNAME

# stop test if any command fails
set -e

# echo key commands
x () {
    echo "\$ $@"
    eval "$@"
}

# echo key pipelines (executed in a subshell)
y () {
    echo "$ ($1)"
    bash -c "$1"
}
