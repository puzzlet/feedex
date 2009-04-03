#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import imp
import os
import datetime
import time
try: # preparing for Python 3.0
    from urllib.parse import quote
except ImportError:
    from urllib import quote
from collections import defaultdict

import feedparser
from irclib import is_channel, nm_to_n
from ircbot import SingleServerIRCBot as Bot
from ircbot import ServerConnectionError

from util import *
import config

@timed_out(3)
def parse_feed(*args, **kwargs):
    return feedparser.parse(*args, **kwargs)

def make_periodic(period):
    def decorator(f):
        def new_f(self, *args):
            try:
                f(self, *args)
            finally:
                self.ircobj.execute_delayed(period, new_f, (self,) + args)
        return new_f
    return decorator

class FeedHandler:
    def __init__(self, uri):
        self.uri = uri
        self.timestamp = 0
        self.id_set = set() # {}
        self.load_timestamp()

    def load_timestamp(self):
        now = time.time()
        file_name = os.path.join(config.FEEDEX_ROOT, 'timestamps', quote(self.uri, ''))
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

    def save_timestamp(self):
        path = os.path.join(config.FEEDEX_ROOT, 'timestamps', quote(self.uri, ''))
        f = open(path, 'w+')
        f.write(str(self.last_updated))
        f.write('\n')
        f.write('\n'.join([id for id in self.id_set]))
        f.close()

    def is_entry_fresh(self, entry):
        if entry.get('updated_parsed', None):
            t = time.mktime(entry.updated_parsed)
            return t > self.last_updated
        if entry.id in self.id_set:
            return False
        return True

    def get_entries(self):
        try:
            feed = parse_feed(self.uri)
        except TimedOutException:
            trace('Timed out while parsing %s' % self.uri)
            return []
        except LookupError:
            trace('Invalid character in %s' % self.uri)
            return []
        except UnicodeDecodeError:
            trace('Invalid character in %s' % self.uri)
            return []
        fresh_entries = [entry for entry in feed.entries if self.is_entry_fresh(entry)]
        max_timestamp = 0
        for entry in fresh_entries:
            if entry.get('id', None):
                self.id_set.add(entry.id)
            if entry.get('updated_parsed', None):
                t = time.mktime(entry.updated_parsed)
                if t > max_timestamp:
                    max_timestamp = t
            else:
                max_timestamp = time.time()
        self.save_timestamp()
        return fresh_entries

class FeedBot(Bot):
    def __init__(self, server_list, nick_list, realname, reconnection_interval=60, use_ssl=False):
        Bot.__init__(self, server_list, nick_list[0], realname, reconnection_interval)
        self.initialized = False
        self.connection.add_global_handler('welcome', self._on_connected)
        self.connection.add_global_handler('privmsg', self._on_msg, 0)

        self.autojoin_channels = set()
        self.feeds = defaultdict(list)
        self.use_ssl = use_ssl
        self.last_checked = {}
        self.buffer = []

        self.reload_feed()

    def _connect(self):
        """overrides Bot._connect()"""
        password = None
        if len(self.server_list[0]) > 2:
            password = self.server_list[0][2]
        try:
            self.connect(self.server_list[0][0],
                         self.server_list[0][1],
                         self._nickname,
                         password,
                         ircname=self._realname,
                         ssl=self.use_ssl)
        except ServerConnectionError:
            pass

    def _on_connected(self, c, e):
        self.spew('Connected.')
        try:
            if config.DEBUG_MODE:
                self.connection.join('#feedex')
            else:
                for channel in self.autojoin_channels:
                    self.connection.join(channel.encode('utf-8'))
        except: #TODO: specify exception here
            pass
        if self.initialized:
            return
        if c != self.connection:
            return
        self.ircobj.execute_delayed(0, self.iter_feed)
        self.ircobj.execute_delayed(0, self.send_buffer)
        self.initialized = True

    def _on_msg(self, c, e):
        if c != self.connection:
            return
        if is_channel(e.target()):
            return
        nickname = nm_to_n(e.source())
        argv = e.arguments()[0].decode('utf8', 'ignore').split(' ')
        if argv[0] == r'\reload':
            self.reload_feed()
            msg = 'Reload successful - %d feeds' % len(self.feeds)
            self.connection.privmsg(nickname, msg)

    @make_periodic(config.FREQUENT_FETCH_PERIOD)
    def frequent_fetch(self, uri):
        self.fetch_feed(uri)
        return

    @make_periodic(config.FETCH_PERIOD)
    def iter_feed(self):
        if not self.feeds:
            return
        if getattr(self, 'feed_iter', None) is None:
            self.feed_iter = self.feeds.iterkeys()
        try:
            uri = self.feed_iter.next()
        except StopIteration:
            self.feed_iter = self.feeds.iterkeys()
            uri = self.feed_iter.next()
        self.fetch_feed(uri)

    def fetch_feed(self, uri):
        timestamps = []
        handler = FeedHandler(uri)
        for entry in handler.get_entries():
            if entry.get('updated_parsed', None):
                t = time.mktime(entry.updated_parsed)
                time_string = datetime.datetime.fromtimestamp(t, KoreanStandardTime()).isoformat(' ')
            else:
                t = time.time()
                time_string = ''
            for x in self.feeds[uri]:
                kwargs = dict(x['data'])
                kwargs['time'] = time_string
                result = x['handler']['display'](entry, kwargs)
                if not result:
                    continue
                target, msg, opt = result
                opt['uri'] = uri
                opt['timestamp'] = t
                opt['callback'] = [] #[self.feed_callback]
                self.buffer.append((target, msg, opt))

    @make_periodic(config.BUFFER_PERIOD)
    def send_buffer(self):
        if not self.buffer:
            return
        self.buffer.sort(key=lambda _:_[2]['timestamp'])
        target, msg, opt = self.buffer[0]
        now = time.time()
        if opt['timestamp'] > now: # 미래에 보여줄 것은 미래까지 기다림
            return
        if config.DEBUG_MODE:
            msg = '%s %s' % (target, msg)
            target = '#feedex'
        msg = force_unicode(msg)
        msg = msg.encode('utf8', 'xmlcharrefreplace')
        target = force_unicode(target).encode('utf8')
        try:
            self.connection.privmsg(target, msg)
            self.buffer.pop(0)
        except:
            return
        for f in opt.get('callback', {}):
            f(target, msg, opt)
        self.save_timestamp(opt['uri'], now)

    def spew(self, msg):
        try:
            msg = force_unicode(msg)
        finally:
            pass
        try:
            if config.DEBUG_MODE:
                self.connection.privmsg('#feedex', msg.encode('utf-8'))
            else:
                print(msg.encode('utf-8'))
        except:
            return

    def feed_callback(self, target, msg, opt):
        self.spew('%s %s' % (target, msg))
        return

    def load_timestamp(self, uri):
        now = time.time()
        file_name = os.path.join(config.FEEDEX_ROOT, 'timestamps', quote(uri, ''))
        if not os.access(file_name, os.F_OK):
            self.save_timestamp(uri, now)
            return now
        try:
            f = open(file_name, 'r')
            result = float(f.read())
            f.close()
            if result > now: # + config.FUTURE_THRESHOLD:
                self.save_timestamp(uri, now)
                return now
            return result
        except:
            pass
        return now

    def save_timestamp(self, uri, timestamp):
        path = os.path.join(config.FEEDEX_ROOT, 'timestamps', quote(uri, ''))
        f = open(path, 'w+')
        f.write(str(timestamp))
        f.close()

    def reload_feed(self):
        self.handlers = []
        self.reload_feed_handlers()
        self.reload_feed_data()
        if self.initialized:
            for channel in self.autojoin_channels:
                self.connection.join(channel.encode('utf-8'))

    def reload_feed_handlers(self):
        handler_names = []
        import_path = os.path.join(config.FEEDEX_ROOT, 'feeds')
        for x in os.listdir(import_path):
            if x.endswith('.py'):
                handler_names.append(x[:-3])
        self.handlers = []
        self.autjoin_channels = set()
        for handler_name in handler_names:
            try:
                fp, filename, opt = imp.find_module(handler_name, [import_path])
            except ImportError:
                continue
            try:
                m = imp.load_module(handler_name, fp, filename, opt)
                self.handlers.append({
                    '__name__': handler_name,
                    'load': m.load,
                    'display': m.display,
                    'channels': m.channels,
                    'frequent': getattr(m, 'frequent', False),
                    })
                self.autojoin_channels.update(m.channels)
            except AttributeError:
                continue
            finally:
                if fp:
                    fp.close()

    def reload_feed_data(self):
        self.feed_iter = None
        self.feeds = defaultdict(list)
        for handler in self.handlers:
            uri_set = set()
            data_list = handler['load']()
            for uri, data in data_list:
                self.feeds[uri].append({
                    'handler': handler,
                    'data': data,
                })
                uri_set.add(uri)
            if handler['frequent']:
                for uri in uri_set:
                    pass
                    self.ircobj.execute_delayed(0, self.frequent_fetch, (uri,))
            self.spew('%s loaded successfully.' % handler['__name__'])

####

if __name__ == '__main__':
    CHANNELS = ['#snucse-feed', '#snucse_18+']
    bot = FeedBot(
            server_list=config.SERVER_LIST,
            nick_list=config.NICKNAME_LIST,
            realname='FeedEx the feed bot',
            use_ssl=config.USE_SSL
            )
    bot.start()

