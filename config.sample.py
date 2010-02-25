import os.path
FEEDEX_ROOT = os.path.dirname(os.path.abspath(__file__))

NICKNAME_LIST = ['FedEx']
DEBUG_MODE = True

SERVER_LIST = [
    ('irc.hanirc.org', 6665),
]
USE_SSL = False
MAX_CHAR = 300
BUFFER_PERIOD = 1

FETCH_PERIOD = 3
FREQUENT_FETCH_PERIOD = 20
FUTURE_THRESHOLD = 86400
TIMEZONE = 9
