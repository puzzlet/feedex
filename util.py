import calendar
import datetime 
import email.utils
import sys
import traceback
import threading
import time

import feedparser

def format_time(timestamp=None):
    if timestamp is None:
        return time.strftime('%m %d %H:%M:%S')
    return time.strftime('%m %d %H:%M:%S', time.localtime(timestamp))

def trace(*message):
    message = ' '.join(str(_) for _ in message)
    print('[%s] %s' % (time.strftime('%m %d %H:%M:%S'), message))

class timezone(datetime.tzinfo):
    def __init__(self, td):
        self.td = td

    def utcoffset(self, dt):
        return self.td

    def dst(self, dt): 
        return datetime.timedelta(0)

UTC = timezone(datetime.timedelta(0))

def to_datetime(t, tzinfo=None):
    if not t:
        return None
    if isinstance(t, str):
        t = datetime.datetime(*feedparser._parse_date(t)[:6], tzinfo=UTC)
    tz = tzinfo or LocalTimezone()
    if isinstance(t, (tuple, time.struct_time)):
        t = datetime.datetime(*t[:6], tzinfo=tz)
    if isinstance(t, (int, float)):
        t = datetime.datetime.fromtimestamp(t, tz=tz)
    if not isinstance(t, datetime.datetime):
        raise ValueError(repr(t))
    if not t.tzinfo:
        t = datetime.datetime(*t.timetuple()[:6], tzinfo=tz)
    return t

