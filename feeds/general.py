#coding: utf-8
import os.path
import time
import calendar
import datetime
from collections import defaultdict
import urllib
import traceback
import yaml
import email.utils
import re

import feedparser
import config
from util import force_unicode, limit_time, trace
from util import rfc2timestamp, tuple2rfc
from util import TimedOutException, KoreanStandardTime

FILE_PATH = os.path.dirname(__file__)

def get_updated(entry, default=None):
    """Returns updated time of the entry, in unix timestamp.
    default -- current time if None
    """
    if getattr(entry, 'has_key', None) and entry.has_key('updated_parsed'):
        # assuming entry.updated_parsed is in UTC
        return calendar.timegm(entry['updated_parsed'])
    elif default is not None:
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
        return os.path.join(FILE_PATH, '../cache', urllib.quote(self.uri, ''))

    def load_cache(self):
        file_name = self._get_cache_filename()
        if not os.access(file_name, os.F_OK):
            self.initialize_cache()
            return
        try:
            data = yaml.load(open(file_name, 'r'))
        except Exception:
            traceback.print_exc()
            return
        self.main_link = str(data.get('link', ''))
        self.etag = data.get('etag', '')
        self.last_confirmed = rfc2timestamp(data.get('last-confirmed', None), 0)
        self.last_modified = rfc2timestamp(data.get('last-modified', None), 0)
        self.entries = data.get('entries', []) if data else []
        for entry in self.entries:
            if 'updated' not in entry:
                continue
            entry['updated'] = email.utils.parsedate(entry['updated'])
        self.initialized = True

    def save_cache(self, entries):
        """Save the feed's information into the cache file.
        entries -- save only these entries, to prevent the cache from being
                   flooded with all the older entries.
        """
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
            entry_data = {}
            if entry.has_key('id'):
                entry_data['id'] = entry['id']
            if entry.has_key('title'):
                entry_data['title'] = entry['title']
            if entry.has_key('link'):
                entry_data['link'] = entry['link']
            if entry.get('updated_parsed', None):
                entry_data['updated'] = tuple2rfc(entry['updated_parsed'])
            data['entries'].append(entry_data)
        yml = yaml.dump(data,
                        default_flow_style=False,
                        encoding='utf-8',
                        allow_unicode=True)
        open(self._get_cache_filename(), 'w+').write(yml)
        self.entries = data['entries']

    def initialize_cache(self):
        self.last_confirmed = time.time()
        self.save_cache([])
        self.initialized = True

    def is_entry_fresh(self, entry):
        if not self.ignore_time and entry.has_key('updated_parsed'):
            now = time.time() + config.FUTURE_THRESHOLD
            return self.last_confirmed < get_updated(entry) < now
        if entry.has_key('id'):
            return all(entry['id'] != _.get('id', None) for _ in self.entries)
        # TODO: title-link pair might be smarter
        if entry.has_key('title'):
            return all(entry['title'] != _.get('title', None) for _ in self.entries)
        if entry.has_key('link'):
            return all(entry['link'] != _.get('link', None) for _ in self.entries)
        return True

    @limit_time(config.TIMEOUT_THRESHOLD)
    def _parse_feed(self):
        return feedparser.parse(
            self.uri,
            etag = self.etag,
            modified = time.gmtime(self.last_modified),
            referrer = self.main_link
        )

    def get_fresh_entries(self):
        if not self.initialized:
            self.load_cache()
        entries = self.get_entries()
        # XXX remove duplicate
        fresh_entries = [_ for _ in entries + self.entries \
            if self.is_entry_fresh(_)]
        if not fresh_entries:
            return []
        self.save_cache(entries)
        return fresh_entries

    def get_entries(self):
        feed = self._parse_feed()
        if not feed.entries:
            return []
        self.main_link = feed.get('link', None)
        self.etag = feed.get('etag', None)
        if feed.has_key('updated'):
            self.last_modified = time.mktime(feed.updated)
        return feed.entries

    def update_timestamp(self, entries, request_time=None):
        if not entries:     
            return  
        t = max(get_updated(entry) for entry in entries)
        if t > self.last_confirmed:     
            self.last_confirmed = t
        self.save_cache(self.entries)

class EntryFormatter(object):
    """format feed entry into an irc packet."""

    def __init__(self, target, format, arguments={}, digest=False):
        self.target = force_unicode(target)
        self.format = force_unicode(format)
        self.arguments = arguments
        self.digest = digest

    def format_entry(self, entry):
        msg = self.format % self.build_arguments(entry)
        opt = {
            # assuming entry.updated_parsed is UTC
            'timestamp': get_updated(entry)
        }
        return (self.target, msg, opt)

    def format_entries(self, entries):
        if self.digest:
            for result in self.digest_entries(entries):
                yield result
        else:
            for entry in entries:
                result = self.format_entry(entry)
                if result:
                    yield result

    def digest_entries(self, entries):
        buffer = ''
        delimiter = ' | '
        titles = set()
        for entry in entries:
            args = self.build_arguments(entry)
            m = re.match(r'(?P<title>.*?)(\(.+\))?(\.\w+)?', args['title'])
            titles.add(m.group('title'))
        for title in titles:
            if not title:
                continue
            msg = '\x02%s\x02' % title
            if len(buffer) + len(delimiter) + len(msg) > config.MAX_CHAR:
                yield (self.target, buffer, {})
                buffer = ''
            buffer += delimiter if buffer else '[%(name)s]' % args # XXX
            buffer += msg
            if len(buffer) > config.MAX_CHAR:
                yield (self.target, buffer, {})
                buffer = ''
        if buffer:
            yield (self.target, buffer, {})

    def build_arguments(self, entry):
        result = defaultdict(unicode)
        for key, val in self.arguments.iteritems():
            result[key] = val
        result['link'] = force_unicode(entry.get('link', ''))
        if not entry.has_key('updated_parsed'):
            result['time'] = 'datetime unknown'
        else:
            # XXX timezone should be customizable
            result['time'] = datetime.datetime.fromtimestamp(
                    get_updated(entry),
                    KoreanStandardTime()).isoformat(' ')
        result['title'] = force_unicode(entry['title']).replace(u'\n', ' ')
        return result

class FeedManager(object):
    def __init__(self, file_path, fetcher_class=FeedFetcher,
                 formatter_class=EntryFormatter):
        self.file_path = os.path.join(FILE_PATH, file_path)
        self.fetcher_class = fetcher_class
        self.formatter_class = formatter_class

    def load_data(self):
        try:
            return yaml.load(open(self.file_path).read())
        except Exception:
            traceback.print_exc()

    def load(self):
        fetcher = {}
        format = self.load_formats()
        for entry in self.load_data():
            if 'format' in entry and entry['format'] in format:
                entry['format'] = format[entry['format']]
            key = entry['uri'] + str(entry.get('ignore_time', False))
            if key not in fetcher:
                fetcher[key] = self.fetcher_class(
                    uri=entry['uri'],
                    ignore_time = entry.get('ignore_time', False),
                    frequent = entry.get('frequent', False)
                )
            for target in entry['targets']:
                formatter = self.formatter_class(
                    target=target.strip(),
                    format=entry['format'],
                    arguments={'name': entry['name']},
                    digest=entry.get('digest', False)
                )
                yield (fetcher[key], formatter)

    def load_formats(self):
        return yaml.load(open(os.path.join(FILE_PATH, 'format.yml')))

manager = FeedManager('general.yml')

