#!/usr/bin/env python
# -*- encoding: utf-8 -*-
import itertools
import logging
import os
import sys
import time
from collections import defaultdict

import irc.client
import yaml

from BufferingBot import BufferingBot, Message
import feeds

FEEDEX_ROOT = os.path.dirname(os.path.abspath(__file__))

class FeedBot(BufferingBot):
    def __init__(self, config_file_name):
        self.config = None
        self.config_file_name = config_file_name
        self.buffer_file_name = os.path.join(FEEDEX_ROOT, 'buffer.yml')
        self.version = -1
        self.config_timestamp = -1
        self.silent = False
        self.load()

        server = self.config['server']
        nickname = self.config['nickname']
        BufferingBot.__init__(self, [server], nickname,
            username="FeedEx",
            realname="FeedEx the feed bot",
            buffer_timeout=-1, # don't use timeout
            use_ssl=self.config.get('use_ssl', False))

        logging.info("Loading buffer...")
        if os.access(self.buffer_file_name, os.F_OK):
            for message in yaml.load(open(self.buffer_file_name, 'rb')):
                self.push_message(message)

        self.initialized = False
        self.connection.add_global_handler('welcome', self._on_connected)

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
            logging.exception('while reading {}'.format(self.config_file_name))
        return None

    def _check_config_file(self):
        try:
            if self._get_config_time() <= self.config_timestamp:
                return
            self.reload()
        except Exception:
            logging.exception('')
        self.ircobj.execute_delayed(1, self._check_config_file)

    def _on_connected(self, conn, _):
        logging.info('Connected.')
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
            fetcher = next(self.feed_iter)
        except StopIteration:
            self.feed_iter = itertools.cycle(self.feeds)
            fetcher = next(self.feed_iter)
        except RuntimeError:
            # RuntimeError: dictionary changed size during iteration
            self.feed_iter = itertools.cycle(self.feeds)
            fetcher = next(self.feed_iter)
        self.fetch_feed(fetcher)
        self.ircobj.execute_delayed(
            self.config.get('fetch_period', 3), self._iter_feed)

    def fetch_feed(self, fetcher):
        logging.debug('Fetching: {}'.format(fetcher.uri))
        entries = []
        try:
            entries = fetcher.get_fresh_entries()
        except Exception:
            logging.exception('while trying to get {}'.format(fetcher.uri))
            return
        for formatter in self.feeds[fetcher]:
            try:
                for target, msg, opt in formatter.format_entries(entries):
                    assert isinstance(target, str)
                    assert isinstance(msg, str)
                    message = Message('privmsg', (target, msg),
                        timestamp=opt.get('timestamp', 0))
                    self.push_message(message)
            except Exception:
                logging.exception(
                    'while trying to format an entry from {}'.format(fetcher.uri))
                return
        if entries:
            try:
                fetcher.update_timestamp(entries)
            except Exception:
                logging.exception(
                    'while updating timestamp for {}'.format(fetcher.uri))
                return

    def flood_control(self):
        if BufferingBot.flood_control(self):
            self.dump_buffer()

    def pop_buffer(self, message_buffer):
        message = message_buffer.peek()
        if message.timestamp > time.time():
            # 미래에 보여줄 것은 미래까지 기다림
            # TODO: ignore_time이면 이 조건 무시
            return False
        if self.silent:
            return self.process_message(message_buffer.pop())
        if message.command in ['privmsg']:
            target = message.arguments[0]
            chan = target.lower()
            if irc.client.is_channel(chan):
                if chan not in [_.lower() for _ in self.channels]:
                    self.connection.join(chan)
        return BufferingBot.pop_buffer(self, message_buffer)

    def process_message(self, message):
        logging.info('%s %s', message.command, ' '.join(message.arguments))
        if self.silent:
            return True
        return BufferingBot.process_message(self, message)

    def dump_buffer(self):
        dump = yaml.dump(list(self.message_buffer.dump()),
            default_flow_style=False,
            encoding='utf-8',
            allow_unicode=True)
        open(self.buffer_file_name, 'wb').write(dump)

    def push_message(self, message):
        BufferingBot.push_message(self, message)
        self.dump_buffer()

    def load(self):
        data = self._get_config_data()
        if self.version >= data['version']:
            return False
        self.config = data
        self.config_timestamp = os.stat(self.config_file_name).st_mtime
        self.version = data['version']
        return True

    def reload(self):
        if not self.load():
            return False
        logging.info("reloading...")
        self.reload_feed()
        logging.info("reloaded.")
        return True

    def reload_feed(self):
        self.handlers = []
        self._reload_feed_handlers()
        self._reload_feed_data()
        if self.initialized:
            for fetcher, enabled in self.frequent_fetches.items():
                self.ircobj.execute_delayed(0, self.frequent_fetch, (fetcher,))
                self.frequent_fetches[fetcher] = enabled

    def _reload_feed_handlers(self):
        self.handlers = feeds.reload()

    def _load_feed_data(self):
        self.feed_iter = None
        self.feeds = defaultdict(list)
        self.frequent_fetches = {}
        for handler in self.handlers:
            manager = handler['manager']
            try:
                for fetcher, formatter in manager.load():
                    logging.debug('Loaded: {}'.format(fetcher.uri))
                    self.feeds[fetcher].append(formatter)
                    if fetcher.frequent:
                        self.frequent_fetches[fetcher] = True
            except Exception:
                logging.exception('')
                continue
            logging.info('%s loaded successfully.', handler['__name__'])

    def _reload_feed_data(self):
        self._load_feed_data()


def main():
    profile = None
    if len(sys.argv) > 1:
        profile = sys.argv[1]
    if not profile:
        profile = 'config'
    config_file_name = os.path.join(FEEDEX_ROOT, '%s.py' % profile)
    data = eval(open(config_file_name).read())
    if data.get('debug', False):
        logging.basicConfig(level=logging.DEBUG)
        logging.debug('Debugging mode')
    else:
        logging.basicConfig(level=logging.INFO)
    logging.info("profile: %s", profile)
    feedex = FeedBot(config_file_name)
    while True:
        try:
            feedex.start()
        except KeyboardInterrupt:
            logging.exception('')
            break
        except:
            logging.exception('')
            raise


if __name__ == '__main__':
    main()
