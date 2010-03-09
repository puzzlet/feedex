#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
import imp
import time
import itertools
import traceback
from collections import defaultdict

import irclib

import BufferingBot

from util import trace, force_unicode
import config

def periodic(period):
    """Decorate a class instance method so that the method would be
    periodically executed by irclib framework.
    """
    def decorator(fun):
        def new_fun(self, *args):
            try:
                fun(self, *args)
            except StopIteration:
                return
            finally:
                self.ircobj.execute_delayed(period, new_fun, (self,) + args)
        return new_fun
    return decorator

class FeedBot(BufferingBot.BufferingBot):
    def __init__(self, server_list, nick_list, realname,
                 reconnection_interval=60, use_ssl=False):
        BufferingBot.BufferingBot.__init__(self, server_list, nick_list[0],
            realname, reconnection_interval=reconnection_interval,
            buffer_timeout=-1, # don't use timeout
            use_ssl=use_ssl)
        self.initialized = False
        self.connection.add_global_handler('welcome', self._on_connected)
        self.connection.add_global_handler('privmsg', self._on_msg, 0)

        self.autojoin_channels = set()
        self.feeds = defaultdict(list)
        self.feed_iter = itertools.cycle(self.feeds)
        self.use_ssl = use_ssl
        self.last_checked = {}
        self.handlers = []
        self.frequent_fetches = {}

        self.reload_feed()

    def _on_connected(self, conn, _):
        trace('Connected.')
        try:
            for channel in self.autojoin_channels:
                self.connection.join(channel.encode('utf-8'))
        except: #TODO: specify exception here
            pass
        if self.initialized:
            return
        if conn != self.connection:
            return
        self.ircobj.execute_delayed(0, self.iter_feed)
        self.initialized = True

    def _on_msg(self, conn, event):
        if conn != self.connection:
            return
        if irclib.is_channel(event.target()):
            return
        nickname = irclib.nm_to_n(event.source())
        argv = event.arguments()[0].decode('utf8', 'ignore').split(' ')
        if argv[0] == r'\reload':
            self.reload_feed()
            msg = 'Reload successful - %d feeds' % len(self.feeds)
            self.connection.privmsg(nickname, msg)
        elif argv[0] == r'\dump':
            print '\n-- dump buffer --\n'
            self.buffer.dump()

    @periodic(config.FREQUENT_FETCH_PERIOD)
    def frequent_fetch(self, fetcher):
        if fetcher not in self.frequent_fetches:
            raise StopIteration()
        if not self.frequent_fetches[fetcher]:
            raise StopIteration()
        self.fetch_feed(fetcher)

    @periodic(config.FETCH_PERIOD)
    def iter_feed(self):
        if not self.feeds:
            return
        if self.feed_iter is None:
            self.feed_iter = itertools.cycle(self.feeds)
        try:
            fetcher = self.feed_iter.next()
        except StopIteration:
            self.feed_iter = itertools.cycle(self.feeds)
            fetcher = self.feed_iter.next()
        except RuntimeError:
            # RuntimeError: dictionary changed size during iteration
            self.feed_iter = itertools.cycle(self.feeds)
            fetcher = self.feed_iter.next()
        self.fetch_feed(fetcher)

    def fetch_feed(self, fetcher):
        if config.DEBUG_MODE:
            trace('Trying to parse from %s' % fetcher.uri)
        try:
            entries = fetcher.get_fresh_entries()
        except Exception:
            traceback.print_exc()
            return
        for formatter in self.feeds[fetcher]:
            try:
                for target, msg, opt in formatter.format_entries(entries):
                    trace('New message from %s: %s' % (fetcher.uri, msg))
                    message = BufferingBot.Message('privmsg',
                        (target, msg), opt.get('timestamp', None))
                    self.push_message(message)
            except Exception:
                traceback.print_exc()
                return
        if entries:
            fetcher.update_timestamp(entries)

    def push_message(self, message):
        arguments = tuple(_.encode('utf8', 'xmlcharrefreplace')
            for _ in message.arguments)
        message = BufferingBot.Message(message.command, arguments,
            message.timestamp)
        BufferingBot.BufferingBot.push_message(self, message)

    def pop_buffer(self, message_buffer):
        print '\r%d message(s) in the buffer' % len(message_buffer)
        message = message_buffer.peek()
        if message.timestamp > time.time():
            # 미래에 보여줄 것은 미래까지 기다림
            # TODO: ignore_time이면 이 조건 무시
            return
        BufferingBot.BufferingBot.pop_buffer(self, message_buffer)

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
                self.frequent_fetches[fetcher] = enabled

    def reload_feed_handlers(self):
        handler_names = []
        import_path = os.path.join(config.FEEDEX_ROOT, 'feeds')
        for file_name in os.listdir(import_path):
            if file_name.endswith('.py') and not file_name.startswith('__'):
                handler_names.append(file_name[:-3])
        self.handlers = []
        self.autojoin_channels = set()
        for handler_name in handler_names:
            try:
                file_obj, filename, opt = imp.find_module(handler_name,
                    [import_path])
            except ImportError:
                traceback.print_exc()
                continue
            try:
                module = imp.load_module(handler_name, file_obj, filename, opt)
                self.handlers.append({
                    '__name__': handler_name,
                    'manager': module.manager,
                })
            except Exception:
                traceback.print_exc()
            finally:
                if file_obj:
                    file_obj.close()

    def reload_feed_data(self):
        self.feed_iter = None
        self.feeds = defaultdict(list)
        self.autojoin_channels = set()
        self.frequent_fetches = {}
        for handler in self.handlers:
            manager = handler['manager']
            try:
                for fetcher, formatter in manager.load():
                    self.feeds[fetcher].append(formatter)
                    self.autojoin_channels.add(formatter.target)
                    if fetcher.frequent:
                        self.frequent_fetches[fetcher] = True
            except Exception:
                traceback.print_exc()
                continue
            trace('%s loaded successfully.' % handler['__name__'])
        if config.DEBUG_MODE:
            trace(self.autojoin_channels)
        for channel in self.channels:
            channel = force_unicode(channel)
            if channel not in self.autojoin_channels:
                self.connection.part(channel.encode('utf-8'))

def main():
    bot = FeedBot(
        server_list=config.SERVER_LIST,
        nick_list=config.NICKNAME_LIST,
        realname='FeedEx the feed bot',
        use_ssl=config.USE_SSL)
    bot.start()

if __name__ == '__main__':
    main()

