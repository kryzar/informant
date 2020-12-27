#!/usr/bin/python3
"""
informant - an Arch Linux News reader designed to also be used as a pacman hook

Usage:
    informant [options] check
    informant [options] list [--reverse --unread]
    informant [options] read [<item> | --all]

Commands:
    check - Check for unread news items, will exit with a positive return code
            with the number of unread items. If there is only one unread item it
            will also print in like 'read' would and mark it as read, else it
            will print the number of unread titles.

    list -  Print the most recent news items, regardless of read status. If
            '--reverse' is provided items are printed oldest to newest. If
            '--unread' is provided only the unread items are returned.

    read  - Read the specified news item, <item> can be either an index or a
            full title. This will also save the item as 'read' so that future
            calls to 'check' will no longer display it. If no <item> is given,
            will begin looping through all unread items, printing each one and
            marking them as read with a prompt to continue. Passing the --all
            flag will mark all items as read without printing.

Options:
    -d, --debug                 Print the command line arguments and don't make
                                changes to the save file
    -r, --raw                   When printing items do not replace any markup
    -f <file>, --file=<file>    Use <file> as the save location for read items
    -h, --help                  Show this help and exit
    -V,--version                Show version and exit
    --no-cache                  Do not use cache

"""

# builtins
import json
import os
import pickle
import shutil
import subprocess
import sys
import textwrap

# external
import docopt
import html2text

# local
from informant.feed import Feed

__version__ = '0.3.0'

CONFIG_FILE = 'config.json' #TODO rename for release
ARCH_NEWS = 'https://archlinux.org/feeds/news'
FILE_DEFAULT = '/var/cache/informant.dat'

# colors
RED = '\033[0;31m'
YELLOW = '\033[1;33m'
CLEAR = '\033[0m'
BOLD = '\033[1m'

# commands
CHECK_CMD = 'check'
LIST_CMD = 'list'
READ_CMD = 'read'

# global options
DEBUG_OPT = '--debug'
FILE_OPT = '--file'
RAW_OPT = '--raw'
NOCACHE_OPT = '--no-cache'

# 'list' options
REV_OPT = '--reverse'
UNREAD_OPT = '--unread'

# 'read' options and args
ITEM_ARG = '<item>'
READALL_OPT = '--all'

def err_print(*args, **kwargs):
    """ Same as builtin print but output to stderr. """
    print(*args, file=sys.stderr, **kwargs)

def pacman_msg(*args, **kwargs):
    """ Same as print but include informant preamble so the message is clear in pacman. """
    msg = YELLOW + ':: informant: ' + CLEAR
    for arg in args:
        msg += arg
    print(msg, **kwargs)

def prompt_yes_no(question, default):
    """ Print 'question' to user with (y/n) and 'default' being the
    response for blank input.
    """
    again = 'Unknown response.'
    if default.lower() in ('y', 'yes'):
        options = '(Y/n): '
    elif default.lower() in ('n', 'no'):
        options = '(y/N): '

    response = input(' '.join((question, options))).lower()
    while response not in ('y', 'yes', 'n', 'no', ''):
        response = input(' '.join((again, question, options))).lower()
    if response == '':
        return default
    return response

def running_from_pacman():
    """ Return True if the parent process is pacman """
    ppid = os.getppid()
    p_name = subprocess.check_output(['ps', '-p', str(ppid), '-o', 'comm='])
    p_name = p_name.decode().rstrip()
    if ARGV.get(DEBUG_OPT):
        err_print('informant: running from: {}'.format(p_name))
    return p_name == 'pacman'


def get_save_name():
    """ Return the name of the file to save read information to. """
    if ARGV.get(FILE_OPT):
        return ARGV.get(FILE_OPT)
    return FILE_DEFAULT

def get_datfile(filename):
    """ Return a datfile, which should be a tuple with the first element
    containing the cache, and the second element the list of read items. """
    if ARGV.get(DEBUG_OPT):
        err_print('Getting datfile from "{}"'.format(filename))

    try:
        with open(filename, 'rb') as pickle_file:
            try:
                (cache, readlist) = pickle.load(pickle_file)
                pickle_file.close()
            except (EOFError, ValueError):
                (cache, readlist) = ({"feed": None, "max-age": None, "last-request": None}, [])
    except (FileNotFoundError, PermissionError):
        (cache, readlist) = ({"feed": None, "components": {}}, [])
    return (cache, readlist)

def has_been_read(entry):
    """ Check if the given entry has been read and return True or False. """
    if ARGV.get(DEBUG_OPT):
        err_print(READLIST)
    title = entry['title']
    date = entry['timestamp']
    if str(date.timestamp()) + '|' + title in READLIST:
        return True
    return False

def save_datfile():
    """ Save the datfile with cache and readlist """
    if ARGV.get(DEBUG_OPT):
        return
    filename = get_save_name()
    datfile_obj = (CACHE, READLIST)
    try:
        # then open as write to save updated list
        with open(filename, 'wb') as pickle_file:
            pickle.dump(datfile_obj, pickle_file)
            pickle_file.close()
    except PermissionError:
        err_print(RED + 'ERROR: ' + CLEAR + 'Unable to save read information, \
please re-run with correct permissions to access "{}".'.format(filename))
        sys.exit(255)

def mark_as_read(entry):
    """ Save the given entry to mark it as read. """
    if has_been_read(entry):
        return
    title = entry['title']
    date = entry['timestamp']
    READLIST.append(str(date.timestamp()) + '|' + title)
    save_datfile()

def pretty_print_item(item):
    """ Print out the given feed item, replacing some markup to make it look
    nicer. If the '--raw' option has been provided then the markup will not be
    replaced. """
    title = item['title']
    body = item['body']
    timestamp = item['timestamp']
    if not ARGV.get(RAW_OPT):
        #if not using raw also bold title
        title = BOLD + title + CLEAR
        h2t = html2text.HTML2Text()
        h2t.inline_links = False
        h2t.body_width = 85
        body = h2t.handle(body)
    print(title + '\n' + timestamp + '\n\n' + body)

def format_list_item(entry, index):
    """ Returns a formatted string with the entry's index number, title, and
    right-aligned timestamp. Unread items are bolded"""
    terminal_width = shutil.get_terminal_size().columns
    wrap_width = terminal_width - len(str(entry['timestamp'])) - 1
    heading = str(index) + ': ' + entry['title']
    wrapped_heading = textwrap.wrap(heading, wrap_width)
    padding = terminal_width - len(wrapped_heading[0] + str(entry['timestamp']))
    if has_been_read(entry):
        return (
            wrapped_heading[0] +
            ' ' * (padding) +
            str(entry['timestamp']) +
            '\n'.join(wrapped_heading[1:])
                )
    else:
        return (
            BOLD +
            wrapped_heading[0] +
            CLEAR +
            ' ' * (padding) +
            str(entry['timestamp']) +
            BOLD +
            '\n'.join(wrapped_heading[1:]) +
            CLEAR
        )

def check_cmd(feed):
    """ Run the check command. Check if there are any news items that are
    unread. If there is only one unread item, print it out and mark it as read.
    Also, exit the program with return code matching the unread count. """
    unread = 0
    unread_items = []
    for entry in feed:
        if not has_been_read(entry):
            unread += 1
            unread_items.append(entry)
    if unread == 1:
        if RFP:
            pacman_msg('Stopping upgrade to print news')
        pretty_print_item(unread_items[0])
        mark_as_read(unread_items[0])
        if RFP:
            pacman_msg('You can re-run your pacman command to complete the upgrade')
    elif unread > 1:
        print('There are {:d} unread news items! Use informant to read \
them.'.format(unread))
        if RFP:
            pacman_msg('Run `informant read` before re-running your pacman command')
    sys.exit(unread)

def list_cmd(feed):
    """ Run the list command. Print out a list of recent news item titles. """
    if ARGV.get(REV_OPT):
        feed_list = reversed(feed)
    else:
        feed_list = feed
    index = 0
    for entry in feed_list:
        if not ARGV.get(UNREAD_OPT) \
        or (ARGV.get(UNREAD_OPT) and not has_been_read(entry)):
            print(format_list_item(entry, index))
            index += 1

def read_cmd(feed):
    """ Run the read command. Print news items and mark them as read. """
    if ARGV.get(READALL_OPT):
        for entry in feed:
            mark_as_read(entry)
    else:
        if ARGV[ITEM_ARG]:
            try:
                item = int(ARGV[ITEM_ARG])
                entry = feed[item]
            except ValueError:
                for entry in feed:
                    if entry.title == item:
                        break
                #NOTE: this will read the oldest unread item if no matches are found
            pretty_print_item(entry)
            mark_as_read(entry)
        else:
            unread_entries = list()
            for entry in feed:
                if not has_been_read(entry):
                    unread_entries.insert(0, entry)
            for entry in unread_entries:
                pretty_print_item(entry)
                mark_as_read(entry)
                if entry is not unread_entries[-1]:
                    read_next = prompt_yes_no('Read next item?', 'yes')
                    if read_next in ('n', 'no'):
                        break
                else:
                    print('No more unread items')

def run():
    """ The main function.
    Check given arguments get feed and run given command. """
    if ARGV.get(DEBUG_OPT):
        err_print(ARGV)

    feed = []
    for config_feed in CONFIG['feeds']:
        feed = feed + Feed(config_feed).entries

    feed = sorted(feed, key=lambda k: k['timestamp'], reverse=True)

    if ARGV.get(CHECK_CMD):
        check_cmd(feed)
    elif ARGV.get(LIST_CMD):
        list_cmd(feed)
    elif ARGV.get(READ_CMD):
        read_cmd(feed)

def main():
    global ARGV, CACHE, CONFIG, READLIST, RFP
    ARGV = docopt.docopt(__doc__, version='informant v{}'.format(__version__))
    CACHE, READLIST = get_datfile(get_save_name())
    RFP = running_from_pacman()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as cfg:
            CONFIG = json.loads(cfg.read())
    else:
        CONFIG = None
    run()
    sys.exit()

if __name__ == '__main__':
    main()
