import twisted.words.protocols.irc as irc
import re
import json
import datetime
import socket
import time
import logging
import HTMLParser
h = HTMLParser.HTMLParser()
    
import traceback as tb
from do_log import *

class Bot:    
    def __init__(self, irc):
        self.irc=irc
#        self.irc.flist=self.irc.flist
        self.name='info'

    @traceback
    def botSay(self,msg):
        for line in msg.split('\n'):
            self.irc.userMsg(self.name, 'PRIVMSG '+self.irc.nick+' :'+line)

    @traceback
    def bot_info(self,prefix,params):
        '''The generic handler for info, the main information bot.'''
        params = params[0].split()
        logging.info (params)
        method = getattr(self, "bot_info_%s" % params[0].lower(), None)
        if method is not None:
            method(prefix, params[1:])
    
    @traceback
    def bot_info_about(self,prefix,params):
        '''Command about: gives as much information on a char as it can.'''
        target = params[0].strip()
        try:
            user = self.irc.flist.userDecode(target)
        except:
            logging.debug(tb.format_exc())
            self.irc.serverMsg(irc.ERR_NOSUCHNICK,params[0]+' :User unknown.')
            return
        desc = str(self.irc.flist.getInfo(user))
#        desc = h.unescape(self.irc.flist.getJSONEndpoint('character-get',user)['character']['description']).encode('utf8')
        for l in desc.split('\n'):
            self.botSay(l.strip('\r'))
        k = self.irc.flist.getKinkInfo(user)
        for l in k.split('\n'):
            self.botSay(l.strip('\r'))
        for item in self.irc.flist.chars[user]:
            if item not in ['ircname','kinks']:
                self.botSay(item+': '+str(self.irc.flist.chars[user][item]))
        par = json.dumps({'character':user})
        self.irc.flist.sendMsg('KIN '+par)
        self.irc.flist.sendMsg('PRO '+par)
    
    @traceback
    def bot_info_kinks(self,prefix,params):
        for n in sorted(self.irc.flist.kinks):
            self.botSay(str(n)+': '+self.irc.flist.kinks[n]['name'])
    
    @traceback
    def bot_info_kink(self,prefix,params):
        input = ' '.join(params).strip().lower()
        if input.isdigit():
            if int(input) in self.irc.flist.kinks:
                input = int(input)
                self.botSay(self.irc.flist.kinks[input]['name']+': '+self.irc.flist.kinks[input]['description'])
        else:
            try:
                names = {self.irc.flist.kinks[x]['name'].lower():x for x in self.irc.flist.kinks}
                if input in names.keys():
                    self.botSay(str(names[input])+': '+self.irc.flist.kinks[names[input]]['description'])
                else:
                    self.botSay('Kinks unknown.')
            except:
                self.botSay('Kink unknown.')
    
    @traceback
    def bot_info_find(self,prefix,params):
        data = {}
        maintokens = {
        'kink:':{self.irc.flist.kinks[x]['name'].lower():x for x in self.irc.flist.kinks},
        'gender:':["male", "female", "transgender", "herm", "shemale", "male-herm", "cunt-boy", "none"],
        'orientation:':["straight", "gay", "bisexual", "asexual", "unsure", "bi - male preference", "bi - female preference", "pansexual", "bi-curious"],
        'language:':["dutch", "english", "french", "spanish", "german", "russian", "chinese", "japanese", "portuguese", "korean", "arabic", "italian", "swedish", "other"],
        'furrypref:':["no furry characters, just humans", "no humans, just furry characters", "furries ok, humans preferred", "humans ok, furries preferred", "furs and / or humans"],
        'role:':["always dominant", "usually dominant", "switch", "usually submissive", "always submissive", "none"]}
        type = ''
        oldwords = ''
        for word in params:
            word = word.lower()
            if word in maintokens:
                logging.info ('New type: '+str(word))
                oldwords = ''
                type = word
                data[type[:-1]+'s'] = []
            elif type != '':
                word = (oldwords + ' '+word).strip()
                logging.info ('New word: '+str(word))
    #            logging.info ('maintoken: '+str(maintokens[type]))
                if type == 'kink:':
                    if word.isdigit():
                        data[type[:-1]+'s'].append(int(word))
                    elif word in maintokens[type].keys():
                        data[type[:-1]+'s'].append(maintokens[type][word])
                    else:
                        oldwords = word
                elif word in maintokens[type]:
                    data[type[:-1]+'s'].append(word)
                else:
                    oldwords = word
        par = json.dumps(data)
        logging.info('FKS '+par) 
        self.irc.flist.sendMsg('FKS '+par) 

    @traceback
    def bot_info_notify(self,prefix,params):
        logging.debug(params)
        if params[0].lower()=='typing':
            if len(params)>1:
                if params[1].lower()=='on':
                    self.irc.flist.typing_notify=True
                    self.botSay('Typing notices on')
                elif params[1].lower()=='off':
                    self.irc.flist.typing_notify=False
                    self.botSay('Typing notices off')
            else:
               self.botSay('Typing notices are '+str(self.irc.flist.typing_notify))
        if params[0].lower()=='login':
            if len(params)>1:
                if params[1].lower()=='on':
                    self.irc.flist.login_notify=True
                    self.botSay('Login notices on')
                elif params[1].lower()=='off':
                    self.irc.flist.login_notify=False
                    self.botSay('Login notices off')
            else:
               self.botSay('Login notices are '+str(self.irc.flist.login_notify))

    @traceback
    def bot_info_friend_requests(self,prefix,params):
        self.irc.flist.getFriendRequests()
        self.botSay('Incoming friend requests:\n'+'\n'.join([self.irc.flist.userEncode(x) for x in self.irc.flist.frequests]))

    def timeFormat(self,secs):
        if secs < 3: return str(secs)+'s'
        secs = int(secs)
        if secs < 60: return str(secs)+'s'
        mins = int(secs/60)
        if mins < 10: return str(mins)+'m'+str(secs-mins*60)+'s'
        if mins < 30: return str(mins)+'m'
        if mins < 60: return str(int(mins/5)*5)+'m'
        hrs = int(mins/60)
        if hrs < 4: return str(hrs)+'h'+str(int((mins-hrs*60)/10)*10)+'m'
        if hrs < 12: return str(hrs)+'h'+str(int((mins-hrs*60)/30)*30)+'m'
        if hrs < 24: return str(hrs)+'h'
        dys = int(hrs/24)
        if dys < 2: return str(dys)+'d'+str(hrs-dys*24)+'h'
        if dys < 7: return str(dys)+'d'
        wks = int(dys/7)
        if wks < 4: return str(wks)+'w'+str(dys-wks*7)+'d'
        mhs = int(dys/30.5)
        if mhs < 6: return str(mhs)+'mo'+str(int((dys-mhs*30.5)/7))+'w'
        if mhs < 12: return str(mhs)+'mo'
        yrs = int(dys/365)
        if yrs < 2: return str(yrs)+'y'+str(int((dys-yrs*365)/30.5))+'mo'
        return str(yrs)+'y'

    @traceback
    def bot_info_friend_list(self,prefix,params):
        result = self.irc.flist.getJSONEndpoint('friend-list')
#        self.botSay(str(result))
        f = {}
        for x in [x for x in result['friends'] if x['source']==self.irc.flist.nick]:
            name = x['dest']
            if name in self.irc.flist.chars:
                s = self.irc.flist.chars[name]['status']
                if s == "": s = 'offline'
                m = self.irc.flist.chars[name]['statusmsg']
            else:
                s='offline'
                m = ''
            f[self.irc.flist.userEncode(name)]={'status':s,'statusmsg':m,'last_online':x['last_online']}
        on = []
        offs = []
        for x in f:
            if f[x]['status'] == 'offline':
                offs.append((f[x]['last_online'],x))
            else:
                l = x+'('+f[x]['status']+')'
                if f[x]['statusmsg']!='':
                    l = l +'('+f[x]['statusmsg']+')'
#                l=l+'('+self.timeFormat(f[x]['last_online'])+' ago)'
                on.append(l)
        offs.sort()
        off = [x[1]+'('+self.timeFormat(x[0])+' ago)' for x in offs]
        ret = 'Online: '
        self.botSay('Online: '+' '.join(on)+'\nOffline: '+' '.join(off))

    @traceback
    def bot_info_friend(self,prefix,params):
        try:
            target = self.irc.flist.userDecode(params[0])
        except Exception as e:
            self.botSay(str(e))
        result = self.irc.flist.getJSONEndpoint('request-send',self.irc.flist.nick,target)
        if 'error' not in result or result['error']=='':
            self.botSay('Friend requested: '+str(params[0]))
        else:
            self.botSay(str(result))

    @traceback
    def bot_info_friend_cancel(self,prefix,params):
        try:
            target = self.irc.flist.userDecode(params[0])
        except Exception as e:
            self.botSay(str(e))
        result = self.irc.flist.getJSONEndpoint('request-cancel',target)
        if 'error' not in result or result['error']=='':
            self.botSay('Outgoing friend request cancelled to: '+str(params[0]))
        else:
            self.botSay(str(result))

    @traceback
    def bot_info_friend_accept(self,prefix,params):
        try:
            target = self.irc.flist.userDecode(params[0])
        except Exception as e:
            self.botSay(str(e))
        result = self.irc.flist.getJSONEndpoint('request-accept',str(self.irc.flist.frequests[target]))
        if 'error' not in result or result['error']=='':
            self.botSay('Friend accepted: '+str(params[0]))
        else:
            self.botSay(str(result))

    @traceback
    def bot_info_friend_reject(self,prefix,params):
        try:
            target = self.irc.flist.userDecode(params[0])
        except Exception as e:
            self.botSay(str(e))
        result = self.irc.flist.getJSONEndpoint('request-deny',target)
        if 'error' not in result or result['error']=='':
            self.botSay('Friend rejected: '+str(params[0]))
        else:
            self.botSay(str(result))

    @traceback
    def bot_info_friend_remove(self,prefix,params):
        try:
            target = self.irc.flist.userDecode(params[0])
        except Exception as e:
            self.botSay(str(e))
        result = self.irc.flist.getJSONEndpoint('friend-remove',target)
        if 'error' not in result or result['error']=='':
            self.botSay('Friend removed: '+str(params[0]))
        else:
            self.botSay(str(result))

    @traceback
    def bot_info_bookmark_list(self,prefix,params):
        self.botSay(str(self.irc.flist.getJSONEndpoint('bookmark-list')))
    @traceback
    def bot_info_bookmark_add(self,prefix,params):
        try:
            target = self.irc.flist.userDecode(params[0])
        except Exception as e:
            self.botSay(str(e))
        self.botSay(str(self.irc.flist.getJSONEndpoint('bookmark-add',target)))
    @traceback
    def bot_info_bookmark_remove(self,prefix,params):
        try:
            target = self.irc.flist.userDecode(params[0])
        except Exception as e:
            self.botSay(str(e))
        self.botSay(str(self.irc.flist.getJSONEndpoint('bookmark-remove',target)))

    @traceback
    def bot_info_character_customkinks(self,prefix,params):
        try:
            target = self.irc.flist.userDecode(params[0])
        except Exception as e:
            self.botSay(str(e))
        self.botSay(str(self.irc.flist.getJSONEndpoint('character-customkinks',target)))
    @traceback
    def bot_info_character_get(self,prefix,params):
        try:
            target = self.irc.flist.userDecode(params[0])
        except Exception as e:
            self.botSay(str(e))
        self.botSay(str(self.irc.flist.getJSONEndpoint('character-get',target)))
    @traceback
    def bot_info_character_images(self,prefix,params):
        try:
            target = self.irc.flist.userDecode(params[0])
        except Exception as e:
            self.botSay(str(e))
        self.botSay(str(self.irc.flist.getJSONEndpoint('character-images',target)))
    @traceback
    def bot_info_character_info(self,prefix,params):
        try:
            target = self.irc.flist.userDecode(params[0])
        except Exception as e:
            self.botSay(str(e))
        self.botSay(str(self.irc.flist.getJSONEndpoint('character-info',target)))

    @traceback
    def bot_info_character_list(self,prefix,params):
        self.botSay(str(self.irc.flist.getJSONEndpoint('character-list')))

    @traceback
    def bot_info_group_list(self,prefix,params):
        self.botSay(str(self.irc.flist.getJSONEndpoint('group-list')))
#    def bot_info_ignore_list(self,prefix,params):
#        self.botSay(str(self.irc.flist.getJSONEndpoint('ignore-list')))
#    def bot_info_request_list(self,prefix,params):
#        self.botSay(str(self.irc.flist.getJSONEndpoint('request-list')))
    @traceback
    def bot_info_request_pending(self,prefix,params):
        self.botSay(str(self.irc.flist.getJSONEndpoint('request-pending')))

