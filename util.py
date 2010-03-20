import sys
import traceback
import signal
import time
import datetime 
import email.utils
import calendar

def format_time(timestamp=None):
    return time.strftime('%m %d %H:%M:%S', time.localtime(timestamp or 0))

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

def limit_time(timeout):
    # from http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/307871
    def decorate(f):
        if 'SIGALRM' not in dir(signal):
            print 'Warning: SIGALRM not supported by OS'
            return f
        def handler(signum, frame):
            raise TimedOutException()
        def new_f(*args, **kwargs):
            old = signal.signal(signal.SIGALRM, handler)
            signal.alarm(int(timeout))
            exc = None
            try:
                result = f(*args, **kwargs)
            except Exception, exc:
                _, _, tb = sys.exc_info()
            finally:
                signal.signal(signal.SIGALRM, old)
            signal.alarm(0)
            if exc:
                traceback.print_tb(tb)
                print exc
                raise exc
            return result
        new_f.func_name = f.func_name
        return new_f
    return decorate

def rfc2timestamp(rfc, default=0):
    if rfc:
        return calendar.timegm(email.utils.parsedate(rfc))
    else:
        return default

def tuple2rfc(time_tuple):
    return email.utils.formatdate(calendar.timegm(time_tuple))

