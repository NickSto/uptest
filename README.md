uptest
======

For a quick and simple connectivity monitor, run `$ bash uptest.sh`. This will ping google.com every 5 seconds and show the latency and whether the ping was dropped.

A more complete and polished script is `upmonitor.py`. For the same functionality as `uptest.sh`, run:
```
$ python upmonitor.py -L log.txt &
$ python upview.py
```
This will start `upmonitor.py` logging to log.txt in the background, and then `upview.py` will watch the log file and show you each ping result as it happens.

`upmonitor.py` allows you to change the ping timeout, the server to ping, and even whether to use ping or curl as the connection test (some networks block pings). It also writes a simple textual display of recent pings to a file. Then you can display this file on your desktop, for instance in the Ubuntu Unity toolbar, using [indicator-sysmonitor](http://www.omgubuntu.co.uk/2011/03/indicator-sysmonitor-simple-system-stats-app-for-ubuntu).

FYI, there is also an old, `upanalyze.pl`, which will look at a log from `uptest.sh` and summarize the % of uptime per hour graphically.

Find the instructions for using each script by running it with the option -h. All scripts have been tested on Ubuntu only, though they should in theory also work for OS X.

Thanks to Kasun Herath and Andrew Stanton for tail.py:  
https://github.com/kasun/python-tail

