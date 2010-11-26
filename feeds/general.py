#coding: utf-8
import calendar
import datetime
import email.utils
import os
import re
import time
import traceback
import urllib.parse
from collections import defaultdict

import feedparser
import yaml

from util import limit_time
from util import rfc2timestamp, tuple2rfc
from util import LocalTimezone

FILE_PATH = os.path.dirname(__file__)
FUTURE_THRESHOLD = seconds=86400
TIMEOUT_THRESHOLD = 30
MAX_CHAR = 300

def get_updated(entry, default=None):
    """Returns updated time of the entry, in unix timestamp.
    default -- current time if None
    """
    try:
        result = entry.get('updated_parsed', None)
        if result:
            # assuming entry.updated_parsed is in UTC
            return calendar.timegm(result)
    except AttributeError:
        pass
    if default is not None:
        return default
    else:
        return time.time()

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
        return os.path.join(FILE_PATH, '../cache',
            urllib.parse.quote(self.uri, ''))

    def load_cache(self):
        file_name = self._get_cache_filename()
        if not os.access(file_name, os.F_OK):
            self.initialize_cache()
            return
        try:
            data = yaml.load(open(file_name, 'r'))
            if data:
                self.main_link = str(data.get('link', ''))
                self.entries = data.get('entries', []) if data else []
                for entry in self.entries or []:
                    if 'updated' in entry:
                        entry['updated'] = email.utils.parsedate(entry['updated'])
                self.last_confirmed = rfc2timestamp(data.get('last-confirmed', None), 0)
                self.last_modified = rfc2timestamp(data.get('last-modified', None), 0)
                self.etag = data.get('etag', '')
        except Exception:
            traceback.print_exc()
        self.initialized = True

    def save_cache(self, entries):
        """Save the feed's information into the cache file.
        Entries timestamped at future are not saved, unless ignore_time is set.
        entries -- save only these entries, to prevent the cache from being
                   flooded with all the older entries.
        """
        now = time.time() + FUTURE_THRESHOLD
        data = {}
        data['uri'] = self.uri
        if self.main_link:
            data['link'] = self.main_link
        if self.last_modified:
            data['last-modified'] = email.utils.formatdate(self.last_modified)
        if self.last_confirmed:
            data['last-confirmed'] = email.utils.formatdate(self.last_confirmed)
        if self.etag:
            data['etag'] = self.etag
        data['entries'] = []
        for entry in entries:
            if not self.ignore_time and get_updated(entry) > now:
                continue
            entry_data = entry.copy()
            if 'updated_parsed' in entry:
                entry_data['updated'] = tuple2rfc(entry['updated_parsed'])
            data['entries'].append(entry_data)
        yml = yaml.dump(data,
                        default_flow_style=False,
                        encoding='utf-8',
                        allow_unicode=True)
        open(self._get_cache_filename(), 'wb+').write(yml)
        self.entries = data['entries']

    def initialize_cache(self):
        self.last_confirmed = time.time()
        self.save_cache([])
        self.initialized = True

    def is_entry_fresh(self, entry):
        if not self.ignore_time and 'updated_parsed' in entry:
            now = time.time() + FUTURE_THRESHOLD
            return self.last_confirmed < get_updated(entry) < now
        if 'id' in entry:
            return all(entry['id'] != _.get('id', None) for _ in self.entries)
        # TODO: title-link pair might be smarter
        if 'title' in entry:
            title = entry['title']
            return all(title != _.get('title', None) for _ in self.entries)
        if 'link' in entry:
            link = entry['link']
            return all(link != _.get('link', None) for _ in self.entries)
        return True

    @limit_time(TIMEOUT_THRESHOLD)
    def _parse_feed(self):
        try:
            kwargs = {}
            kwargs['referrer'] = self.main_link
            if self.etag:
                kwargs['etag'] = self.etag
            if self.last_modified:
                kwargs['modified'] = time.gmtime(self.last_modified)
            return feedparser.parse(self.uri, **kwargs)
        except Exception:
            print('An error occured while trying to get %s:' % self.uri)
            traceback.print_exc(limit=None)

    def get_fresh_entries(self):
        if not self.initialized:
            self.load_cache()
        entries = self.get_entries()
        # TODO: remove duplicate
        all_entries = (entries or []) + (self.entries or [])
        fresh_entries = [_ for _ in all_entries if self.is_entry_fresh(_)]
        if not fresh_entries:
            return []
        self.save_cache(entries)
        return fresh_entries

    def get_entries(self):
        feed = self._parse_feed()
        if not feed or not feed['entries']:
            return []
        self.main_link = feed.get('link', None)
        self.etag = feed.get('etag', None)
        if 'updated' in feed:
            self.last_modified = time.mktime(feed['updated'])
        return feed['entries']

    def update_timestamp(self, entries):
        if not entries:     
            return  
        latest = max(get_updated(entry) for entry in entries)
        if latest > self.last_confirmed:     
            self.last_confirmed = latest
        self.save_cache(self.entries)

class EntryFormatter(object):
    """format feed entry into an irc packet."""

    def __init__(self, targets, message_format, arguments=None, digest=False,
            exclude=[]):
        self.targets = targets
        if not isinstance(self.targets, list):
            self.targets = [self.targets]
        self.message_format = message_format
        self.arguments = arguments or {}
        self.digest = digest
        self.exclude = exclude

    def format_entry(self, entry):
        for pattern in self.exclude:
            if re.match(pattern, entry['title']):
                return
        msg = self.message_format % self.build_arguments(entry)
        opt = {
            'timestamp': get_updated(entry)
        }
        return (msg, opt)

    def format_entries(self, entries):
        if self.digest:
            for result in self.digest_entries(entries):
                yield result
        else:
            for entry in entries or []:
                x = self.format_entry(entry)
                if not x:
                    continue
                message, opt = x
                for target in self.targets:
                    yield target, message, opt

    def digest_entries(self, entries):
        msg_buffer = ''
        delimiter = ' | '
        titles = set()
        for entry in entries:
            args = self.build_arguments(entry)
            match = re.match(r'(?P<title>.*?)(\(.+\))?(\.\w+)?', args['title'])
            titles.add(match.group('title'))
        for title in titles:
            if not title:
                continue
            msg = '\x02%s\x02' % title
            if len(msg_buffer) + len(delimiter) + len(msg) > MAX_CHAR:
                for target in self.targets:
                    yield (target, msg_buffer, {})
                msg_buffer = ''
            msg_buffer += delimiter if msg_buffer else '[%(name)s]' % args # XXX
            msg_buffer += msg
            if len(msg_buffer) > MAX_CHAR:
                for target in self.targets:
                    yield (target, msg_buffer, {})
                msg_buffer = ''
        if msg_buffer:
            for target in self.targets:
                yield (target, msg_buffer, {})

    def build_arguments(self, entry):
        result = defaultdict(str)
        for key, val in self.arguments.items():
            result[key] = val
        result['link'] = entry.get('link', '')
        if 'updated_parsed' not in entry:
            result['time'] = 'datetime unknown'
        else:
            result['time'] = datetime.datetime.fromtimestamp(
                get_updated(entry),
                tz=LocalTimezone()).isoformat(' ')
        if 'title' in entry:
            result['title'] = entry['title'].replace('\n', ' ')
        return result

class FeedManager(object):
    def __init__(self, file_path, fetcher_class=FeedFetcher,
                 formatter_class=EntryFormatter):
        self.file_path = os.path.join(FILE_PATH, file_path)
        self.fetcher_class = fetcher_class
        self.formatter_class = formatter_class
        self.fetcher = {}

    def load(self):
        self.fetcher = {}
        formats = self.load_formats()
        data = self.load_data()
        if not data:
            return
        for entry in data:
            if 'format' in entry and entry['format'] in formats:
                entry['format'] = formats[entry['format']]
            key = self._get_entry_key(entry)
            if key not in self.fetcher:
                self.fetcher[key] = self.fetcher_class(
                    uri=entry['uri'],
                    ignore_time = entry.get('ignore_time', False),
                    frequent = entry.get('frequent', False)
                )
            formatter = self.formatter_class(
                targets=entry['targets'],
                message_format=entry['format'],
                arguments={'name': entry['name']},
                digest=entry.get('digest', False),
                exclude=entry.get('exclude', []),
            )
            yield (self.fetcher[key], formatter)

    def _get_entry_key(self, entry):
        return (entry['uri'], entry.get('ignore_time', False))

    def load_data(self):
        if not os.access(self.file_path, os.F_OK):
            return None
        try:
            return yaml.load(open(self.file_path).read())
        except Exception:
            traceback.print_exc()

    def load_formats(self):
        return yaml.load(open(os.path.join(FILE_PATH, 'format.yml')))

    def reload(self):
        fetcher_old = self.fetcher
        self.fetcher = {}
        formats = self.load_formats()
        data = self.load_data()

manager = FeedManager('general.yml')

