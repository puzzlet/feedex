#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import imp
import os
import datetime
import time
import calendar
import itertools
try:
    # for python 3.0
    from urllib.parse import quote
except ImportError:
    from urllib import quote
from collections import defaultdict

from irclib import is_channel, nm_to_n
from ircbot import SingleServerIRCBot as Bot
from ircbot import ServerConnectionError

from util import trace, force_unicode
import config

def periodic(period):
    def decorator(f):
        def new_f(self, *args):
            try:
                f(self, *args)
            finally:
                self.ircobj.execute_delayed(period, new_f, (self,) + args)
        return new_f
    return decorator

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
        self.frequent_fetches = {}

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
        self.ircobj.execute_delayed(config.BUFFER_PERIOD, self.send_buffer)
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

    @periodic(config.FREQUENT_FETCH_PERIOD)
    def frequent_fetch(self, fetcher):
        self.fetch_feed(fetcher)
        return

    @periodic(config.FETCH_PERIOD)
    def iter_feed(self):
        if not self.feeds:
            return
        if getattr(self, 'feed_iter', None) is None:
            self.feed_iter = itertools.cycle(self.feeds)
        try:
            fetcher = self.feed_iter.next()
        except StopIteration:
            self.feed_iter = self.feeds.iterkeys()
            fetcher = self.feed_iter.next()
        except RuntimeError:
            # RuntimeError: dictionary changed size during iteration
            self.feed_iter = self.feeds.iterkeys()
            fetcher = self.feed_iter.next()
        self.fetch_feed(fetcher)

    def fetch_feed(self, fetcher):
        timestamps = []
        if config.DEBUG_MODE:
            print fetcher.uri
        entries = fetcher.get_entries()
        for formatter in self.feeds[fetcher]:
            for data in formatter.format_entries(entries):
                target, msg, opt = data
                print data
                self.buffer.append((target, msg, opt))

    @periodic(config.BUFFER_PERIOD)
    def send_buffer(self):
        if not self.buffer:
            return
        self.buffer.sort(key=lambda _:_[2].get('timestamp', 0))
        target, msg, opt = self.buffer[0]
        now = time.time()
        # 미래에 보여줄 것은 미래까지 기다림
        if opt.get('timestamp', now-1) > now:
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

    def reload_feed(self):
        self.handlers = []
        self.reload_feed_handlers()
        self.reload_feed_data()
        if self.initialized:
            for channel in self.autojoin_channels:
                channel = channel.encode('utf-8')
                if channel not in self.channels:
                    self.connection.join(channel)
            for fetcher, enabled in self.frequent_fetches.iteritems():
                self.ircobj.execute_delayed(0, self.frequent_fetch, (fetcher,))
                self.frequent_fetches[fetcher] = True

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
                    'frequent': getattr(m, 'frequent', False),
                    })
            except AttributeError:
                continue
            finally:
                if fp:
                    fp.close()

    def reload_feed_data(self):
        self.feed_iter = None
        self.feeds = defaultdict(list)
        for handler in self.handlers:
            fetcher_set = set()
            data_list = handler['load']()
            for fetcher, formatter in data_list:
                self.feeds[fetcher].append(formatter)
                fetcher_set.add(fetcher)
                self.autojoin_channels.update(formatter.target)
            if handler['frequent']:
                for fetcher in fetcher_set:
                    self.frequent_fetches[fetcher] = False
            trace('%s loaded successfully.' % handler['__name__'])

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

