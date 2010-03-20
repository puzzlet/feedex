#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import os
import sys
import imp
import time
import itertools
import traceback
from collections import defaultdict

from BufferingBot import BufferingBot, Message

from util import trace, format_time

class FeedBot(BufferingBot):
    def __init__(self, config_file_name):
        self.config = None
        self.config_file_name = config_file_name
        self.version = -1
        self.config_timestamp = -1
        self.debug_mode = False
        self.reload()

        server = self.config['server']
        nickname = self.config['nickname']
        BufferingBot.__init__(self, [server], nickname,
            realname='FeedEx the feed bot',
            buffer_timeout=-1, # don't use timeout
            use_ssl=self.config.get('use_ssl', False))

        self.initialized = False
        self.connection.add_global_handler('welcome', self._on_connected)

        self.autojoin_channels = set()
        self.feeds = defaultdict(list)
        self.feed_iter = itertools.cycle(self.feeds)
        self.handlers = []
        self.frequent_fetches = {}

        self.reload_feed()

        self._check_config_file()

    def _get_config_time(self):
        if not os.access(self.config_file_name, os.F_OK):
            return -1
        return os.stat(self.config_file_name).st_mtime

    def _get_config_data(self):
        if not os.access(self.config_file_name, os.R_OK):
            return None
        try:
            return eval(open(self.config_file_name).read())
        except SyntaxError:
            traceback.print_exc()
        return None

    def _check_config_file(self):
        try:
            if self._get_config_time() <= self.config_timestamp:
                return
            self.reload()
        except Exception:
            traceback.print_exc()
        self.ircobj.execute_delayed(1, self._check_config_file)

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
        self.ircobj.execute_delayed(0, self._iter_feed)
        self.initialized = True

    def frequent_fetch(self, fetcher):
        if fetcher not in self.frequent_fetches:
            raise StopIteration()
        if not self.frequent_fetches[fetcher]:
            raise StopIteration()
        self.fetch_feed(fetcher)
        self.ircobj.execute_delayed(
            self.config.get('frequent_fetch_period', 20), self.frequent_fetch)

    def _iter_feed(self):
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
        self.ircobj.execute_delayed(
            self.config.get('fetch_period', 3), self._iter_feed)

    def fetch_feed(self, fetcher):
        try:
            entries = fetcher.get_fresh_entries()
        except Exception:
            traceback.print_exc()
            return
        for formatter in self.feeds[fetcher]:
            try:
                timestamps = []
                for target, msg, opt in formatter.format_entries(entries):
                    timestamp = opt.get('timestamp', None)
                    timestamps.append(timestamp)
                    message = Message('privmsg',
                        (target, msg), timestamp=timestamp)
                    print message
                    self.push_message(message)
                if self.debug_mode and timestamps:
                    print ('\r[%s] %s new message(s) from %s, '
                        'at from [%s] to [%s]' %
                        (format_time(), len(timestamps), fetcher.uri,
                        format_time(min(timestamps)),
                        format_time(max(timestamps))))
            except Exception:
                traceback.print_exc()
                return
        if entries:
            fetcher.update_timestamp(entries)

    def push_message(self, message):
        """Override BufferingBot.push_message(message)
        encodes arguments in UTF-8."""
        arguments = tuple(_.encode('utf8', 'xmlcharrefreplace')
            for _ in message.arguments)
        message = Message(message.command, arguments, message.timestamp)
        BufferingBot.push_message(self, message)

    def pop_buffer(self, message_buffer):
        earliest = message_buffer.peek().timestamp
        if self.debug_mode:
            print('\r[%s] %d message(s) in the buffer starting from [%s]' %
                (format_time(), len(message_buffer), format_time(earliest)))
        if earliest > time.time():
            # 미래에 보여줄 것은 미래까지 기다림
            # TODO: ignore_time이면 이 조건 무시
            return False
        BufferingBot.pop_buffer(self, message_buffer)

    def process_message(self, message):
        if self.debug_mode:
            print '\r[%s] %s %s' % (format_time(), message.command,
                ' '.join(message.arguments))
        BufferingBot.process_message(self, message)

    def load(self):
        data = self._get_config_data()
        if self.version >= data['version']:
            return False
        self.config = data
        self.config_timestamp = os.stat(self.config_file_name).st_mtime
        self.version = data['version']
        self.debug_mode = data.get('debug', False)
        return True

    def reload(self):
        if not self.load():
            return False
        trace("reloading...")
        self.reload_feed()
        trace("reloaded.")
        return True

    def reload_feed(self):
        self.handlers = []
        self._reload_feed_handlers()
        self._reload_feed_data()
        if self.initialized:
            for channel in self.autojoin_channels:
                channel = channel.encode('utf-8')
                if channel not in self.channels:
                    self.connection.join(channel)
            for fetcher, enabled in self.frequent_fetches.iteritems():
                self.ircobj.execute_delayed(0, self.frequent_fetch, (fetcher,))
                self.frequent_fetches[fetcher] = enabled

    def _reload_feed_handlers(self):
        handler_names = []
        import_path = os.path.join(FEEDEX_ROOT, 'feeds')
        for file_name in os.listdir(import_path):
            if file_name.endswith('.py') and not file_name.startswith('__'):
                handler_names.append(file_name[:-3])
        self.handlers = []
        self.autojoin_channels = set()
        for handler_name in handler_names:
            module = self._load_handler_module(handler_name)
            if module is None:
                continue
            self.handlers.append({
                '__name__': handler_name,
                'manager': module.manager,
            })

    def _load_handler_module(self, handler_name):
        paths = [os.path.join(FEEDEX_ROOT, 'feeds')]
        try:
            file_obj, filename, opt = imp.find_module(handler_name, paths)
        except ImportError:
            traceback.print_exc()
            return None
        try:
            module = imp.load_module(handler_name, file_obj, filename, opt)
        except Exception:
            traceback.print_exc()
        finally:
            if file_obj:
                file_obj.close()
        return module

    def _load_feed_data(self):
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
        for channel in self.channels:
            if channel.decode('utf-8', 'ignore') not in self.autojoin_channels:
                self.connection.part(channel)

    def _reload_feed_data(self):
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
        for channel in self.channels:
            if channel.decode('utf-8', 'ignore') not in self.autojoin_channels:
                self.connection.part(channel)

FEEDEX_ROOT = os.path.dirname(os.path.abspath(__file__))

def main():
    profile = None
    if len(sys.argv) > 1:
        profile = sys.argv[1]
    if not profile:
        profile = 'config'
    trace("profile: %s" % profile)
    config_file_name = os.path.join(FEEDEX_ROOT, '%s.py' % profile)
    feedex = FeedBot(config_file_name)
    feedex.start()

if __name__ == '__main__':
    main()

