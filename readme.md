Gitlabot
========


Gitlabot is a small webserver with IRC client written in Python. It uses the tornado framework for the webserver, and brukva for passing messages between the webserver thread and the IRC thread. The goal is to set your GitLab webhook to the webserver (localhost:8889 by default), and this application will then post the commitmessages and their author and url to the IRC channel given.

How to use
----------

Make sure you have Redis installed, and the python-dev package (that's what it's called on Ubuntu at least)

Install the requirements as specified in requirements.txt. Please use a virtualenv.

Please create a local.py file with contents as specified in local.py.example, so you can set your IRC channel, the botname, and some other parameters.

Set one or more deploy hook(s) in a GitLab project to http://localhost:8889/

Advice is to run the bot in a screen or tmux session, so it can continue running without you having to keep your shell session opened.

If you don't like the messages the bot shows, you can change them in the MainHandler class.


Warning
-------

This is buggy code. On whatever error, the application will quit and fail.


Credits
-------

Most of the code for the IRC part was borrowed from https://github.com/nod/iobot. Thx :)


Notice
------
Gitlabot comes with ABSOLUTELY NO WARRANTY; for details see the LICENCE file.
This is free software, and you are welcome to redistribute it
under certain conditions;

Contributions can be shared at https://github.com/maikelwever/gitlabot
