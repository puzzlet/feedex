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

class LocalTimezone(datetime.tzinfo):
    ZERO = datetime.timedelta(0)
    STDOFFSET = datetime.timedelta(seconds=-time.timezone)
    DSTOFFSET = datetime.timedelta(seconds=-time.altzone)
    DSTDIFF = DSTOFFSET - STDOFFSET
    def utcoffset(self, dt):
        if self._isdst(dt):
            return self.DSTOFFSET
        else:
            return self.STDOFFSET

    def dst(self, dt):
        if self._isdst(dt):
            return self.DSTDIFF
        else:
            return self.ZERO

    def tzname(self, dt):
        return time.tzname[self._isdst(dt)]

    def _isdst(self, dt):
        tt = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
              dt.weekday(), 0, -1)
        stamp = time.mktime(tt)
        tt = time.localtime(stamp)
        return tt.tm_isdst > 0

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

