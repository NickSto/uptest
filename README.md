uptest
======

For a quick and simple internet connectivity monitor, run `$ bash uptest.sh`. This will ping google.com every 5 seconds and show your latency and whether the ping was dropped.

A more complete and capable script is `upmonitor.py`. For the same functionality as `uptest.sh`, run:
```
$ python upmonitor.py -L log.txt &
$ python upview.py
```
This will start `upmonitor.py` logging to log.txt in the background, and then `upview.py` will watch the log file and show you each ping result as it happens.

`upmonitor.py` allows you to change the ping timeout, the server to ping, and allows more advanced methods than just `ping`. In particular, setting the method to `httplib` with the `-m` option makes it use an HTTP request, which avoids issues with ping being blocked on certain networks. It also allows detection of captive portals that intercept your connection with things like wifi login or terms of service pages.

`upmonitor.py` also writes a simple textual display of recent pings to a status file. Then you can display this file on your desktop, for instance in the Ubuntu Unity toolbar, using [indicator-sysmonitor](http://www.omgubuntu.co.uk/2011/03/indicator-sysmonitor-simple-system-stats-app-for-ubuntu).

FYI, there is also an old script, `upanalyze.pl`, which will look at a log from `uptest.sh` and summarize the % of uptime per hour graphically. It may or may not work with logs from recent versions.

Find the instructions for using each script by running it with the option -h. The scripts were developed on Ubuntu, but have also been tested on OS X. The Python scripts require Python 2.7, though, which I believe became default on OS X 10.7.

Thanks to Kasun Herath and Andrew Stanton for tail.py:  
https://github.com/kasun/python-tail

