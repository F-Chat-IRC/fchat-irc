'''This module provides the factory that handles the IRC server. Several commands are translated directly to F-list, as documented here:
https://wiki.f-list.net/F-Chat_Server_Commands
Most of the functions are named for their IRC methods: https://tools.ietf.org/html/rfc2812 
and the numeric names can be referenced here: https://www.alien.net.au/irc/irc2numerics.html
'''

from twisted.internet.protocol import ServerFactory
from twisted.internet.task import LoopingCall, deferLater
from twisted.internet.defer import inlineCallbacks
import twisted.words.protocols.irc as irc
import re
import json
import datetime
import socket
import time
import logging

import flistprotocolwsirc
from do_log import *
from irc_bots import Bot

SERVERNAME = 'testserv'
VERSION=0.1
CREATED = datetime.datetime.now().strftime('%M:%H %d/%m/%y')

class IRCServer(irc.IRC):
    def __init__(self,reactor):
        self.MAX_LENGTH=9999999
        self.flist=None
        self.reactor=reactor
        self.reactor.irc = self
        self.servernick=SERVERNAME
        self.servername=socket.getfqdn()
        self.nick = ''
        self.channels = []
        self.pm=[]
        self.passwd = ''
        self.pinging = False
        self.flistConnect()
        self.logging_in=True
        self.hello=''

    @inlineCallbacks
    def flistConnect(self):
        flfactory = flistprotocolwsirc.FlistWSFactory("wss://chat.f-list.net:9799", self.reactor,self)
        yield self.reactor.connectTCP("chat.f-list.net", 9722, flfactory)
        logging.debug('IRC connect')
        self.bot = Bot(self)

#Loop functions
    @traceback
    def cb_PING(self):
        '''An automatic IRC ping callback, every 60 seconds. Keeps clients happy.'''
        logging.info ('PINGing.')
        self.sendLine("%s" % ("PING"))

#irc callback functions
    @traceback
    def irc_USER(self,prefix, params):
        '''Called on login. Has a bunch of info we don't need, but we can use this to start loops.'''
        logging.info ("USER login." + str(params))
        if not self.pinging:
            self.pinging = LoopingCall(self.cb_PING)
            self.pinging.start(60)

    @traceback
    def irc_QUIT(self,prefix, params):
        '''User dropped. Shut down the connections.'''
        logging.info ("USER quit.")
        self.flist.dropConnection()

    @traceback
    def irc_PASS(self,prefix,params):
        '''Set a password.'''
        self.passwd = params[0]
        if self.passwd != '' and self.nick != '':
            self.getLogin(self.nick, self.passwd)

    @traceback
    def irc_PING(self,prefix,params):
        '''Client has pinged server. Reply appropriately.'''
        logging.info ('PONGing.')
        self.sendLine("%s" % ("PONG"))

    @traceback
    def irc_PONG(self,prefix,params):
        '''Client has replied to our ping. Do nothing.'''
        pass

    @traceback
    def irc_NICK(self, prefix, params):
        '''Set a nick. This might come before or after PASS.'''
        if self.nick == '':
            self.nick = params[0]
            if self.passwd != '' and self.nick != '':
                self.getLogin(self.nick, self.passwd)
        else:
            try:
                char=None
                if self.flist.userDecode(params[0]) in self.flist.characters:
                    char = params[0]
#                if params[0].strip() in self.flist.characters:
#                    char = params[0].strip()
#                if ' '.join(params).strip() in self.flist.characters:
#                    char = ' '.join(params).strip()
#                if char is not None:
                    acc = self.flist.account
                    for x in self.channels:
                        self.userMsg(self.nick,'PART '+x)
                    self.nick = char
                    self.flist.dropConnection()
                    self.logging_in=True
                    self.flist=None
                    self.flistConnect()
                    self.getLogin(acc+'='+char, self.passwd)
#                    self.flist.chatLogin(self.flist.account,self.flist.password,char)
                else:
                    self.serverMsg(irc.ERR_NICKNAMEINUSE,':Nickname already in use.')                
            except:
                logging.debug(tb.format_exc())
                self.serverMsg(irc.ERR_NICKNAMEINUSE,':Nickname error.')

    @traceback
    def irc_JOIN(self, prefix, params):
        '''Join a channel, or multiple comma separated.'''
        if self.flist is None:
            self.reactor.callLater(2,self.irc_JOIN,prefix,params)
            return
        data = {}
        ch = [x.strip() for x in params[0].split(',')]
        for chan in ch:
            try:
                if chan.lower().startswith('#adh'): chan = chan[1:]
                data['channel'] = self.flist.chanDecode(chan)
                par = json.dumps(data)
                self.flist.sendMsg('JCH '+par)
                if chan not in self.channels: self.channels.append(chan)
            except ValueError:
                self.serverMsg(irc.ERR_NOSUCHCHANNEL,params[0]+' :Channel unknown.')

    @traceback
    def irc_PART(self, prefix, params):
        '''You left a channel.'''
        data = {}
        data['channel'] = self.flist.chanDecode(params[0])
        par = json.dumps(data)
        self.flist.sendMsg('LCH '+par)
        if params[0] in self.channels: self.channels.remove(params[0])

    @traceback
    def irc_WHO(self, prefix, params):
        '''Give me information on everyone in a channel (to build member lists)'''
        irctarget = params[0]
        target = self.flist.chanDecode(irctarget)
        for user in self.flist.chans[target]['users']:
            udict = self.flist.chars[user]
            ircuser = self.flist.userEncode(user)
            if udict['status'] == 'away':
                mode = 'G'
            else:
                mode = 'H'
            if user in self.flist.chans[target]['ops']: 
                mode = mode + '@'
            ident = udict['gender']+'.flist'
            self.serverMsg(irc.RPL_WHOREPLY,' '.join([irctarget,ircuser,ident,self.servername,ircuser,mode,':0',udict['statusmsg']]))
        self.serverMsg(irc.RPL_ENDOFWHO,':End of WHO list')

    @traceback
    def irc_PRIVMSG(self, prefix, params):
        '''All normal channel messages and privmsgs come through here.'''
        if len(params)==1:
            self.serverMsg(irc.ERR_NOTEXTTOSEND,':No message.' )
            return
        data = {}
#Check for CTCP messages e.g.: params=  [char, '\x01TYPING 1\x01']
        if params[0][0] == '#': #channel message        
            try:
                data['channel'] = self.flist.chanDecode(params[0])
#CTCP TYPING messages do not go into channels, only PM's!
                msg = re.sub('\x01ACTION *(.*)\x01',r'/me \1',params[1])
                msg = self.flist.msgDecode(msg)
                data['message']=msg
                par = json.dumps(data)
                self.flist.sendMsg('MSG '+par)
            except ValueError:
                self.serverMsg(irc.ERR_NOSUCHCHANNEL,params[0]+' :Channel unknown.')
        else: #user message
            #Hook in the bot functions
            method = getattr(self.bot, "bot_%s" % params[0].lower(), None)
            if method is not None:
                method(prefix, params[1:])
            else:
                try:
                    user = self.flist.userDecode(params[0])
                    self.pm.append(user)
                    data['recipient'] = user
#                    msg = params[1].strip('\x01').strip()
#                    if 'ACTION' == msg[:6]: msg = '/me'+msg[6:]
                    msg = re.sub('\x01ACTION *(.*)\x01',r'/me \1',params[1])
                    msg = self.flist.msgDecode(msg)
                    data['message']=msg
                    if self.flist.chars[user]['status']=='offline': raise ValueError
                    par = json.dumps(data)
                    self.flist.sendMsg('PRI '+par)
                except ValueError:
                    self.serverMsg(irc.ERR_NOSUCHNICK,params[0]+' :User unknown.')

    @traceback
    def irc_NOTICE(self, prefix, params):
        '''Create an in-channel RP ad.'''
        data = {}
        if params[0][0] == '#': #channel command
            try:
                data['channel'] = self.flist.chanDecode(params[0])
                msg = params[1].strip('\x01').strip()
                msg = self.flist.msgDecode(msg)
                if 'ACTION' == msg[:6]: msg = '/me'+msg[6:]
                data['message']=msg
                self.flist.sendMsg('LRP '+json.dumps(data))
            except ValueError:
                self.serverMsg(irc.ERR_NOSUCHCHANNEL,params[0]+' :Channel unknown.')

    @traceback
    def irc_LIST(self, prefix, params):
        self.flist.sendMsg('CHA')
        #Should also try to get the chan topic if given one in params

    @traceback
    def irc_AWAY(self, prefix, params):
        '''Set or unset the away status.'''
        data = {}
        if len(params)>0:
            self.serverMsg(irc.RPL_NOWAWAY,':You have been marked as being away.')
            self.flist.oldsts = str(self.flist.chars[self.nick]['status'])
            self.flist.oldstsmsg = str(self.flist.chars[self.nick]['statusmsg'])
            data['status']='away'
            data['statusmsg']=params[0]
            self.flist.sendMsg('STA '+json.dumps(data))
        else:
            self.serverMsg(irc.RPL_UNAWAY,':You are no longer marked as being away.')
            if str(self.flist.oldsts) in ['online','looking','busy','dnd']:
                data['status']=self.flist.oldsts
            else:
                data['status']='online'
            data['statusmsg']=self.flist.oldstsmsg
            self.flist.sendMsg('STA '+json.dumps(data))

#unwritten functions
    @traceback
    def irc_ADMIN(self, prefix, params):
        '''Show me a list of the admins.'''
        pass

    @traceback
    def irc_INVITE(self, prefix, params):
        '''Invite <nick> to <chan>'''
        pass
    @traceback
    def irc_ISON(self, prefix, params):
        '''Tell me if <nick> is on.'''
        pass
    @traceback
    def irc_KICK(self, prefix, params):
        ''' Remove from <chan>, <nick>'''
        pass
    @traceback
    def irc_KNOCK(self, prefix, params):
        '''Request access to <chan> with <msg>'''
        pass
    @traceback
    def irc_LUSERS(self, prefix, params):
        '''Do something pretty with stats:
There are 37 users and 10584 invisible on 19 servers
23 IRC Operators online
2399 channels formed
I have 610 clients and 1 servers
Current local users: 610  Max: 1092
Current global users: 10621  Max: 11257
Highest connection count: 1093 (1092 clients) (89653 connections received)
'''
        pass

    @traceback
    def irc_MODE(self, prefix, params):
        '''Set mode on <nick/chan> <flags>'''
        data={}
        logging.debug(params)
        if len(params)==1: #Return info.
            if params[0][0]=='#':
                self.serverMsg(irc.RPL_CHANNELMODEIS,params[0]+' +t')
        else:
            if params[0][0]=='#':
                data['channel']=self.flist.chanDecode(params[0])
                if params[1][0] == '+': #ADD
                    if 'o' in params[1]: #OP
                        data['character']=self.flist.userDecode(params[2])
                        self.flist.sendMsg('COA '+json.dumps(data))
                    if 'O' in params[1]: #OWNER
                        data['character']=self.flist.userDecode(params[2])
                        self.flist.sendMsg('CSO '+json.dumps(data))
                if params[1][0] == '-': #REMOVE
                    if 'o' in params[1]: #OP
                        data['character']=self.flist.userDecode(params[2])
                        self.flist.sendMsg('COR '+json.dumps(data))

    @traceback
    def irc_MOTD(self, prefix, params):
        '''Get the MOTD'''
        pass
    @traceback
    def irc_NAMES(self, prefix, params):
        '''Return a list of who is in <chans>'''
        pass
    @traceback
    def irc_OPER(self, prefix, params):
        '''Useful for entering passwords in secret, like bitlbee. <nick> <passwd>'''
        pass
    @traceback
    def irc_SILENCE(self, prefix, params):
        '''Ignore <nick>'''
        pass
    @traceback
    def irc_TOPIC(self, prefix, params):
        '''Get or set topic on <chan> [<msg>] '''
        pass
    @traceback
    def irc_USERHOST(self, prefix, params):
        '''Get host info on <nick>.
 buZz=+~buzz@space.nurdspace.nl'''
        pass
    @traceback
    def irc_USERS(self, prefix, params):
        '''Return a list of chars.'''
        pass
    @traceback
    def irc_VERSION(self, prefix, params):
        '''Return some server info.
RPL_VERSION hybrid-7.0.3(20040701_0).  irc.nsict.orgegGHIKMpZ
WALLCHOPS KNOCK EXCEPTS INVEX MODES=4 MAXCHANNELS=15 MAXBANS=25 MAXTARGETS=4 NICKLEN=15 TOPICLEN=350 KICKLEN=350 are supported by this server
CHANTYPES=#& PREFIX=(ohv)@%+ CHANMODES=eIb,k,l,imnpst NETWORK=nsict CASEMAPPING=rfc1459 CALLERID are supported by this server
'''
        pass
    @traceback
    def irc_WATCH(self, prefix, params):
        '''using  [+/-<nick>], set watch. Quite rare to use.'''
        pass
    @traceback
    def irc_WHOIS(self, prefix, params):
        '''Return information about a char.
RPL_WHOISUSER buZz [~buzz@space.nurdspace.nl]
ircname  : buZz
RPL_WHOISCHANNELS channels : @#nurds @#puik. #rss @#wesp #nurdsbestuur #pcl #fsf-tablet #hark24 @#idiopolis @#techinc #hack42 #osm #nurdbottest @#puik @#uch @#fablabwag @#nurds-netwerk @#xtensa
RPL_WHOISSERVER server   : beauty.oftc.net [New York, New York]
         : user has identified to services
RPL_WHOISHOST hostname : 213.154.232.2 
RPL_ENDOFWHOIS End of WHOIS
'''
        char = params[-1]
        pass
    @traceback

#These functions are intentionally blanked.
    @traceback
    def irc_INFO(self, prefix, params):
        self.irc_disallowed(params)
    def irc_HELP(self, prefix, params):
        self.irc_disallowed(params)
    def irc_STATS(self, prefix, params):
        self.irc_disallowed(params)
    def irc_WHOWAS(self, prefix, params):
        self.irc_disallowed(params)
    def irc_DIE(self, prefix, params):
        self.irc_disallowed(params)
    def irc_RESTART(self, prefix, params):
        self.irc_disallowed(params)
    def irc_SETNAME(self, prefix, params):
        self.irc_disallowed(params)
    def irc_TIME(self, prefix, params):
        self.irc_disallowed(params)
    def irc_TRACE(self, prefix, params):
        self.irc_disallowed(params)
    def irc_USERIP(self, prefix, params):
        self.irc_disallowed(params)
    def irc_WALLOPS(self, prefix, params):
        self.irc_disallowed(params)

    @traceback
    def irc_disallowed(self, params):
        '''This is called if there is a known function BUT it is definitely not going to be coded.'''
        self.serverMsg(irc.ERR_UNKNOWNCOMMAND,params[0]+' :Unhandled command.')

    @traceback
    def irc_unknown(self, prefix, command, params):
        '''This function is called if an unexpected IRC command is passed and ought to be implemented.'''
        self.serverMsg(irc.ERR_UNKNOWNCOMMAND,params[0]+' :Unknown command.')
        logging.error ("%s, %s, %s, IRC UNKNOWN" % (prefix, command, params))

#Helper functions
    @traceback
    def getLogin(self, nick, passwd):
        if self.flist is None:
            self.reactor.callLater(2,self.getLogin,nick,passwd)
            return
        try:
            nick,character = nick.split('=',1)
        except:
            character=''
        logging.debug('Logging in with '+ str((nick,passwd,character)))
        self.flist.chatLogin(nick,passwd,character)

    @traceback
    def finishLogin(self):
        self.logging_in=False
        self.serverMsg(irc.RPL_WELCOME,':'+self.hello)
        self.serverMsg(irc.RPL_YOURHOST,":No host info found.")
        self.serverMsg(irc.RPL_UMODEIS,'+i')

    @traceback
    def handleCommand(self, command, prefix, params):
        logging.debug ("<-- "+str(command)+' '+str(prefix)+' '+str(params))
        irc.IRC.handleCommand(self, command, prefix, params)

    @traceback
    def serverMsg(self, reply, line='',dest=None):
        if dest == None: dest = self.nick
        for l in line.split('\n'):
            logging.debug(':'+self.servername+' '+str(reply)+' '+str(dest)+' '+str(l))
            self.sendLine(':'+self.servername+' '+str(reply)+' '+str(dest)+' '+str(l))

    @traceback
    def userMsg(self, user, line=''):
        try:
            name = self.flist.userEncode(user)
        except: #by ircname
            name = user
            user = self.flist.userDecode(name)
            logging.info ('Repairing incorrect usage of userMsg....')
        udict = self.flist.chars[user]
        gender = udict['gender']
        for l in line.split('\n'): 
            self.sendLine(':'+name+'!'+name+'.'+gender+'@'+self.nick+'.flist '+l)

    @traceback
    def sendLine(self,line):
        logging.info ("--> "+line)
        l = line.replace('\n','').replace('\r','') #Safety factor
        if l != line:
            logging.info (r'\n trapped')
        irc.IRC.sendLine(self,l)

class IRCServerFactory(ServerFactory):
    def __init__(self,reactor):
        self.reactor= reactor
    def buildProtocol (self, reactor):
        return IRCServer(self.reactor)

