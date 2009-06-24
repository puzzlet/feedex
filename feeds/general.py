#coding: utf-8
import os.path
import re
import time
import calendar
import datetime
import itertools
from collections import defaultdict
try: # preparing for Python 3.0
    from urllib.parse import quote
except ImportError:
    from urllib import quote
import urllib
import yaml
import email.utils

import feedparser
import config
from util import force_unicode, parse_feed, limit_time, trace
from util import TimedOutException, KoreanStandardTime

FILE_PATH = os.path.dirname(__file__)

class FeedFetcher(object):
    def __init__(self, uri, ignore_time=False):
        self.uri = str(uri)
        self.ignore_time = ignore_time
        self.etag = ''
        self.last_modified = 0
        self.last_updated = 0
        self.main_link = ''
        self.entries = []
        self.load_cache()

    def _get_cache_filename(self):
        return os.path.join(FILE_PATH, '../cache', quote(self.uri, ''))

    def _get_timestamp_filename(self):
        return os.path.join(FILE_PATH, '../timestamps', quote(self.uri, ''))

    def load_cache(self):
        file_name = self._get_cache_filename()
        if not os.access(file_name, os.F_OK):
            self.load_timestamp()
            return
        try:
            print self.uri
            data = yaml.load(open(file_name, 'r'))
        except:
            trace('Error loading cache data for %s' % self.uri)
        self.main_link = data.get('link', '')
        self.etag = data.get('etag', '')
        self.last_confirmed = data.get('last-confirmed', 0)
        self.last_modified = data.get('last-modified', 0)
        self.entries = data.get('entries', [])
        return

    def load_timestamp(self):
        now = time.time()
        file_name = self._get_timestamp_filename()
        if not os.access(file_name, os.F_OK):
            self.last_confirmed = now
            self.save_timestamp()
            return
        try:
            f = open(file_name, 'r')
            timestamp = float(f.next().strip())
            f.close()
            if timestamp > now: # + config.FUTURE_THRESHOLD:
                self.last_confirmed = now
                self.save_timestamp()
                return
            self.last_confirmed = timestamp
        except:
            pass

    def save_timestamp(self, timestamp=None):
        if timestamp is not None:
            self.last_confirmed = timestamp
        file_name = self._get_timestamp_filename()
        f = open(file_name, 'w+')
        f.write(str(self.last_confirmed))
        f.write('\n')
        f.write(u'\n'.join(self.guid_set).encode('utf-8'))
        f.write('\n')
        f.close()

    def save_cache(self, entries = []):
        data = {}
        data['uri'] = self.uri
        if self.main_link:
            data['link'] = self.main_link
        if self.last_modified:
            data['last-modified'] = self.last_modified
            # should be tuple?
        if self.last_confirmed:
            data['last-confirmed'] = self.last_confirmed
        if self.etag:
            data['etag'] = self.etag
        data['entries'] = []
        for entry in entries:
            entry_data = {}
            if entry.has_key('id'):
                entry_data['id'] = entry.id
            if entry.has_key('title'):
                entry_data['title'] = entry.title
            if entry.has_key('link'):
                entry_data['link'] = entry.link
            data['entries'].append(entry_data)
        yml = yaml.dump(data, default_flow_style=False, encoding='utf-8')
        f = open(self._get_cache_filename(), 'w+').write(yml)
        self.entries = data['entries']

        self.guid_set = None
        self.title_set = None
        self.link_set = None

        return

    def update_timestamp(self, entries, request_time=None):
        if not entries:
            return
        if request_time is None:
            request_time = time.time()
        # assuming entry.updated_parsed is UTC
        t = max(calendar.timegm(entry.get('updated_parsed', time.gmtime())) for entry in entries)
        if t > self.last_confirmed:
            self.last_confirmed = t

    def is_entry_fresh(self, entry):
        if config.DEBUG_MODE:
            return True
        if not self.ignore_time and entry.get('updated_parsed', None):
            # assuming entry.updated_parsed is UTC:
            t = calendar.timegm(entry.updated_parsed)
            return self.last_confirmed < t < time.time() + config.FUTURE_THRESHOLD
        if entry.has_key('id'):
            return all(entry.id != _.get('id', None) for _ in self.entries)
        if entry.has_key('title'):
            return all(entry.title != _.get('title', None) for _ in self.entries)
        if entry.has_key('link'):
            return all(entry.link != _.get('link', None) for _ in self.entries)
        return True

    @limit_time(config.TIMEOUT_THRESHOLD)
    def _parse_feed(self):
        return feedparser.parse(
            self.uri,
            etag = self.etag,
            modified = time.gmtime(self.last_modified),
            referrer = self.main_link
        )

    def get_entries(self):
        feed = None
        fetch_time = time.time()
        try:
            feed = self._parse_feed()
        except TimedOutException:
            trace('Timed out while parsing %s' % self.uri)
        except LookupError:
            trace('Invalid character in %s' % self.uri)
        except UnicodeDecodeError:
            trace('Invalid character in %s' % self.uri)
        if feed is None:
            return []
        if not feed.entries:
            return []
        self.link = feed.get('link', None)
        self.etag = feed.get('etag', None)
        if feed.has_key('updated'):
            self.last_modified = time.mktime(feed.updated)
        feed.entries.reverse()
        fresh_entries = [entry for entry in feed.entries if self.is_entry_fresh(entry)]
        self.update_timestamp(fresh_entries, fetch_time)
        self.save_cache(feed.entries)
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
        kwargs = defaultdict(unicode)
        for key, val in self.options.iteritems():
            kwargs[key] = val
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

