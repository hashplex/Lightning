#! /usr/bin/env python3

"""A little curl-ish program."""

import sys
import requests

PORT = int(sys.argv[3])
URL = 'http://localhost:%d/' % PORT
if sys.argv[1] == 'block':
    URL += 'block-notify?block=%s' % sys.argv[2]
elif sys.argv[1] == 'wallet':
    URL += 'wallet-notify?tx=%s' % sys.argv[2]
else:
    raise Exception("Unknown notification", sys.argv[1])
requests.get(URL, auth=('rt', 'rt'))
