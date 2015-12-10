Captive Portal Detection
========================

Currently I use Google's URL: http://www.gstatic.com/generate_204  
If this doesn't return an HTTP 204, then we know we're blocked by an access point.
See Google Chrome's methods for captive portal detection:  
http://www.chromium.org/chromium-os/chromiumos-design-docs/network-portal-detection  
Unfortunately, some access points (like Greyhound bus wifi) seem to cache responses,
returning a 204 even when access is disallowed. Also, sometimes the current URL
(generate_204) doesn't work on attwifi for unknown reasons.

Also, some sadistic portals actively try to fool user agents into thinking their
connection isn't blocked even though it is (just so their crappy interception page's
terrible features can be viewed in full effect in a fully enabled browser):  
http://blog.tanaza.com/blog/bid/318805/iOS-7-and-captive-portal-a-guide-to-captive-portal-requirements  
Cisco also seems to make captive portal software which allows a similar bypass:  
https://supportforums.cisco.com/document/11934431/important-captive-portal-bypass-changes-needed-ios-7

Some more info on Apple's detection method, which uses as close to an actual standard
as I've seen so far:  
http://blog.erratasec.com/2010/09/apples-secret-wispr-request.html

List of known captive portal URLs:
* http://www.msftncsi.com/ncsi.txt
* http://www.apple.com/library/test/success.html
* http://google.com/generate_204
* http://www.gstatic.com/generate_204
* http://connectivitycheck.android.com/generate_204
* http://clients3.google.com/generate_204
* http://connectivitycheck.gstatic.com/generate_204