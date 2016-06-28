This is an IRC server interface on to the websockets connection for F-list's chat function.

To get started, you'll need python2.7 and matching python-twisted and python-autobahn modules installed.

From there, running fchat-irc will spin up an IRC server, defaultly set to port 8002 on localhost. You can connect to it using any standard IRC client.

You will need to log in to the server using your login details and password, and this will be transferred on to the F-list chat.

To select different characters, append your username with an = , then the character name (replacing spaces with underscores) e.g.

user1=John_Harrington

Chat
----

Channels will appear as, well, channels. Creating new private channels is untested as of now.
