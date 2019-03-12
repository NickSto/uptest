uptest
======

We've all run into the situation where you connect to a wifi hotspot but discover it's not actually providing internet access. Or worse, you might be connected for hours but things stop loading, and you can't tell what's wrong or how bad it is.

This project offers several tools to make these situations easier to discover and diagnose.


## Usage

### Terminal

For a quick and simple internet connectivity monitor, run `$ bash uptest.sh`. This will ping google.com every 5 seconds and show your latency and whether the ping was dropped.

A more complete and capable script is `upmonitor.py`. For the same functionality as `uptest.sh`, run:
```
$ python upmonitor.py -L log.txt &
$ python upview.py
```
This will start `upmonitor.py` logging to log.txt in the background, and then `upview.py` will watch the log file and show you each ping result as it happens.

`upmonitor.py` allows you to change the ping timeout, the server to ping, and allows more advanced methods than just `ping`. The most advanced method is `polo`, which uses a custom HTTP-based challenge/response protocol to avoid problems with networks which block pings and cache HTTP requests.

FYI, there is also an old script, `upanalyze.pl`, which will look at a log from `uptest.sh` and summarize the percent of uptime per hour graphically. It may or may not work with logs from recent versions.

Find the instructions for using each script by running it with the option `--help`. The scripts were developed on Ubuntu, but have also been tested on OS X. The Python scripts require Python 2.7, though, which I believe became default on OS X 10.7.

### Graphical display

`upmonitor.py` also writes a simple textual display of recent pings to a status file. Then you can display this file on your desktop, for instance in the Ubuntu Unity toolbar, using [indicator-sysmonitor](http://www.omgubuntu.co.uk/2011/03/indicator-sysmonitor-simple-system-stats-app-for-ubuntu).


## Captive portal detection

You've certainly encountered a "captive portal" before. When you connect to a public wifi hotspot, then try to start using your browser, but instead get greeted by a "Welcome! Please accept our terms and conditions.", that's a captive portal. Worse than just blocking your internet access, it intercepts it and replaces it with its own junk. This can play havoc with applications that expect to either get a valid response or none at all.

In response, modern operating systems have developed methods for detecting these interlopers. Generally, they send an HTTP request to a standard url, like Mozilla's http://detectportal.firefox.com/success.txt. Then, if they receive the expected response (Mozilla's url always returns the text `success\n`), they know it's a real connection. If the reponse is something else, like a redirect to a wecome page, or the HTML for the welcome page itself, then they know they've been "captured". The `upmonitor.py` method `httplib` does this.

This is great, and the current industry standard. However, I've run into the issue that some portals will cache responses, so that they'll return the correct response even when you're not actually connected! Even worse, some [sadistic portals](http://blog.tanaza.com/blog/bid/318805/iOS-7-and-captive-portal-a-guide-to-captive-portal-requirements) actively try to fool user agents into thinking their
connection isn't blocked even though it is.¹ That's why I developed the `polo` protocol to distinguish a real connection from an illusion. Basically, it not only makes an HTTP connection to a standard url, but it also sends a "challenge" (16 random characters). The server then [hashes](https://simple.wikipedia.org/wiki/Cryptographic_hash_function) this challenge and returns it. `upmonitor.py` then checks it's the right hash, and if so, it knows this is a real internet connection. This defeats caching and any captive portals deliberately trying to fool clients.

Of course, if anyone wanted to target this protocol specifically, they could easily spoof it. For now, I'm relying on obscurity, which is good enough when I'm the only one using this. But the protocol could easily be made spoof-proof by having the server cryptographically sign the response. That'd be a fun project at some point, but it's not necessary yet.

¹ Why would anyone do this? Well, usually when an OS discovers it's behind a captive portal, it pops up a window displaying the captive portal's welcome page so the user can click "accept" or log in, or whatever the portal wants you to do. This popup window is a little mini-browser, but it doesn't share any cookies with your main browser. It turns out the makers of the captive portal software (or their customers) don't like this because they really want those cookies! It's valuable personal data they can sell! Also, without cookies, their "Log in with Facebook/Twitter" buttons won't work as well, and those provide even juicier personal data! This isn't just an assumption, by they way. They freely admit as much [here](https://www.tanaza.com/features/free-social-wifi/) (here's an [archived copy](https://web.archive.org/web/20180811181321/https://www.tanaza.com/features/free-social-wifi/) in case they try to hide it).


## Credits

Thanks to Kasun Herath and Andrew Stanton for tail.py:  
https://github.com/kasun/python-tail
