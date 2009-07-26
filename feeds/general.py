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
import traceback
import urllib
import yaml
import email.utils

import feedparser
import config
from util import force_unicode, parse_feed, limit_time, trace
from util import TimedOutException, KoreanStandardTime

FILE_PATH = os.path.dirname(__file__)

class FeedFetcher(object):
    def __init__(self, uri, ignore_time=False, frequent=False):
        self.uri = str(uri)
        self.ignore_time = ignore_time
        self.frequent = frequent
        self.etag = ''
        self.last_modified = 0
        self.last_confirmed = 0
        self.main_link = ''
        self.entries = []
        self.initialized = False

    def _get_cache_filename(self):
        return os.path.join(FILE_PATH, '../cache', quote(self.uri, ''))

    def load_cache(self):
        file_name = self._get_cache_filename()
        if not os.access(file_name, os.F_OK):
            self.initialize_cache()
            return
        try:
            data = yaml.load(open(file_name, 'r'))
        except:
            trace('Error loading cache data for %s' % self.uri)
        if data:
            self.main_link = str(data.get('link', ''))
            self.etag = data.get('etag', '')
            if 'last-confirmed' in data:
                if type(data['last-confirmed']) == str:
                    self.last_confirmed = calendar.timegm(email.utils.parsedate(data['last-confirmed']))
                else:
                    self.last_confirmed = data['last-confirmed']
            else:
                self.last_confirmed = 0
            if 'last-modified' in data:
                if type(data['last-modified']) == str:
                    self.last_modified = calendar.timegm(email.utils.parsedate(data['last-modified']))
                else:
                    self.last_modified = data['last-modified']
            else:
                self.last_modified = 0
            self.entries = data.get('entries', []) if data else []
            for entry in self.entries:
                if 'updated' not in entry:
                    continue
                entry['updated'] = email.utils.parsedate(entry['updated'])
        self.initialized = True

    def save_cache(self, entries = []):
        data = {}
        data['uri'] = self.uri
        if self.main_link:
            data['link'] = self.main_link
        if self.last_modified:
            data['last-modified'] = email.utils.formatdate(self.last_modified)
            # should be tuple?
        if self.last_confirmed:
            data['last-confirmed'] = email.utils.formatdate(self.last_confirmed)
        if self.etag:
            data['etag'] = self.etag
        data['entries'] = []
        for entry in entries:
            entry_data = {}
            if entry.has_key('id'):
                entry_data['id'] = entry['id']
            if entry.has_key('title'):
                entry_data['title'] = entry['title']
            if entry.has_key('link'):
                entry_data['link'] = entry['link']
            if entry.get('updated_parsed', None):
                entry_data['updated'] = email.utils.formatdate(calendar.timegm(entry['updated_parsed']))
            data['entries'].append(entry_data)
        yml = yaml.dump(data, default_flow_style=False, encoding='utf-8', allow_unicode=True)
        f = open(self._get_cache_filename(), 'w+').write(yml)
        self.entries = data['entries']

    def initialize_cache(self):
        self.save_cache()

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
        if not self.initialized:
            self.load_cache()
        if not self.ignore_time and entry.get('updated_parsed', None):
            # assuming entry.updated_parsed is UTC:
            t = calendar.timegm(entry.get('updated_parsed', 0))
            return self.last_confirmed < t < time.time() + config.FUTURE_THRESHOLD
        if entry.has_key('id'):
            return all(entry.id != _.get('id', None) for _ in self.entries)
        # TODO: title-link pair might be better
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
        if not self.initialized:
            self.load_cache()
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
        if not fresh_entries:
            return []
        self.update_timestamp(fresh_entries, fetch_time)
        self.save_cache(feed.entries)
        return fresh_entries

class EntryFormatter(object):
    def __init__(self, target, format, options={}):
        self.target = force_unicode(target)
        self.format = force_unicode(format)
        self.options = options

    def format_entry(self, entry):
        msg = self.format % self.build_arguments(entry)
        opt = {
            # assuming entry.updated_parsed is UTC
            'timestamp': calendar.timegm(entry['updated_parsed']) if entry.has_key('updated_parsed') else time.time()
        }
        return (self.target, msg, opt)

    def format_entries(self, entries):
        for entry in entries:
            result = self.format_entry(entry)
            if result:
                yield result

    def build_arguments(self, entry):
        result = defaultdict(unicode)
        for key, val in self.options.iteritems():
            result[key] = val
        result['bold'] = '\x02'
        result['link'] = force_unicode(entry.get('link', ''))
        if not entry.has_key('updated_parsed'):
            result['time'] = 'datetime unknown'
        else:
            t = calendar.timegm(entry['updated_parsed'])
            # XXX timezone should be customizable
            dt = datetime.datetime.fromtimestamp(t, KoreanStandardTime())
            result['time'] = dt.isoformat(' ')
        result['title'] = force_unicode(entry['title']).replace(u'\n', ' ')
        return result

class FeedManager(object):
    def __init__(self, file_path, fetcher_class=FeedFetcher, formatter_class=EntryFormatter):
        self.file_path = os.path.join(FILE_PATH, file_path)
        self.fetcher_class = fetcher_class
        self.formatter_class = formatter_class

    def load(self):
        fetcher = {}
        format = self.load_formats()
        for token in self.parse(self.file_path):
            name, targets, flag_string, uri = token
            flag = self.parse_flag_string(flag_string)
            if 'format' in flag:
                flag['format'] = format[flag['format']]
            flag_string = self.build_flag_string(flag)
            if (uri, flag_string) not in fetcher:
                fetcher[(uri, flag_string)] = self.fetcher_class(
                    uri = uri,
                    ignore_time = flag.get('ignore_time', False),
                    frequent = flag.get('frequent', False)
                )
            for target in targets.split(','):
                formatter = self.formatter_class(
                    target=target.strip(),
                    format=flag['format'],
                    options={'name': name}
                )
                yield (fetcher[(uri, flag_string)], formatter)

    def load_formats(self):
        result = {}
        for token in self.parse(os.path.join(FILE_PATH, 'format')):
            result[token[0]] = token[1]
        return result

    def parse(self, file_path):
        for line in open(file_path, 'r'):
            line = line.strip().decode('utf-8')
            if not line:
                continue
            if line.startswith('#'):
                continue
            yield re.split(r'\s\s+|\t', line)

    def parse_flag_string(self, s):
        result = {}
        for token in s.split(','):
            key, _, value = token.partition('=')
            if _:
                result[key] = value
            else:
                result[key] = True
        return result

    def build_flag_string(self, d):
        result = []
        for key, value in sorted(d.items()):
            if key =='format':
                continue
            result.append('%s=%s' % (key, value))
        return ','.join(result)

manager = FeedManager('general.data')

