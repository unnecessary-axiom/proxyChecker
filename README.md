# ProxyChecker

ProxyChecker is a Python 3 script to test a list of socks/http proxies in a threaded manner. It supports IP range blacklisting and text search on the reached website.

## Installation

* Clone or download this repo: `git clone git@github.com:unnecessary-axiom/proxyChecker.git`
* Install dependencies `pip install -r requirements.txt`
* Run script: `python proxyChecker.py --arguments`

## Usage

In it's simplest form, run `python proxyChecker.py --input proxy_list.txt --output output.txt --proxy_type http`

Run `python proxyChecker.py -h` for full command list.

You'll need a list of proxies separated by newlines in the format `ip:port`. 

Output is in the format `proxy_type,response time in seconds,proxy ip:port`.

The exclusion list is a list of ranges separated by newlines. Ranges are defined in the slash format, or a range separated by a dash. For example, `10.0.0.0/8` or `8.8.8.8-8.8.8.9`. Lines that are blank or beginning with `#` are ignored.



`exclude.conf` sourced from https://raw.githubusercontent.com/robertdavidgraham/masscan/master/data/exclude.conf

It's recommended to check for text on the target webpage since many proxies have a login or initial redirect. 

