#!/usr/bin/env python
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Contributions can be shared at https://github.com/maikelwever/gitlabot
#

import re
import socket

import tornado.web
from tornado.ioloop import IOLoop
from tornado.iostream import IOStream

import brukva
import redis
import json

try:
    from local import *
except ImportError:
    IRC_SERVER = 'irc.freenode.net'
    IRC_CHANS = ['#braqbot',]
    IRC_NICK = 'changemePLEASE'
    IRC_OWNER = 'henkdevries'
    IRC_COMMAND_CHAR = '$'
    WEB_PORT = 8889
    REDIS_CHAN = "gitlabot"
    REDIS_DB = 2
    # Set proto to https if you use https for external use
    PROTO = "https"


print """Gitlabot, yet another bot which spams commitmessages on IRC
Gitlabot comes with ABSOLUTELY NO WARRANTY; for details see the LICENCE file.
This is free software, and you are welcome to redistribute it
under certain conditions;

Contributions can be shared at https://github.com/maikelwever/gitlabot
"""


if not PROTO:
    proto = ''

class IrcProtoCmd(object):

    def __init__(self, actn):
        self.hooks = set()
        self.actn = actn

    def __call__(self, irc, ln):
        self.actn(irc, ln)
        for h in self.hooks:
            h(irc, ln)


renick = re.compile("^(\w*?)!")


class IrcObj(object):
    """
    tries to guess and populate something from an ircd statement
    """

    def __init__(self, line, bot):
        self.text = self.server_cmd = self.chan = self.nick = None
        self._bot = bot
        self.line = line
        self.command = None
        self.command_args = None
        self._parse_line(line)

    def _parse_line(self, line):

        if not line.startswith(":"):
            # PING most likely
            stoks = line.split()
            self.server_cmd = stoks[0].upper()
            return

        # :senor.crunchybueno.com 401 nodnc  #xx :No such nick/channel
        # :nod!~nod@crunchy.bueno.land PRIVMSG xyz :hi

        tokens = line[1:].split(":")
        if not tokens:
            return

        stoks = tokens[0].split()

        # find originator
        nick = renick.findall(stoks[0])
        if len(nick) == 1:
            self.nick = nick[0]
        stoks = stoks[1:]  # strip off server tok

        self.server_cmd = stoks[0].upper()
        stoks = stoks[1:]

        # save off remaining tokens
        self.stoks = stoks

    def say(self, text, dest=None):
        self._bot.say(dest or self.chan, text)

    def error(self, text, dest=None):
        self.say(dest or self.chan, "error: %s" % text)


class IOBot(object):

    def __init__(
            self,
            host,
            nick='hircules',
            port=6667,
            char='@',
            owner='owner',
            initial_chans=None,
            on_ready=None,
            redis_db=REDIS_DB,
            redis_channel=REDIS_CHAN,
    ):
        """
        create an irc bot instance.
        @params
        initial_chans: None or list of strings representing channels to join
        """
        self.nick = nick
        self.chans = set()  # chans we're a member of
        self.owner = owner
        self.host = host
        self.port = port
        self.char = char
        self._plugins = dict()
        self._connected = False
        # used for parsing out nicks later, just wanted to compile it once
        # server protocol gorp
        self._irc_proto = {
            'PRIVMSG': IrcProtoCmd(self._p_privmsg),
            'PING': IrcProtoCmd(self._p_ping),
            'JOIN': IrcProtoCmd(self._p_afterjoin),
            '401': IrcProtoCmd(self._p_nochan),
        }
        # build our user command list
        self.cmds = dict()

        self._initial_chans = initial_chans
        self._on_ready = on_ready

        self.brukva = brukva.Client(selected_db=redis_db)
        self.brukva.connect()
        self.brukva.subscribe(redis_channel)

        # finally, connect.
        self._connect()

    def hook(self, cmd, hook_f):
        """
        allows easy hooking of any raw irc protocol statement.  These will be
        executed after the initial protocol parsing occurs.  Plugins can use this
        to extend their reach lower into the protocol.
        """
        assert(cmd in self._irc_proto)
        self._irc_proto[cmd].hooks.add(hook_f)

    def joinchan(self, chan):
        self._stream.write("JOIN :%s\r\n" % chan)

    def say(self, chan, msg):
        """
        sends a message to a chan or user
        """
        self._stream.write("PRIVMSG {} :{}\r\n".format(chan, msg))

    def register(self, plugins):
        """
        accepts an instance of Plugin to add to the callback chain
        """
        for p in plugins:
            # update to support custom paths?
            p_module = __import__(
                'iobot.plugins.%s.plugin' % p,
                fromlist=['Plugin']
            )
            p_obj = p_module.Plugin()

            cmds = []
            for method in dir(p_obj):
                if callable(getattr(p_obj, method)) \
                        and hasattr(getattr(p_obj, method), 'cmd'):
                    cmds.append(method)

            for cmd in cmds:
                self._plugins[cmd] = p_obj

    def _connect(self):
        print "Connecting to IRC server..."
        _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        self._stream = IOStream(_sock)
        self._stream.connect((self.host, self.port), self._after_connect)

    def _after_connect(self):
        print "Connected, logging in...."
        self._stream.write("NICK %s\r\n" % self.nick)
        self._stream.write("USER %s 0 * :%s\r\n" % ("iobot", "iobot"))
        print "Logged in, joining channels..."

        if self._initial_chans:
            for c in self._initial_chans:
                self.joinchan(c)
                print "Joined channel " + c
            del self._initial_chans

        print "Connecting to Redis"
        self.brukva.listen(self.on_brukva_message)

        print "Invoking callback, if any."
        if self._on_ready:
            self._on_ready()
        print "Done connecting. Profit!"
        self._next()

    def on_brukva_message(self, msg):
        for i in IRC_CHANS:
            self.say(i, msg.body)

    def _parse_line(self, line):
        irc = IrcObj(line, self)
        if irc.server_cmd in self._irc_proto:
            self._irc_proto[irc.server_cmd](irc, line)
        return irc

    def _p_ping(self, irc, line):
        self._stream.write("PONG %s\r\n" % line[1])

    def _p_privmsg(self, irc, line):
        # :nod!~nod@crunchy.bueno.land PRIVMSG #xx :hi
        toks = line[1:].split(':')[0].split()
        irc.chan = toks[-1]  # should be last token after last :
        irc.text = line[line.find(':', 1) + 1:].strip()
        if irc.text and irc.text.startswith(self.char):
            text_split = irc.text.split()
            irc.command = text_split[0][1:]
            irc.command_args = ' '.join(text_split[1:])

    def _p_afterjoin(self, irc, line):
        toks = line.strip().split(':')
        if irc.nick != self.nick:
            return  # we don't care right now if others join
        irc.chan = toks[-1]  # should be last token after last :
        self.chans.add(irc.chan)

    def _p_nochan(self, irc, line):
        # :senor.crunchybueno.com 401 nodnc  #xx :No such nick/channel
        toks = line.strip().split(':')
        irc.chan = toks[1].strip().split()[-1]
        if irc.chan in self.chans:
            self.chans.remove(irc.chan)

    def _process_plugins(self, irc):
        """ parses a completed ircObj for module hooks """
        try:
            plugin = self._plugins.get(irc.command) if irc.command else None
        except KeyError:
            # plugin does not exist
            pass

        try:
            if plugin:
                plugin_method = getattr(plugin, irc.command)
                plugin_method(irc)
        except:
            doc = "usage: %s %s" % (irc.command, plugin_method.__doc__)
            irc.say(doc)

    def _next(self):
        # go back on the loop looking for the next line of input
        self._stream.read_until('\r\n', self._incoming)

    def _incoming(self, line):
        self._process_plugins(self._parse_line(line))
        self._next()


class MainHandler(tornado.web.RequestHandler):
    def post(self):
        data = self.request.body
        if data:
            data = json.loads(data)
            r = redis.Redis(db=REDIS_DB)

            r.publish(REDIS_CHAN, "%s new commits for %s, %s" % (
                len(data['commits']), data['repository']['name'],
                data['repository']['homepage']))

            for i in data['commits']:

                hmmurl = i['url']
                if 'http' in hmmurl and 'https' not in hmmurl and PROTO == 'https':
                    hmmurl = hmmurl.replace('http', 'https')

                r.publish(REDIS_CHAN, "by %s | %s | %s" % (
                    i['author']['name'].split()[0], i['message'], hmmurl))

            self.write("ty")
        self.write('Dunno')


def main():
    io = IOBot(
        host=IRC_SERVER,
        nick=IRC_NICK,
        char=IRC_COMMAND_CHAR,
        owner=IRC_OWNER,
        port=6667,
        initial_chans=IRC_CHANS,
    )

    application = tornado.web.Application([
        (r"/", MainHandler),
    ])

    application.listen(WEB_PORT)
    IOLoop.instance().start()


if __name__ == '__main__':
    main()
