# Copyright (C) 2013-2014 Jean-Francois Romang (jromang@posteo.de)
#                         Shivkumar Shivaji ()
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import logging
import queue
import os
import platform
import random
import subprocess
import urllib.request
import socket
from xml.dom.minidom import parseString
try:
    import enum
except ImportError:
    import enum34 as enum


# picochess version
version = '030'

event_queue = queue.Queue()
display_devices = []


class AutoNumber(enum.Enum):
    def __new__(cls): # Autonumber
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

class Event(AutoNumber):
    # User events
    FEN = ()  # User has moved one or more pieces, and we have a new fen position.
    LEVEL = ()  # User sets engine level (from 1 to 20).
    NEW_GAME = ()  # User starts a new game
    USER_MOVE = ()  # User sends a move
    OPENING_BOOK = ()  # User chooses an opening book
    SET_MODE = ()  # Change interaction mode
    SETUP_POSITION = () # Setup custom position
    #Engine events
    BEST_MOVE = ()  # Engine has found a move
    SET_TIME_CONTROL = ()  # User sets time control
    OUT_OF_TIME = ()
    UCI_OPTION_SET = ()  # Users sets an UCI option, contains 'name' and 'value' (strings)
    SHUTDOWN = ()


class Message(AutoNumber):
    #Messages to display devices
    COMPUTER_MOVE = ()  # Show computer move
    BOOK_MOVE = ()  # Show book move
    REVIEW_MODE_MOVE = () # Player is reviewing game
    INTERACTION_MODE = ()  # Interaction mode
    START_NEW_GAME = ()
    COMPUTER_MOVE_DONE_ON_BOARD = ()  # User has done the compute move on board
    SEARCH_STARTED = ()  # Engine has started to search
    USER_TAKE_BACK = ()  # User takes back his move while engine is searching
    UPDATE_CLOCK = ()  # Message send every second when to clock runs, containing white_time and black_time
    RUN_CLOCK = ()  # Say to run autonomous clock, contains time_control
    USER_MOVE = ()  # Player has done a move on board
    UCI_OPTION_LIST = ()  # Contains 'options', a dict of the current engine's UCI options
    GAME_ENDS = ()  # The current game has ended, contains a 'result' (GameResult) and list of 'moves'

    SYSTEM_INFO = () # Information about picochess such as version etc


class Menu(AutoNumber):
    GAME_MENU = ()  # Default Menu
    SETUP_POSITION_MENU = ()  # Setup position menu
    ENGINE_MENU = ()  # Engine menu
    SETTINGS_MENU = ()  # Settings menu


class SetupPositionMenu(AutoNumber):
    TO_MOVE_TOGGLE = ()
    REVERSE_ORIENTATION = ()
    SCAN_POSITION = ()
    SPACER = ()
    SWITCH_MENU = ()  # Switch Menu


class EngineMenu(AutoNumber):
    LEVEL = ()
    BOOK = ()
    TIME = ()
    ENG_INFO = ()
    SWITCH_MENU = ()  # Switch Menu


class GameMenu(AutoNumber):
    LAST_MOVE = () # Show last move
    HINT = ()  # Show hint
    EVAL = ()  # Show evaluation of position
    ADD_TIME = ()  # Add 1 minute to clock
    SWITCH_MENU = ()  # Switch Menu

@enum.unique
class Mode(enum.Enum):
    #Interaction modes
    GAME = 0
    ANALYSIS = 1
    PLAY_WHITE = 2
    KIBITZ = 3
    OBSERVE = 4
    PLAY_BLACK = 5


class ClockMode(AutoNumber):
    FIXED_TIME = ()  # Fixed seconds per move
    BLITZ = ()  # Fixed time per game
    FISCHER = ()  # Fischer increment


class GameResult(enum.Enum):
    MATE = 'mate'
    STALEMATE = 'stalemate'
    TIME_CONTROL = 'time'
    INSUFFICIENT_MATERIAL = 'material'
    ABORT = 'abort'


class Observable(object):  # Input devices are observable
    def __init__(self):
        super(Observable, self).__init__()

    @staticmethod
    def fire(event, **attrs):
        for k, v in attrs.items():
            setattr(event, k, v)
        event_queue.put(event)


class Display(object):  # Display devices (DGT XL clock, Piface LCD, pgn file...)
    def __init__(self):
        super(Display, self).__init__()
        self.message_queue = queue.Queue()
        display_devices.append(self)

    @staticmethod
    def show(message, **attrs):  # Sends a message on each display device
        for k, v in attrs.items():
            setattr(message, k, v)
        for display in display_devices:
            display.message_queue.put(message)


# switch/case instruction in python
class switch(object):
    def __init__(self, value):
        self.value = value
        self.fall = False

    def __iter__(self):
        """Return the match method once, then stop"""
        yield self.match
        raise StopIteration

    def match(self, *args):
        """Indicate whether or not to enter a case suite"""
        if self.fall or not args:
            return True
        elif self.value in args: # changed for v1.5, see below
            self.fall = True
            return True
        else:
            return False


def get_opening_books():
    book_list = sorted(os.listdir(os.path.dirname(os.path.realpath(__file__))+os.sep+'books'))
    library = [('nobook', None)]
    for book in book_list:
        library.append((book[2:book.index('.')], 'books' + os.sep + book))
    return library


def weighted_choice(book, game):
    total = sum(e.weight for e in book.get_entries_for_position(game))
    r = random.uniform(0, total)
    upto = 0
    #for e in book.get_entries_for_position(game):
    #    print(e.move().uci() + 'w:' + str(e.weight))
    for e in book.get_entries_for_position(game):
        if upto + e.weight > r:
            return e.move()
        upto += e.weight
    return None


def hours_minutes_seconds(seconds):
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return h, m, s


def which(program):
    """ Find an executable file on the system path.
    :param program: Name or full path of the executable file
    :return: Full path of the executable file, or None if it was not found
    """
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)
    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep) + [os.path.dirname(os.path.realpath(__file__)),
                                                            os.path.dirname(os.path.realpath(__file__))+os.sep+'engines']:
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file
    logging.warning("Engine executable [%s] not found", program)
    return None


def update_picochess(auto_reboot=False):
    git = which('git.exe' if platform.system() == 'Windows' else 'git')
    if git:
        branch = subprocess.Popen([git, "rev-parse", "--abbrev-ref", "HEAD"], stdout=subprocess.PIPE).communicate()[0].decode(encoding='UTF-8').rstrip()
        if branch == 'stable':
            # Fetch remote repo
            output = subprocess.Popen([git, "remote", "update"], stdout=subprocess.PIPE).communicate()[0].decode(encoding='UTF-8')
            logging.debug(output)
            # Check if update is needed
            output = subprocess.Popen([git, "status", "-uno"], stdout=subprocess.PIPE).communicate()[0].decode(encoding='UTF-8')
            logging.debug(output)
            if not 'up-to-date' in output:
                # Update
                logging.debug('Updating')
                output = subprocess.Popen([git, "pull", "origin", "stable"], stdout=subprocess.PIPE).communicate()[0].decode(encoding='UTF-8')
                logging.debug(output)
                if auto_reboot:
                    os.system('reboot')


def shutdown():
    logging.debug('Shutting down system')
    if platform.system() == 'Windows':
        os.system('shutdown /s')
    else:
        os.system('shutdown -h now')


def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("google.com", 80))
        return s.getsockname()[0]

    # TODO: Better handling of exceptions of socket connect
    except socket.error as v:
        logging.error("No Internet Connection!")
    finally:
        s.close()


def get_location():
    try:
        response = urllib.request.urlopen('http://freegeoip.net/xml/')
        dom = parseString(response.read())
        country = dom.getElementsByTagName('CountryName')[0].childNodes[0].data
        city = dom.getElementsByTagName('City')[0].childNodes[0].data
        country_code = dom.getElementsByTagName('CountryCode')[0].childNodes[0].data
        return city + ', ' + country + ' ' + country_code
    except:
        return '?'
