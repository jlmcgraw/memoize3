A python3 utility to memoize an arbitrary shell command

It will monitor the files utilized by a command and, if none of them have changed since the last execution, it will not re-run the command

Based on https://github.com/kgaughan/memoize.py with some additions:
    
    - updated to python3
    - use sha256 instead of md5
    - don't load the whole file to be hashed at once
    - track renames of temporary files
    - properly handle commands with spaces/special characters in them
    - follow pylint
    - verbosity
    - optionally ignore directories
    - use argparse
