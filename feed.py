#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import imp
import os
import datetime
from time import time, mktime 
from urllib import quote
from collections import defaultdict

import feedparser
from ircbot import SingleServerIRCBot as Bot
from ircbot import ServerConnectionError

from util import *
from config import *

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

class FeedBot(Bot):
    def __init__(self, server_list, nick_list, realname, reconnection_interval=60, use_ssl=False):
        Bot.__init__(self, server_list, nick_list[0], realname, reconnection_interval)
        self.initialized = False
        self.connection.add_global_handler('welcome', self._on_connected)
        self.connection.add_global_handler('pubmsg', self._on_msg, 0)

        self.autojoin_channels = set()
        self.feeds = defaultdict(list)
        self.use_ssl = use_ssl
        self.last_checked = {}
        self.buffer = []

        self.handlers = []
        self.reload_feed_handlers()
        self.reload_feed_data()

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
        trace('Connected.')
        try:
            self.connection.join('#feedex')
            for channel in self.autojoin_channels:
                self.connection.join(channel.encode('utf-8'))
        except: #TODO: specify exception here
            pass
        if self.initialized: return
        if c != self.connection: return
        self.ircobj.execute_delayed(0, self.iter_feed)
        self.ircobj.execute_delayed(0, self.send_buffer)
        self.initialized = True

    def _on_msg(self, c, e):
        if c != self.connection: return

        argv = e.arguments()[0].decode('utf8', 'ignore').split(' ')
#        if argv[0] == '@add':
#            self.on_add(e.target(), argv)

    @make_periodic(FREQUENT_FETCH_PERIOD)
    def frequent_fetch(self, uri):
        self.fetch_feed(uri)
        return
        def foo(instance):
            FeedBot.fetch_feed(instance, uri)
        return make_periodic(FETCH_PERIOD)(foo)

    @make_periodic(FETCH_PERIOD)
    def iter_feed(self):
        if not self.feeds:
            return
        try:
            uri = self.feed_iter.next()
        except StopIteration:
            self.feed_iter = self.feeds.iterkeys()
            uri = self.feed_iter.next()
        self.fetch_feed(uri)

    def fetch_feed(self, uri):
        timestamps = []
        reference_timestamp = self.load_timestamp(uri)
        if uri in self.last_checked:
            reference_timestamp = self.last_checked[uri]

        self.spew('Trying to fetch & parse %s' % uri)
        try:
            spam = parse_feed(uri)
        except TimedOutException:
            trace('Timed out.')
            return
        except LookupError:
            self.spew('Invalid character in %s' % uri)
            return
        except UnicodeDecodeError:
            self.spew('Invalid character in %s' % uri)
            return

        spam.entries.reverse()
        for entry in spam.entries:
            if not entry.get('updated_parsed', None):
                trace('Erroneous feed at %s' % uri)
                return
            t = mktime(entry.updated_parsed)
            time_string = datetime.datetime.fromtimestamp(t, KoreanStandardTime()).isoformat(' ')
            if t > reference_timestamp:
                timestamps.append(t)
                for x in self.feeds[uri]:
                    kwargs = dict(x['data'])
                    kwargs['time'] = time_string
                    result = x['handler']['display'](entry, kwargs)
                    if not result:
                        continue
                    target, msg, opt = result
                    opt['uri'] = uri
                    opt['timestamp'] = t
                    opt['callback'] = [self.feed_callback]
                    self.buffer.append((target, msg, opt))

        if timestamps:
            self.last_checked[uri] = max(timestamps)
            #self.save_timestamp(uri, max(timestamps))
            pass

        self.spew('Completed processing %s.' % uri)

    @make_periodic(BUFFER_PERIOD)
    def send_buffer(self):
        if not self.buffer:
            return
        self.buffer.sort(key=lambda _:_[2]['timestamp'])
        target, msg, opt = self.buffer[0]
        now = time.time()
        if opt['timestamp'] > now: # 10 minutes
            return
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
            if DEBUG_MODE:
                self.connection.privmsg('#feedex', msg.encode('utf-8'))
            else:
                print msg.encode('utf-8')
        except:
            return

    def feed_callback(self, target, msg, opt):
        self.spew('%s %s' % (target, msg))
        return

        # should be called after the line is popped from self.buffer
        if 'uri' not in opt: return
        uri = opt['uri']
        for t, m, o in self.buffer:
            if 'uri' not in o: continue
            if uri == o['uri']: return

        self.save_timestamp(uri, self.timestamps_temp[uri])

    def load_timestamp(self, uri):
        file_name = os.path.join(FEEDEX_ROOT, 'timestamps', quote(uri, ''))
        if not os.access(file_name, os.F_OK):
            result = time.time()
            open(file_name, 'w').write(str(result))
            return result
        try:
            f = open(file_name, 'r')
            result = float(f.read())
            f.close()
            return result
        except:
            return time()

    def save_timestamp(self, uri, timestamp):
        path = os.path.join(FEEDEX_ROOT, 'timestamps', quote(uri, ''))
        f = open(path, 'w+')
        f.write(str(timestamp))
        f.close()

    def reload_feed_handlers(self):
        handler_names = []
        import_path = os.path.join(FEEDEX_ROOT, 'feeds')
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
            trace('%s loaded successfully.' % handler['__name__'])
        self.feed_iter = self.feeds.iterkeys()

####

if __name__ == '__main__':
    CHANNELS = ['#snucse-feed', '#snucse_18+']
    bot = FeedBot(
            server_list=SERVER_LIST,
            nick_list=NICKNAME_LIST,
            realname='FeedEx the feed bot',
            use_ssl=USE_SSL
            )
    bot.start()
