#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""memoize a command
Based on https://github.com/kgaughan/memoize.py with some additions:
    updated to python3
    use sha256 instead of md5
    don't load the whole file to be hashed at once
    track renames of temporary files
    properly handle commands with spaces/special characters in them
    follow pylint
    verbosity
    optionally ignore directories
    use argparse
TODO
    no pylint warnings
"""

import sys
import os
import os.path
import shlex
import re
# Try this regex module
# import regex as re
import hashlib
import tempfile
import pickle
import subprocess
import argparse


__author__ = 'jlmcgraw@gmail.com'

# Should we use modtime as the check for a file being changed (default is hash)
opt_use_modtime = False

# Directories to monitor
opt_dirs = []

# Directories to ignore
ignore_dirs = []


def hash_file(fname: str):
    """ Return the hash of a file """
    blocksize = 65536

    # Which type of hash to use
    hasher = hashlib.sha256()

    try:
        with open(fname, 'rb') as file_to_hash:
            buf = file_to_hash.read(blocksize)
            while len(buf) > 0:
                hasher.update(buf)
                buf = file_to_hash.read(blocksize)
        return hasher.hexdigest()
    except Exception:
        return None


def modtime(fname: str):
    """ Return modtime of a given file"""
    try:
        return os.path.getmtime(fname)
    except Exception:
        return 'bad_modtime'


def files_up_to_date(files: list) -> bool:
    """ Check the up_to_date status of all files used by this command """

    if files is None:
        if args.verbose:
            print('MEMOIZE: No files yet')
        return False

    for (fname, hash_digest, mtime) in files:
        if opt_use_modtime:
            if modtime(fname) != mtime:
                if args.verbose:
                    print('MEMOIZE: File modtime changed: ', fname)
                return False
        else:
            if hash_file(fname) != hash_digest:
                if args.verbose:
                    print('MEMOIZE: File hash changed: ', fname)
                return False
    return True


def is_relevant(fname: str) -> bool:

    """ Do we want to consider this file as relevant?"""
    path1 = os.path.abspath(fname)

    # Do we want to ignore this directory and its subdirectories?
    if ignore_dirs:
        for ignorable_directory in ignore_dirs:
            path2 = os.path.abspath(ignorable_directory)
            if path1.startswith(path2):

                if args.verbose:
                    print('MEMOIZE: Ignoring: ', path1)

                return False

    # Do we want to specifically include this directory and its subdirectories?
    for additional_directory in opt_dirs:
        path2 = os.path.abspath(additional_directory)

        if path1.startswith(path2):

            if args.verbose:
                print('MEMOIZE: Including: ', path1)

            return True

    # Default is to ignore the file
    return False


def generate_deps(cmd: str) -> tuple:
    """ Gather dependencies for a command and store their hash and modtime """
    if args.verbose:
        print('MEMOIZE: running: ', cmd)

    # strace_output_filename = './strace_output'
    strace_output_filename = tempfile.mktemp()

    if args.verbose:
        print("MEMOIZE: strace output saved in ", strace_output_filename)

    # wholecmd = \
        # 'strace -f -o %s -e trace=open,rename,stat,stat64,exit_group %s' \
        # % (strace_output_filename, cmd)

    wholecmd = \
        'strace -f -o %s -e trace=file,exit_group %s' \
        % (strace_output_filename, cmd)

    # print(wholecmd)
    subprocess.call(wholecmd, shell=True)

    # Read the strace output and remove the tempfile
    output = open(strace_output_filename).readlines()
    os.remove(strace_output_filename)

    status = 0
    files = []
    files_dict = {}

    # Things we'd like to match
    regexes = [
        r'.*open\("(.*)", .*',
        r'.*stat64\("(.*)", .*',
        r'.*rename\(".*", "(.*)"',
        r'.*stat\("(.*)", .*',
        r'.*openat\(AT_FDCWD, "(.*)", .*'
        ]

    for line in output:
        for regex in regexes:
            match = re.match(regex, line)

            if match:

                # Get the name of the destination file
                fname = os.path.normpath(match.group(1))

                # if args.verbose:
                #     print("MEMOIZE: Regex {} matched {}".format(regex, fname))

                if fname not in files_dict \
                        and is_relevant(fname) \
                        and os.path.isfile(fname):

                    # if args.verbose:
                    #     print('MEMOIZE: Is relevant: ', fname)

                    # Add this file's hash and datestamp to our dictionary
                    # and mark that we've seen it already
                    files.append((fname, hash_file(fname), modtime(fname)))
                    files_dict[fname] = True

            # Get the exit code from strace output if it exists
            match = re.match(r'.*exit_group\((.*)\).*', line)

            if match:

                # Use that for our return code
                status = int(match.group(1))

    return status, files


def read_deps(depsname: str) -> dict:
    """ Unpickle the dependencies dictionary """
    try:
        pickle_file = open(depsname, 'rb')
    except Exception:
        pickle_file = None

    if pickle_file:
        deps = pickle.load(pickle_file)
        pickle_file.close()
        return deps

    # Return an empty dictionary if no existing dependencies
    return {}


def write_deps(depsname: str, deps: dict):
    """ Pickle the dependencies dictionary to a file """
    pickle_file = open(depsname, 'wb')
    pickle.dump(deps, pickle_file)
    pickle_file.close()


def memoize_with_deps(depsname: str, deps: dict, cmd: str) -> int:
    """ Run a command if it has no existing dependencies or if they're out of
    date. Save the captured dependencies
    """

    # Get the files used by this command from our stored dictionary
    files = deps.get(cmd)

    if args.verbose:
        print('Files used: ', files)

    # Check the status of all of this command's files

    if files and files_up_to_date(files):
        # if args.verbose:
        print('MEMOIZE: Up to date: {}'.format(cmd))
        return 0
    else:
        # Run the command and collect list of files that it opens
        (status, files) = generate_deps(cmd)

        # If the command was successful...
        if status == 0:

            # Add the files list to the dictionary
            deps[cmd] = files

        elif cmd in deps:

            # Delete the key if the command was unsuccessful
            del deps[cmd]

        # Write out the dictionary of opened files for this command
        write_deps(depsname, deps)

        return status


if __name__ == '__main__':

    # Parse the command line options

    parser = argparse.ArgumentParser(
        description='Memoize any program or command.  By default it will only monitor files under the current directory')

    parser.add_argument(
        '-t',
        '--timestamps',
        action='store_true',
        help='Use timestamps instead of hash to determine if a file has changed',
        required=False)

    parser.add_argument(
        '-d',
        '--directory',
        action='append',
        default=['.'],
        metavar='DIRECTORY',
        help='Monitor this directory and its subdirectories',
        required=False)

    parser.add_argument(
        '-i',
        '--ignore',
        action='append',
        metavar='DIRECTORY',
        help='Ignore this directory and its subdirectories',
        required=False)

    parser.add_argument(
        '-v',
        '--verbose',
        help='More output',
        action='store_true',
        required=False)

    parser.add_argument(
        '-f',
        '--filename',
        default='.deps3',
        help='Filename to store dependency information in',
        required=False)

    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help='The command to memoize')

    args = parser.parse_args()

    # Sort the individual elements of the command
    # Good idea or not?: Consider using this as the key
    # so the command could be rearranged without being considered out of date

    # command_sorted = sorted(args.command)

    # Quote all the individual items in command and join them with a space
    # into a string
    command_string = ' '.join(shlex.quote(element) for element in args.command)

    # Check that a command was supplied
    if not command_string:
        print('Error: A command to memoize is required')
        parser.print_help()
        sys.exit(1)

    if args.verbose:
        print('Command: ', args.command)
        # print('Command sorted: ', command_sorted)
        print('Command string: ', command_string)
        print('Ignoring these directory trees: ', args.ignore)
        print('Monitoring these directory trees: ', args.directory)
        print('Using timestamps: ', args.timestamps)
        print('Dependencies file: ', args.filename)

    opt_use_modtime = args.timestamps
    opt_dirs = args.directory
    ignore_dirs = args.ignore

    # Get stored dependencies
    default_deps = read_deps(args.filename)

    # Check the status of those dependencies and run the command if anything has changed
    memoize_status = memoize_with_deps(
        args.filename, default_deps, command_string)

    sys.exit(memoize_status)
