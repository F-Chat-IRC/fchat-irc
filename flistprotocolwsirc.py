# -*- coding: utf-8 -*-
'''This is the main module that handles all the commands from F-list. (see https://wiki.f-list.net/F-Chat_Client_Commands for details)
The lower block handles the https://wiki.f-list.net/Json_endpoints JSON, unifying it into a standard interface.'''
import HTMLParser
import urllib, urllib2, json
import time, string
from twisted.internet.task import LoopingCall
import twisted.words.protocols.irc as irc
import os, sys, re
import logging
from collections import defaultdict
from autobahn.twisted.websocket import WebSocketClientProtocol, \
                                       WebSocketClientFactory

def defdefaultdict():
    '''A driver so defaultdict returns a defaultdict of strings.'''
    return defaultdict(str)

from do_log import *
h = HTMLParser.HTMLParser()

class FlistProtocol(WebSocketClientProtocol):
    def __init__(self,reactor,irc=None):
        if irc is not None:
            self.irc = irc
            self.irc.flist = self
        self.account = ''
        self.password = ''
        self.ticket = ''
        if reactor is not None:
            logging.debug('fl init reactor.')
            self.reactor = reactor
            self.reactor.flist = self
            self.irc = self.reactor.irc
        self.flconnected=False
        self.typing_notify=True
        self.login_notify=False
        self.nick = ''
        self.friends=[]
        self.ignores=[]
        #All the characters (i.e. everyone else) in Flist format
        self.chars = defaultdict(defdefaultdict)
        self.chars['info']={}
        self.chars['info']['ircname']='info'
        self.chars['info']['gender']='bot'
        self.chars['info']['status']=''
        self.chars['info']['statusmsg']=''
        #All the channels in Flist format.
        self.chans = defaultdict(defdefaultdict)
        self.kinks = {}
        self.sys_params = {}
        self.pinging=None
        self.expectingping=False
        self.pingrate=120
        self.lastping=time.time()
        self.toomanypings=10

    @traceback
    def onConnect(self, response):
       '''Called only on connections for the websocket.'''
       logging.info("Server connected: {0}".format(response.peer))

    @traceback
    def onOpen(self):
        '''This is called when the connection is actually opened.'''
        pass

    @traceback
    def onClose(self, wasClean, code, reason):
        '''Called once the WS session closes.'''
        self.flconnected = False
        logging.info ("WebSocket connection closed: {0}".format(reason))
        self.irc.transport.loseConnection()

    @traceback
    def chatLogin(self, nick, passwd,character=''):
        '''Instantiated from irc when a new login is detected. It sets up the user in the users table.'''
        if not self.flconnected:
            r = self.identify(nick,passwd)
            self.flconnected = True
            self.characters=r['characters']
            self.default_character=r['default_character']
        ircchars = [self.userEncode(x) for x in self.characters]
        if not self.pinging:
            self.pinging = LoopingCall(self.cb_PING)
            self.pinging.start(self.pingrate)
        logging.info('IRC safe char list: '+str(ircchars))
        try:
            num = ircchars.index(character)
            sel_char = self.characters[num]
        except:
            sel_char = self.default_character
        IDstring = json.dumps({'method':'ticket',
                       'account':nick,
                       'ticket':self.ticket,
                       'character':sel_char,
                       'cname':'f-chat-irc',
                       'cversion':'0.4'})
        self.sendMsg('IDN '+IDstring)
        self.getKinks()


    @traceback
    def onMessage(self, payload,isBinary):
        '''A callback once a message comes in from the F-List server.'''
        message = payload.decode('utf8').strip()
        logging.debug('<- '+message.encode('ascii','ignore'))
        command = message[:3].strip()
        try:
            params = json.loads(message[3:].strip())
        except:
            params = ''
        prefix = ''
        method = getattr(self, "fl_%s" % command, None)
        try:
            if method is not None:
                method(prefix, params)
            else:
                self.fl_unknown(command, prefix, params)
        except Exception,e:
            logging.info (sys.exc_info())
            logging.info ('Error: '+ str(payload))


    @traceback
    def sendMsg(self, payload, isBinary=False):
        '''An override to log all outgoing messages before delivery'''
        logging.info('-> '+str(payload))
        return self.sendMessage(payload,isBinary)

    @traceback
    def chanEncode(self,channame):
        '''This function converts FList channel names into a safe unambiguous IRC format.'''
        if 'ircname' in self.chans[channame]:
            ircname = self.chans[channame]['ircname']
            if ircname != '':
                return ircname
        ircname = "#"+str(channame).replace(' ','_').replace("'",'').replace('/','+').lower()
        postfix = 1
        unique = False
        while unique==False:
            notunique = False
            for chan in self.chans:
                try:
                    if self.chans[chan]['ircname'] == ircname:
                        notunique = True
                except:
                    pass
            if notunique:
                ircname = "#"+str(channame).replace(' ','_').replace("'",'').replace('/','+').lower()+str(postfix)
                postfix = postfix + 1
            else:
                unique = True
        self.chans[channame]['ircname'] = ircname
        return ircname

    def chanDecode(self,channel):
        '''This function converts IRC encoded channel names into ones that Flist uses.'''
        for chan in self.chans:
            try:
                if self.chans[chan]['ircname'] == channel.lower():
                    return chan
            except:
                pass
        raise ValueError ("I don't know a channel called "+str(channel))

    @traceback
    def userEncode(self,username):
        '''This function converts FList charnames into a safe unambiguous IRC format.'''
        if 'ircname' in self.chars[username]:
            ircname = self.chars[username]['ircname']
            if ircname != '':
                return ircname
        ircname = username.encode('ascii','ignore').replace(' ','_').replace("'",'').replace('/','+')
        postfix = 1
        unique = False
        while not unique:
            notunique = False
            for user in self.chars:
                if self.chars[user]['ircname'] == ircname:
                    notunique = True
            if notunique:
                ircname = username.replace(' ','_').replace("'",'').replace('/','+')+str(postfix)
                postfix = postfix + 1
            else:
                unique = True
        self.chars[username]['ircname'] = ircname
        return ircname

    def userDecode(self,username):
        '''Convert an IRC name to one F-List uses.'''
        for user in self.chars:
            try:
                if self.chars[user]['ircname'] == username:
                    return user
            except:
                pass
        raise ValueError ("I don't know a character called "+str(username))

    @traceback
    def msgEncode(self,msg):
        '''Convert a message from F-List into one IRC is happy with.'''
        colours = {'white':'00','black':'01','red':'04','blue':'02','yellow':'08','green':'03','pink':'13','gray':'14','orange':'07','purple':'06','brown':'05','cyan':'11'}
#        msg = msg.replace('\n','  ').replace('\r','')
#        msg = msg.replace(':heart:','♥')
#        msg.replace(':cake:','[i]🎂[/i]')
#        msg.replace(':lif-angry:','^>_<^')
#        msg.replace(':lif-blush:','^^_^^;')
#        msg.replace(':lif-cry:',';^-_-^;')
#        msg.replace(':lif-evil:','^‾v‾^')
#        msg.replace(':lif-gasp:','^‾o‾^')
#        msg.replace(':lif-happy:','^^_^^')
#        msg.replace(':lif-meh:',"~^-_-^~")
#        msg.replace(':lif-neutral:','^-_-^')
#        msg.replace(':lif-ooh:','^‾O‾^')
#        msg.replace(':lif-purr:','^‾_‾^zzz')
#        msg.replace(':lif-roll:',"^'_'^")
#        msg.replace(':lif-sad:','^u.u^')
#        msg.replace(':lif-sick:','^Z_Z^')
#        msg.replace(':lif-smile:','^^_^^')
#        msg.replace(':lif-whee:','^‾x‾^')
#        msg.replace(':lif-wink:','^^_‾^')
#        msg.replace(':lif-wtf:','^O_o^')
#        msg.replace(':lif-yawn:','^‾O‾^;')
#        msg.replace(':hex-smile:',':-)')
#        msg.replace(':hex-confuse:',':-?')
#        msg.replace(':hex-eek:',':-O')
#        msg.replace(':hex-mad:',':-/')
#        msg.replace(':hex-roll:','=-)')
#        msg.replace(':hex-wink:',';-)')
#        msg.replace(':hex-twist:','>:D')
#        msg.replace(':hex-sad:',':-(')
#        msg = msg.replace(':hex-grin:',':-D')
#        msg.replace(':hex-red:',':-X')
#        msg.replace(':hex-razz:',':-P')
#        msg.replace(':hex-yell:',':-U')
        parts = re.split(r'(\[\/?noparse\])',msg)
        parts = parts [::2] #remove the noparse items
        output = ''
        for n,m in enumerate(parts):
            if n%2==0: #n%2==1 when inside a [noparse] tag. 
                m = re.sub(r'\[b\](.*?)\[\/b\]','\x02\\1\x02',m,flags=re.S|re.U)
                m = re.sub(r'\[u\](.*?)\[\/u\]','\x1f\\1\x1f',m,flags=re.S| re.U)
                m = re.sub(r'\[i\](.*?)\[\/i\]','\x1d\\1\x1d',m,flags=re.S|re.U)
#                m = re.sub(r'\[i\](.*?)\[\/i\]',r'/\1/',m)
                m = re.sub(r'\[s\](.*?)\[\/s\]',r'-\1-',m,flags=re.S|re.U)
                m = re.sub(r'\[url=(.*?)\](.*?)\[\/url\]',r'[\2|\1]',m,flags=re.S|re.U)
                m = re.sub(r'\[url\](.*?)\[\/url\]',r'\1',m,flags=re.S|re.U)
                m = re.sub(r'\[session=(.*?)\](.*?)\[\/session\]',r'[\2|\1]',m,flags=re.S|re.U)#needs chanEncode
                m = re.sub(r'\[header\](.*?)\[\/header\]','\x02\\1\x02',m,flags=re.S|re.U)
                m = re.sub(r'\[quote\](.*?)\[\/quote\]',r'"\1"',m,flags=re.S|re.U)
                m = re.sub(r'\[hr\]',r'--------',m,flags=re.S|re.U)
                #sub/sup and big/small are left - no way to translate them for IRC.
                m = re.sub(r'\[indent\](.*?)\[\/indent\]',r'  \1',m,flags=re.S|re.U)#This is not truly correct - indent ought to adjust all newlines in the block plus the originating line...
                m = re.sub(r'\[justify\](.*?)\[\/justify\]',r'\1',m,flags=re.S|re.U)
                m = re.sub(r'\[collapse=header\](.*?)\[\/collapse\]',r'\1',m,flags=re.S|re.U)
                m = re.sub(r'\[icon\](.*?)\[\/icon\]','\x02\\1\x02',m,flags=re.S|re.U)
                m = re.sub(r'\[user\](.*?)\[\/user\]',r'https://www.f-list.net/c/\1',m,flags=re.S|re.U)
                match = re.match(r'(.*?)\[color=(.*?)\](.*?)\[\/color\](.*)',m,flags=re.S|re.U)
                while match is not None:
                    try:
                        m = match.group(1)+'\x03'+colours[match.group(2)]+match.group(3)+'\x03'+match.group(4)
                    except:
                        break
                    match = re.match(r'(.*?)\[color=(.*?)\](.*?)\[\/color\](.*)',m,flags=re.S|re.U)
            output = output + m
        #Add highlighter
        msg = output.split(' ')
        if len(msg[0])>1:
            if msg[0][-1] in [',',':']:
                for name in self.chars: 
                    if name == msg[0][:-1]: #This may have some Unicode magic problems...
                        msg[0]=self.chars[name]['ircname']+msg[0][-1]
        msg = ' '.join(msg)
        return msg

    @traceback
    def msgDecode(self,msg):
        '''Convert an IRC message back into something F-List is happy decoding.'''
        colours = {"":'white','1':'black','2':'blue','3':'green','4':'red','5':'brown','6':'purple','7':'orange','8':'yellow','9':'green','10':'cyan','11':'cyan','12':'blue','13':'pink','14':'gray','15':'gray'}
        msg = re.sub('\x02(.*?)(\x02)?',r'[b]\1[/b]',msg)
        msg = re.sub('\x1d(.*?)(\x1d)?',r'[i]\1[/i]',msg)
        msg = re.sub('\x1f(.*?)(\x1f)?',r'[u]\1[/u]',msg)
        match = re.match(r'(.*?)\x03(\d)([^\x03]*?)(\x03)?(.*)',msg)
        while match is not None:
            try:
                msg = match.group(1)+'[color='+colours[match.group(2)[:2].strip('0')]+']'+match.group(3)+r'[/color]'+match.group(5)
            except:
                break
            match = re.match(r'(.*?)\x03(\d)([^\x03]*?)(\x03)?(.*)',msg)
        #replace irc names with Flist names if quoted.
        msg = msg.split(' ')
        if len(msg[0])>1:
            if msg[0][-1] in [',',':']:
                for name in self.chars:
                    if self.chars[name]['ircname'] == msg[0][:-1]: #This may have some Unicode magic problems...
                        msg[0]=name+msg[0][-1]
        msg = ' '.join(msg)
        return msg

#Loop functions
    @traceback
    def cb_PING(self):
        '''An automatic ping callback, every 60 seconds. Check the far end is alive.'''
        logging.info ('PINGing.')
        self.sendMsg('PIN')
        self.expectingping=True
        if (time.time() - self.lastping) > (self.pingrate*self.toomanypings):
            logging.warn('Losing connection due to no ping reply.')
            self.irc.transport.loseConnection()
            self.transport.loseConnection()

#These are all callbacks for Flist commands
    @traceback
    def fl_unknown(self,command,prefix,params):
        '''A handler for anything not correctly defined.'''
        logging.info ('Unknown command: '+str(command)+' : '+str(params))

    @traceback
    def fl_PIN(self,prefix,params):
        '''System ping.'''
        if self.expectingping:
            self.lastping=time.time()
            self.expectingping=False
        else:
            self.sendMsg('PIN')


    @traceback
    def fl_IDN(self,prefix,params):
        '''Login success, and your ident details.'''
        self.nick = params['character'].encode('utf8')
        self.irc.nick = self.userEncode(self.nick)
        self.reactor.callLater(1,self.sendMsg,'ORS')
        self.reactor.callLater(2,self.sendMsg,'CHA')

    @traceback
    def fl_CDS(self,prefix,params):
        '''Got channel description.'''
        name = h.unescape(params['channel']).encode('utf8')
        desc = h.unescape(params['description']).encode('utf8')
        desc = re.sub('[\r\n]+',' | ',desc)
        desc = self.msgEncode(desc)
        self.chans[name]['description'] = desc
        if desc is not '':
            self.irc.serverMsg(irc.RPL_TOPIC, self.chanEncode(name)+' :'+desc)
        else:
            self.irc.serverMsg(irc.RPL_NOTOPIC, self.chanEncode(name)+' :No topic is set')

    @traceback
    def fl_STA(self,prefix,params):
        '''User updates status.'''
        name = h.unescape(params['character']).encode('utf8')
        self.chars[name]['status'] = h.unescape(params['status']).encode('utf8')
        self.chars[name]['statusmsg'] = h.unescape(params['statusmsg']).encode('utf8').replace('\r',' ').replace('\n','|')

    @traceback
    def fl_NLN(self,prefix,params):
        '''User comes online.'''
        name = h.unescape(params['identity']).encode('utf8')
#        if name not in self.chars: self.chars[name]={}
        self.chars[name]['gender'] = h.unescape(params['gender']).encode('utf8')
        self.chars[name]['status'] = h.unescape(params['status']).encode('utf8')
        if 'statusmsg' not in self.chars[name]:
            self.chars[name]['statusmsg'] = ''
        if self.login_notify and name in self.friends:
            self.irc.serverMsg(irc.RPL_ISON,': '+self.userEncode(name))

    @traceback
    def fl_FLN(self,prefix,params):
        '''User goes offline.'''
        name =  h.unescape(params['character']).encode('utf8')
        self.chars[name]['status'] = 'offline'
        quitting=False
        if name in self.friends and self.login_notify:
            quitting=True
        if self.userEncode(name) in self.irc.pm:
            self.irc.pm.remove(self.userEncode(name))
            quitting=True
        else:
            for chan in self.irc.channels:
                if name in self.chans[self.chanDecode(chan)]['users']:
                    quitting=True
        if quitting:
            self.irc.userMsg(name,'QUIT :')

    @traceback
    def fl_TPN(self,prefix,params):
        '''User changes typing status.'''
        name = h.unescape(params['character']).encode('utf8')
        if self.typing_notify:
            if params['status']=='typing':
                self.irc.userMsg(self.userEncode(name),'PRIVMSG '+self.irc.nick+' :\x01 TYPING 1\x01')
            else:
                self.irc.userMsg(self.userEncode(name),'PRIVMSG '+self.irc.nick+' :\x01 TYPING 0\x01')

    @traceback
    def fl_LCH(self,prefix,params):
        '''User leaves channel.'''
        name = h.unescape(params['channel']).encode('utf8')
        user = h.unescape(params['character']).encode('utf8')
#        if name not in self.chans: self.chans[name]={}
        if 'users' not in self.chans[name]: self.chans[name]['users']=[]
        if user in self.chans[name]['users']: self.chans[name]['users'].remove(user)
        self.irc.userMsg(user,'PART '+self.chanEncode(name))

    @traceback
    def fl_JCH(self,prefix,params):
        '''User joins channel.'''
        name = h.unescape(params['channel']).encode('utf8')
        user = h.unescape(params['character']['identity']).encode('utf8')
#        if name not in self.chans: self.chans[name]={}
        if 'users' not in self.chans[name]: self.chans[name]['users']=[]
        if user not in self.chans[name]['users']: self.chans[name]['users'].append(user)
        self.irc.userMsg(user,'JOIN '+self.chanEncode(name))
        if user in self.chans[name]['ops']:
            self.irc.serverMsg(irc.RPL_CHANNELMODEIS,':+o '+self.userEncode(user),self.chanEncode(name))
        if user ==self.chans[name]['owner']:
            self.irc.serverMsg(irc.RPL_CHANNELMODEIS,':+O '+self.userEncode(user),self.chanEncode(name))

    @traceback
    def fl_ICH(self,prefix,params):
        '''Initial channel data.'''
        name = h.unescape(params['channel']).encode('utf8')
        users = [h.unescape(c['identity']).encode('utf8') for c in params['users']]
#        if name not in self.chans: self.chans[name]={}
        self.chans[name]['users']=users
        listusers = []
        for user in users:
            if user in self.chans[name]['ops']:
#                logging.info ('@'+user)
                listusers.append('@'+self.userEncode(user))
            else:
#                logging.info (user)
                listusers.append(self.userEncode(user))
        self.irc.serverMsg(irc.RPL_NAMREPLY, '= '+self.chanEncode(name)+' :'+' '.join(listusers))
        self.irc.serverMsg(irc.RPL_ENDOFNAMES,self.chanEncode(name)+' :End of NAMES list')

    @traceback
    def fl_COL(self,prefix,params):
        '''User Op list.'''
        name = h.unescape(params['channel']).encode('utf8')
        ops = [h.unescape(c).encode('utf8') for c in params['oplist']]
        self.chans[name]['owner'] = ops[0]
        if ops[0] =='': ops = ops[1:]
        self.chans[name]['ops'] = ops
        for user in self.chans[name]['users']:
            if user in ops:
                self.irc.serverMsg(irc.RPL_CHANNELMODEIS,':+o '+self.userEncode(user),self.chanEncode(name))
            if user ==self.chans[name]['owner']:
                self.irc.serverMsg(irc.RPL_CHANNELMODEIS,':+O '+self.userEncode(user),self.chanEncode(name))

    @traceback
    def fl_COA(self,prefix,params):
        '''Promote user to Op.'''
        name = h.unescape(params['channel']).encode('utf8')
        user = h.unescape(params['character']).encode('utf8')
        self.chans[name]['ops'].append(user)
        self.serverMsg(irc.RPL_CHANNELMODEIS,':+o '+self.userEncode(user),self.chanEncode(name))

    @traceback
    def fl_COR(self,prefix,params):
        '''Demote user from Op.'''
        name = h.unescape(params['channel']).encode('utf8')
        user = h.unescape(params['character']).encode('utf8')
        self.chans[name]['ops'].remove(user)
        self.serverMsg(irc.RPL_CHANNELMODEIS,':-o '+self.userEncode(user),self.chanEncode(name))

    @traceback
    def fl_CSO(self,prefix,params):
        '''Set new channel owner.'''
        name = h.unescape(params['channel']).encode('utf8')
        user = h.unescape(params['character']).encode('utf8')
        oldowner = self.chans[name]['owner']
        self.serverMsg(irc.RPL_CHANNELMODEIS,':-O '+self.userEncode(oldowner),self.chanEncode(name))
        self.chans[name]['owner'] = user
        self.serverMsg(irc.RPL_CHANNELMODEIS,':+O '+self.userEncode(user),self.chanEncode(name))

    @traceback
    def fl_CTU(self,prefix,params):
        '''User temp timeoutted from channel.'''
        name = h.unescape(params['channel']).encode('utf8')
        kicker = h.unescape(params['operator']).encode('utf8')
        user = h.unescape(params['character']).encode('utf8')
        time = params['length'] #minutes
#        self.irc.userMsg(kicker,'KICK '+self.chanEncode(name)+' '+self.userEncode(user))

    @traceback
    def fl_CKU(self,prefix,params):
        '''User kicked from channel.'''
        name = h.unescape(params['channel']).encode('utf8')
        kicker = h.unescape(params['operator']).encode('utf8')
        user = h.unescape(params['character']).encode('utf8')
        self.irc.userMsg(kicker,'KICK '+self.chanEncode(name)+' '+self.userEncode(user))

    @traceback
    def fl_CBU(self,prefix,params):
        '''User kickbanned from channel.'''
        self.fl_CKU(prefix,params)

    @traceback
    def fl_CIU(self,prefix,params):
        '''Chatroom invite.'''
        inviter = self.userEncode(h.unescape(params['sender']).encode('utf8'))
        desc = h.unescape(params['name']).encode('utf8')
        channel = self.chanEncode(h.unescape(params['title']).encode('utf8'))
        nick = self.irc.nick
        self.irc.serverMsg(irc.RPL_INVITED,channel+' '+nick+' '+inviter+' :'+nick+' has been invited by '+inviter)

    @traceback
    def fl_CON(self,prefix,params):
        '''Number of connected users.'''
        self.sys_params['connected_users'] = params['count']

    @traceback
    def fl_VAR(self,prefix,params):
        '''System variables.'''
        val = params['value']
        if isinstance(val,basestring):
            val = h.unescape(val).encode('utf8')
        self.sys_params[params['variable']]=val

    @traceback
    def fl_UPT(self,prefix,params):
        '''Uptime info.'''
        self.sys_params['starttime']=params['starttime']
        self.sys_params['total_connection_count']=params['accepted']
        self.sys_params['current_users']=params['users']
        self.sys_params['current_channels']=params['channels']
        self.sys_params['max_users']=params['maxusers']

    @traceback
    def fl_ADL(self,prefix,params):
        '''ChatOp List.'''
        self.sys_params['chatops']=[h.unescape(c).encode('utf8') for c in params['ops']]

    @traceback
    def fl_AOP(self,prefix,params):
        '''ChatOp Promotion.'''
        self.sys_params['chatops'].append(h.unescape(params['character']).encode('utf8'))

    @traceback
    def fl_DOP(self,prefix,params):
        '''ChatOp Demotion.'''
        self.sys_params['chatops'].remove(h.unescape(params['character']).encode('utf8'))

    @traceback
    def fl_BRO(self,prefix,params):
        '''System broadcast.'''
        self.irc.serverMsg('NOTICE',':'+params['message'])
        logging.info ('BROADCAST: '+str(params['message']))
        #Some sort of serverMsg

    @traceback
    def fl_SYS(self,prefix,params):
        '''System messages.'''
        self.irc.serverMsg('NOTICE',':'+h.unescape(params['message']).encode('utf8'))
        logging.info ('Sys: '+str(params))

    @traceback
    def fl_ERR(self,prefix,params):
        '''Error messages.'''
        if params['number'] in [0,1,2,3,4,8,9,11,30,33,62,67,-1,-4,-5]:
            self.irc.serverMsg('NOTICE',':'+h.unescape(params['message']).encode('utf8'))
        else:
            self.irc.userMsg('info','PRIVMSG '+self.irc.nick+' :'+h.unescape(params['message']).encode('utf8'))
        logging.info ('Err: '+str(params))

    @traceback
    def fl_RTB(self,prefix,params):
        '''Real-time bridge info. This does stuff like friend invites and stuff.'''
        logging.info ('RTB: '+str(params))

    @traceback
    def fl_HLO(self,prefix,params):
        '''Server hello info.'''
        self.sys_params['hello'] = h.unescape(params['message']).encode('utf8')
        self.irc.hello=self.sys_params['hello']

    @traceback
    def fl_RLL(self,prefix,params):
        '''Dice rolling in channel.'''
        user = self.userEncode(params['character'])
        ircchan = self.chanEncode(params['channel'])
#        msg = h.unescape(params['message']).encode('utf8')
        type = params['type']
        if type == 'dice':
            numbers = str(params['results'])
            dice = str([x.encode('utf8') for x in params['rolls']])
            result = str(params['endresult'])
            self.irc.userMsg(user,'NOTICE '+ircchan+' :'+user+' rolled '+dice+' for '+str(numbers)+', totalling '+result)
        if type == 'bottle':
            result = self.userEncode(params['target'])
            self.irc.userMsg(user,'NOTICE '+ircchan+' :'+user+' spun the bottle and selected: '+result)

    @traceback
    def fl_RMO(self,prefix,params):
        '''Change channel mode.'''
        name = h.unescape(params['channel']).encode('utf8')
        mode = h.unescape(params['mode'])[0].encode('utf8')
        #Some type of serverMsg?

    @traceback
    def fl_MSG(self,prefix,params):
        '''User messages channel.'''
        name = h.unescape(params['channel']).encode('utf8')
        user = h.unescape(params['character']).encode('utf8')
        msgs = h.unescape(self.msgEncode(params['message'])).encode('utf8').split('\n')
        for msg in msgs:
            msg = msg.strip('\r')
            msg = re.sub(r'^/me *(.*)','\x01ACTION \\1\x01',msg)
            self.irc.userMsg(user,'PRIVMSG '+self.chanEncode(name)+' :'+msg)

    @traceback
    def fl_PRI(self,prefix,params):
        '''User private messages you.'''
        user = h.unescape(params['character']).encode('utf8')
        msgs = h.unescape(self.msgEncode(params['message'])).encode('utf8').split('\n')
        for msg in msgs:
            msg = msg.strip('\r')
            msg = re.sub(r'^/me *(.*)','\x01ACTION \\1\x01',msg)
            self.irc.userMsg(user,'PRIVMSG '+self.irc.nick+' :'+msg)

    @traceback
    def fl_CHA(self,prefix,params):
        '''Update public channel list.'''
        clist = params['channels']
        for c in clist:
            name = h.unescape(c['name']).encode('utf8')
            self.chans[name]['mode'] = h.unescape(c['mode'])[0].encode('utf8')
            self.chans[name]['usercount'] = c['characters']
            if 'users' not in self.chans[name]: self.chans[name]['users'] = []
            if 'description' not in self.chans[name]: self.chans[name]['description']=name
            self.chanEncode(name)
        if self.irc.logging_in:
            self.irc.finishLogin()
        else:
            self.irc.serverMsg(irc.RPL_LISTSTART)
            for name in self.chans:
                desc = self.chans[name]['description']
                users = self.chans[name]['usercount']
                self.irc.serverMsg(irc.RPL_LIST,self.chanEncode(name)+' '+str(users)+' :'+str(desc))
            self.irc.serverMsg(irc.RPL_LISTEND)

    @traceback
    def fl_LIS(self,prefix,params):
        '''Update user list.'''
        clist = params['characters']
        for c in clist:
            name = h.unescape(c[0]).encode('utf8')
            self.chars[name]['gender']=h.unescape(c[1]).encode('utf8')
            self.chars[name]['status']=h.unescape(c[2]).encode('utf8')
            self.chars[name]['statusmsg']=h.unescape(c[3]).encode('utf8').replace('\r',' ').replace('\n','|')
            self.userEncode(name)
#        self.irc.serverMsg('NOTICE',':character info loaded.')

    @traceback
    def fl_ORS(self,prefix,params):
        '''Update private room list.'''
        clist = params['channels']
        for c in clist:
            name = h.unescape(c['name']).encode('utf8')
            if name not in self.chans: self.chans[name]={}
            self.chans[name]['description'] = h.unescape(c['title']).encode('utf8')
            self.chans[name]['mode'] = 'c'
            self.chans[name]['usercount'] = c['characters']
            if 'users' not in self.chans[name]: self.chans[name]['users'] = []
            self.chanEncode(name)

    @traceback
    def fl_IGN(self,prefix,params):
        '''Handle ignore list. This is not very well documented...'''
#        self.ignores=params['characters']
        #Needs debugging
        logging.info ('IGN: '+str(params))

    @traceback
    def fl_FRL(self,prefix,params):
        '''Handle friends list.'''
        self.friends=params['characters']
        #Needs debugging
        logging.info ('FRL: '+str(params))

    @traceback
    def fl_FKS(self,prefix,params):
        '''Find Kink response.'''
# {u'kinks': [551, 463], u'characters': [u'Trainer Georgina...
        mchars=[h.unescape(x).encode('utf8') for x in params['characters']]
        mchars = {c:self.chars[c] for c in mchars}
        statusorder = sorted(mchars.keys(),key=lambda x: mchars[x]['status'])
        for char in statusorder:
            msg = self.userEncode(char)+'('+mchars[char]['gender']+'): '+mchars[char]['status']
            if mchars[char]['statusmsg'] != '':
               msg = msg + '('+mchars[char]['statusmsg']+')'
            self.irc.userMsg('info','PRIVMSG '+self.irc.nick+' :'+msg)
        logging.info ('FKS: '+str(params))

    @traceback
    def fl_KID(self,prefix,params):
        '''Kink response Currently hardcoded to reply as infobot.'''
        if params['type'] not in ['start','end']:
            user = h.unescape(params['character']).encode('utf8')
            ircuser = self.userEncode(user)
            type = h.unescape(params['key']).encode('utf8')
            data = h.unescape(params['value']).encode('utf8')
            self.irc.userMsg('info','PRIVMSG '+self.irc.nick+' :'+type+': '+data)
#            self.irc.sendLine('info!info@bot.flist PRIVMSG '+self.irc.nick+' :'+type+': '+data)
        logging.info ('KID: '+str(params))

    @traceback
    def fl_PRD(self,prefix,params):
        '''Profile information. Currently hardcoded to reply as infobot.'''
        if params['type'] not in ['start','end']:
            user = h.unescape(params['character']).encode('utf8')
            ircuser = self.userEncode(user)
            type = h.unescape(params['key']).encode('utf8')
            data = h.unescape(params['value']).encode('utf8')
            self.irc.userMsg('info','PRIVMSG '+self.irc.nick+' :'+type+': '+data)
#            self.irc.sendLine('info!info@bot.flist PRIVMSG '+self.irc.nick+' :'+type+': '+data)
        logging.info ('PRD: '+str(params))

    @traceback
    def fl_LRP(self,prefix,params):
        '''Roleplay ad. These may be multi-line ads, but I just want single line, so break it.'''
        user = h.unescape(params['character']).encode('utf8')
        channel = h.unescape(params['channel']).encode('utf8')
        ircchan = self.chanEncode(channel)
        msg = self.msgEncode(h.unescape(params['message']).encode('utf8')).replace('\n','  ')
        self.irc.userMsg(user,'NOTICE '+ircchan+' :'+msg)

    @traceback
    def fl_SFC(self,prefix,params):
        '''Response to an admin ticket This is kind of buggy..'''
        logging.info ('SFC: '+str(params))

#JSON endpoint stuff
    def identify(self, account='', password=''):
        '''This goes off to get the login ticket. It doesn't use the generic JSON caller from below to prevent loops.'''
        logging.info('Attempting login with account '+account)
        if account == '':
            if self.account != '':
                account = self.account
            else:
                raise ValueError('need a name at least once.')
        else:
            self.account = account
        if password == '':
            if self.password != '':
                password = self.password
            else:
                raise ValueError('need a password at least once.')
        else:
            self.password = password
        payload = urllib.urlencode({'account':account,'password':password})
        site = "www.f-list.net"
        API = '/json/getApiTicket.php'
        response = urllib2.urlopen('https://'+site+API,payload).read()
        reply = json.loads (response)
        if 'error' not in reply or reply['error'] =='':
            self.ticket = reply['ticket']
        else:
            raise ValueError('Error with payload: '+str(payload)+' ticket: ' +str(reply))
        logging.info('Got ticket: '+self.ticket)
        return reply

    @traceback
    def getKinks(self):
        '''Get and format the kinks block properly for cross-reference.'''
        kinks = {}
        kitems = self.getJSONEndpoint('kink-list')
        opposites={137:157,163:16,513:515,512:514,141:158,577:578,229:340,422:423}
        rop = {y:x for x,y in opposites.items()}
        for group in kitems['kinks']:
            for k in kitems['kinks'][group]['items']:
                kdata = {}
                id = k['kink_id']
                kdata['group'] = h.unescape(group).encode('utf8')
                kdata['name'] = h.unescape(k['name']).encode('utf8')
                kdata['description'] = h.unescape(k['description']).encode('utf8')
                if id in opposites:
                    kdata['opposite']=opposites[id]
                if id in rop:
                    kdata['opposite']=rop[id]
                kinks[id]=kdata
        self.kinks = kinks

    @traceback
    def getInfo(self,name):
        '''Get and format the info from a char for the infobot to use.'''
        ret = h.unescape(self.getJSONEndpoint('character-get',name)['character']['description']).encode('utf8')
#        return '\n'.join([self.msgEncode(l) for l in ret.split('\n')])
        return self.msgEncode(ret)

    @traceback
    def fillKinks(self,name):
        self.chars[name]['kinks']={}
        k = self.getJSONEndpoint('character-kinks',name)['kinks']
        for v in ['fave','yes','maybe','no']:
            self.chars[name]['kinks'][v]=[]
            for group in k:
                for id in k[group]['items']:
                    if id['choice'].lower()==v:
                        self.chars[name]['kinks'][v].append(int(id['id']))

    @traceback
    def getKinkInfo(self,name):
        '''Get and format the info from a char for the infobot to use.'''
        if self.chars[self.nick]['kinks']=="" or self.chars[self.nick]['kinks']=={}:
            self.fillKinks(self.nick)
        self.fillKinks(name)
        myk = self.chars[self.nick]['kinks']
        k = self.chars[name]['kinks']
        corr={}
        for x in k:
            corr[x]={y:'white' for y in k[x]}
        order=['fave','yes','maybe','no']
        rules={'fave':{'fave':'purple','yes':'green','maybe':'gray','no':'red'},
               'yes':{'fave':'green','yes':'blue','maybe':'yellow','no':'red'},
               'maybe':{'fave':'blue','yes':'yellow','maybe':'gray','no':'orange'},
               'no':{'fave':'red','yes':'red','maybe':'gray','no':'black'}}
        for val in corr:
            for id in corr[val]:
                for myval in rules[val]:
                    if 'opposite' in self.kinks[id]:
                        if self.kinks[id]['opposite'] in myk[myval]: corr[val][id]=rules[val][myval]
                    else:
                        if id in myk[myval]: corr[val][id]=rules[val][myval]
        ret = ''
        for val in order:
            ret = ret + string.capwords(val)+': '+'  '.join(['[color='+corr[val][x]+']'+self.kinks[x]['name']+'[/color]' for x in corr[val]])+'\n'
#        return '\n'.join([self.msgEncode(l) for l in ret.split('\n')])
        return self.msgEncode(ret)

    def getJSONEndpoint(self,type,*args):
        '''A generic endpoint fetcher that autosatisfies the myriad different type of API Flist has.'''
        if self.account == '' or self.ticket == '': return {}
        payload = urllib.urlencode({'account':self.account,'ticket':self.ticket})
        site = "https://www.f-list.net"
        try:
            type = type.encode('ascii','ignore')
            API = '/json/api/%s.php'% type
            if type in ['character-get']:
                request = site+API+r'?name='+urllib.quote(args[0])
            elif type in ['request-accept','request-cancel','request-deny']:
                request = site+API+r'?request_id='+urllib.quote(args[0])
            elif type in ['request-send','friend-remove']:
                request = site+API+r'?source_name='+urllib.quote(args[0])+r'&dest_name='+urllib.quote(args[1])
            elif type in ['bookmark-add','bookmark-remove','character-customkinks','character-get','character-images','character-info','character-kinks']:
                request = site+API+r'?name='+urllib.quote(args[0])
            elif type in ['info-list','kink-list','character-list','bookmark-list','group-list','ignore-list','request-list','request-pending']:
                request = site+API
            else:
                request = site+API
        except:
            logging.error('getJSONEndpoint threw a strange error with '+str(args)+' Did you somehow put UTF8 into it?')
            return {}

        payload = urllib.urlencode({'account':self.account,'ticket':self.ticket})
        response = urllib2.urlopen(request,payload)
        reply = json.load (response)
        if 'error' in reply:
            if 'Your login ticket has expired' in reply['error']:
                self.identify()
                payload = urllib.urlencode({'account':self.account,'ticket':self.ticket})
                response = urllib2.urlopen(request,payload)
                reply = json.load (response)
            elif reply['error'].strip() != '':
                raise ValueError (type+' <- '+str(payload)+' = '+str(reply))
#        logging.debug('Got JSON reply from '+type+': '+str(reply))
        return reply

    @traceback
    def getFriendRequests(self):
        '''This function merely fills the friend request data. It should be called on appropriate RTB events.'''
        self.frequests = {x['source']:x['id'] for x in self.getJSONEndpoint('request-list')['requests'] if x['dest']==self.nick}

    @traceback
    def getFriends(self):
        '''This function merely fills the friend list. Make sure to call this every time it might change!.'''
        self.friends = [x['dest'] for x in self.getJSONEndpoint('friend-list')['friends'] if x['source']==self.nick]

    @traceback
    def getIgnores(self):
        '''Fill the ignore list. UNFINISHED - I have no ignores!'''
        pass
#        self.ignores = [(x['source'],x['id']) for x in self.getJSONEndpoint('ignore-list')['requests'] if x['dest']==self.nick]

class FlistWSFactory(WebSocketClientFactory):
    def __init__(self,endpoint,reactor,irc=None):
        self.irc = irc
        self.reactor = reactor
        WebSocketClientFactory.__init__(self, endpoint, debug = False)

    def buildProtocol(self,reactor):
        if self.irc is not None:
            p = FlistProtocol(self.reactor,self.irc)
        else:
            p = FlistProtocol(self.reactor)
        p.factory = self
        return p

