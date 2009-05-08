import sys
import traceback
import signal
import time
import chardet
import datetime 

import feedparser

def trace(str):
    print('[%s] %s' % (time.strftime('%m %d %H:%M:%S'), str))

class KoreanStandardTime(datetime.tzinfo):
    def utcoffset(self, dt):
        return datetime.timedelta(hours=9)

    def dst(self, dt):
        return datetime.timedelta(0)

    def tzname(self, dt):
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
            e = None
            try:
                result = f(*args, **kwargs)
            except Exception, e:
                type, value, tb = sys.exc_info()
            finally:
                signal.signal(signal.SIGALRM, old)
            signal.alarm(0)
            if e:
                traceback.print_tb(tb)
                print e
                raise e
            return result
        
        new_f.func_name = f.func_name
        return new_f

    return decorate

@limit_time(3)
def parse_feed(*args, **kwargs):
    #XXX need to cache the feeds and request with ETag, etc.
    return feedparser.parse(*args, **kwargs)

def force_unicode(str, encoding=''):
    if type(str) == unicode:
        return str
    if not encoding:
        encoding = chardet.detect(str)['encoding']
    if not encoding:
        print "Cannot find encoding for %s" % repr(str)
        return "?"
    return str.decode(encoding, 'ignore')

