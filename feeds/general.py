#coding: utf-8
import os.path
import re
import time
import calendar
import datetime
from util import force_unicode, parse_feed, trace
from util import TimedOutException, KoreanStandardTime
try: # preparing for Python 3.0
    from urllib.parse import quote
except ImportError:
    from urllib import quote
from config import DEBUG_MODE

FILE_PATH = os.path.dirname(__file__)

class FeedFetcher(object):
    def __init__(self, uri, ignore_time=False):
        self.uri = uri
        self.ignore_time = ignore_time
        self.timestamp = 0
        self.id_set = set() # {}
        self.load_timestamp()

    def _get_timestamp_filename(self):
        return os.path.join(FILE_PATH, '../timestamps', quote(self.uri, ''))

    def load_timestamp(self):
        now = time.time()
        file_name = self._get_timestamp_filename()
        if not os.access(file_name, os.F_OK):
            self.last_updated = now
            self.save_timestamp()
            return
        try:
            f = open(file_name, 'r')
            timestamp = float(f.next().strip())
            for line in f:
                id = line.strip()
                if not id:
                    continue
                self.id_set.add(id)
            f.close()
            if timestamp > now: # + config.FUTURE_THRESHOLD:
                self.last_updated = now
                self.save_timestamp()
                return
            self.last_updated = timestamp
        except:
            pass

    def save_timestamp(self, timestamp=None):
        if timestamp is not None:
            self.last_updated = timestamp
        file_name = self._get_timestamp_filename()
        f = open(file_name, 'w+')
        f.write(str(self.last_updated))
        f.write('\n')
        f.write('\n'.join(self.id_set).encode('utf-8'))
        f.write('\n')
        f.close()

    def update_timestamp(self, entries, request_time=None):
        if request_time is None:
            request_time = time.time()
        for entry in entries:
            key = entry.get('id', None) or entry.get('link', None)
            if key:
                self.id_set.add(key)
            if entry.get('updated_parsed', None) is None:
                self.last_updated = request_time
            else:
                # assuming entry.updated_parsed is UTC
                t = calendar.timegm(entry.updated_parsed)
                if t > self.last_updated:
                    self.last_updated = t
        self.save_timestamp()

    def is_entry_fresh(self, entry):
        if DEBUG_MODE:
            return True
        if not self.ignore_time and entry.get('updated_parsed', None):
            # assuming entry.updated_parsed is UTC:
            t = calendar.timegm(entry.updated_parsed)
            return self.last_updated < t < time.time()
        if entry.get('id', None):
            return entry.id not in self.id_set
        if entry.get('link', None):
            return entry.link not in self.id_set
        return True

    def get_entries(self):
        feed = None
        fetch_time = time.time()
        try:
            feed = parse_feed(str(self.uri))
        except TimedOutException:
            trace('Timed out while parsing %s' % self.uri)
        except LookupError:
            trace('Invalid character in %s' % self.uri)
        except UnicodeDecodeError:
            trace('Invalid character in %s' % self.uri)
        if feed is None:
            return []
        feed.entries.reverse()
        fresh_entries = [entry for entry in feed.entries if self.is_entry_fresh(entry)]
        self.update_timestamp(fresh_entries, fetch_time)
        return fresh_entries

class EntryFormatter(object):
    def __init__(self, target, format, options={}):
        self.target = force_unicode(target)
        self.format = force_unicode(format)
        self.options = options

    def format_entry(self, entry):
        if entry.get('updated_parsed', None) is None:
            t = time.time()
            time_string = 'datetime unknown'
        else:
            # assuming entry.updated_parsed is UTC
            t = calendar.timegm(entry.updated_parsed)
            #XXX timezone should be customizable
            dt = datetime.datetime.fromtimestamp(t, KoreanStandardTime())
            time_string = dt.isoformat(' ')
        kwargs = self.options
        kwargs['bold'] = '\x02'
        kwargs['link'] = force_unicode(entry.get('link', ''))
        kwargs['time'] = time_string
        kwargs['title'] = force_unicode(entry.title)
        opt = {
            'timestamp': t
        }
        return (self.target, self.format % kwargs, opt)

    def format_entries(self, entries):
        for entry in entries:
            result = self.format_entry(entry)
            if result:
                yield result

def load():
    format = {}
    for line in open(os.path.join(FILE_PATH, 'format'), 'r'):
        line = line.strip().decode('utf-8')
        if line.startswith('#'):
            continue
        if ' ' not in line:
            continue
        tokens = re.split(r'\s\s+', line, 1)
        format[tokens[0]] = tokens[1]
    result = []
    fetcher = {}
    for line in open(os.path.join(FILE_PATH, 'general.data'), 'r'):
        line = line.strip().decode('utf-8')
        if line.startswith('#'):
            continue
        if not line:
            continue
        tokens = re.split(r'\s\s+', line)
        for uri, flag_string, formatter in parse(tokens, format):
            if (uri, flag_string) not in fetcher:
                flag = parse_flag_string(flag_string)
                fetcher[(uri, flag_string)] = FeedFetcher(
                    uri = uri,
                    ignore_time = flag.get('ignore_time', False)
                )
            result.append((fetcher[(uri, flag_string)], formatter))
    return result

def parse_flag_string(s):
    result = {}
    for token in s.split(','):
        key, _, value = token.partition('=')
        if _:
            result[key] = value
        else:
            result[key] = True
    return result

def parse(argv, format):
    flag = parse_flag_string(argv[2])
    if 'format' in flag:
        flag['format'] = format[flag['format']]
    flag_string = []
    for key, value in sorted(flag.items()):
        if key == 'format':
            continue
        flag_string.append('%s=%s' % (key, value))
    flag_string = ','.join(flag_string)
    for target in argv[1].split(','):
        formatter = EntryFormatter(
            target=target.strip(),
            format=flag['format'],
            options={'name': argv[0]}
        )
        yield (argv[3], flag_string, formatter)


channels = set()
for fetcher, formatter in load():
    channels.add(formatter.target)

