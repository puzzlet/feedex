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

def trace(message):
    print('[%s] %s' % (time.strftime('%m %d %H:%M:%S'), message))

class KoreanStandardTime(datetime.tzinfo):
    def utcoffset(self, _):
        return datetime.timedelta(hours=9)

    def dst(self, _):
        return datetime.timedelta(0)

    def tzname(self, _):
        return '+0900'

class TimedOutException(Exception):
    def __init__(self, value = "Timed Out"):
        self.value = value

    def __str__(self):
        return repr(self.value)

def limit_time(timeout_duration):
    # from http://code.activestate.com/recipes/473878/
    def decorate(func):
        def new_func(*args, **kwargs):
            class InterruptableThread(threading.Thread):
                def __init__(self):
                    threading.Thread.__init__(self)
                    self.result = None
                def run(self):
                    self.result = func(*args, **kwargs)
            it = InterruptableThread()
            it.start()
            it.join(timeout_duration)
            if it.isAlive():
                return it.result
            return it.result
        new_func.__name__ = func.__name__
        return new_func
    return decorate

def rfc2timestamp(rfc, default=0):
    if rfc:
        return calendar.timegm(email.utils.parsedate(rfc))
    else:
        return default

def tuple2rfc(time_tuple):
    return email.utils.formatdate(calendar.timegm(time_tuple))

def to_datetime(t):
    if not t:
        return None
    if isinstance(t, str):
        x = email.utils.parsedate(t)
        if not x:
            x = feedparser._parse_date(t)
        t = x
    if isinstance(t, (tuple, time.struct_time)):
        t = time.mktime(t)
    if isinstance(t, (int, float)):
        t = datetime.datetime.fromtimestamp(t)
    if not isinstance(t, datetime.datetime):
        raise ValueError(repr(t))
    return t

